"""Camera controller - async consumer loop and lifecycle management."""

import asyncio
import contextlib
import logging
import time
from pathlib import Path
from typing import Optional, Callable

from .state import CameraState, Settings, Metrics, Phase, RecordingPhase
from ..capture import (
    USBCamera,
    AudioCapture,
    FrameRingBuffer,
    AudioRingBuffer,
    CapturedFrame,
)

try:
    from rpi_logger.modules.base.storage_utils import module_filename_prefix, sanitize_device_id
except ImportError:
    module_filename_prefix = None
    sanitize_device_id = None

logger = logging.getLogger(__name__)


class CameraController:
    """Controls USB camera lifecycle and frame routing.

    Records ALL frames from camera without rate limiting. The camera is
    configured for the desired FPS via fps_hint, and we record everything
    it delivers. Preview is throttled via preview_divisor to reduce UI load.
    """

    def __init__(self):
        """Initialize controller."""
        self._state = CameraState()
        self._subscribers: list[Callable[[CameraState], None]] = []

        # Capture components
        self._frame_buffer: Optional[FrameRingBuffer] = None
        self._audio_buffer: Optional[AudioRingBuffer] = None
        self._camera: Optional[USBCamera] = None
        self._audio: Optional[AudioCapture] = None
        self._consumer_task: Optional[asyncio.Task] = None

        # Recording components (imported lazily)
        self._recorder = None
        self._muxer = None
        self._timing = None

        # Preview callback
        self._preview_callback: Optional[Callable[[bytes], None]] = None

        # Recording state
        self._frames_recorded = 0

    def subscribe(self, callback: Callable[[CameraState], None]) -> None:
        """Subscribe to state changes."""
        self._subscribers.append(callback)
        callback(self._state)

    def unsubscribe(self, callback: Callable[[CameraState], None]) -> None:
        """Unsubscribe from state changes."""
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def _notify(self) -> None:
        """Notify all subscribers of state change."""
        for sub in self._subscribers:
            try:
                sub(self._state)
            except Exception as e:
                logger.error("Subscriber error: %s", e)

    def set_preview_callback(self, callback: Optional[Callable[[bytes], None]]) -> None:
        """Set callback for preview frames (PPM data)."""
        self._preview_callback = callback

    @property
    def state(self) -> CameraState:
        """Current camera state."""
        return self._state

    async def start_streaming(
        self,
        device: int | str,
        device_info: dict,
    ) -> bool:
        """Open camera and start capture.

        Args:
            device: Camera device index or path
            device_info: Device information from DeviceSystem

        Returns:
            True on success
        """
        if self._state.phase != Phase.IDLE:
            logger.warning("Cannot start streaming: phase=%s", self._state.phase)
            return False

        self._state.phase = Phase.STARTING
        self._state.device_name = device_info.get("name", str(device))
        self._state.has_audio = device_info.get("has_audio", False)
        self._notify()

        try:
            loop = asyncio.get_running_loop()

            # Create frame buffer and bind to event loop
            self._frame_buffer = FrameRingBuffer(capacity=8)
            self._frame_buffer.bind_loop(loop)

            # Create and open camera (run in thread to avoid blocking async loop)
            self._camera = USBCamera(
                device=device,
                resolution=self._state.settings.resolution,
                fps_hint=float(self._state.settings.frame_rate),
                buffer=self._frame_buffer,
            )

            # Camera open can be slow (especially MSMF on Windows), run in thread
            logger.info("Opening camera %s (this may take a moment)...", device)
            opened = await loop.run_in_executor(None, self._camera.open)
            if not opened:
                raise RuntimeError(f"Failed to open camera: {device}")

            # Setup audio if enabled and available
            if self._state.settings.audio_enabled and self._state.has_audio:
                await self._setup_audio(device_info, loop)

            # Start capture
            self._camera.start()
            if self._audio:
                self._audio.start()

            # Start consumer loop
            self._consumer_task = asyncio.create_task(self._consumer_loop())

            self._state.phase = Phase.STREAMING
            self._notify()

            logger.info(
                "Streaming started: device=%s, resolution=%s, audio=%s",
                device,
                self._camera.resolution,
                self._audio is not None,
            )
            return True

        except Exception as e:
            logger.error("Failed to start streaming: %s", e, exc_info=True)
            self._state.phase = Phase.ERROR
            self._state.error = str(e)
            self._notify()
            await self._cleanup()
            return False

    async def _setup_audio(
        self, device_info: dict, loop: asyncio.AbstractEventLoop
    ) -> None:
        """Setup audio capture if available."""
        audio_device = self._state.settings.audio_device_index
        if audio_device is None:
            audio_device = device_info.get("audio_device_index")

        if audio_device is None:
            logger.warning("Audio enabled but no audio device found")
            return

        self._audio_buffer = AudioRingBuffer(capacity=32)
        self._audio_buffer.bind_loop(loop)

        supported_rates = device_info.get("supported_sample_rates", ())

        self._audio = AudioCapture(
            device_index=audio_device,
            sample_rate=self._state.settings.sample_rate,
            channels=self._state.settings.audio_channels,
            buffer=self._audio_buffer,
            supported_rates=supported_rates,
        )

        if not self._audio.open():
            logger.warning("Failed to open audio device %d", audio_device)
            self._audio = None
            self._audio_buffer = None

    async def stop_streaming(self) -> None:
        """Stop capture and release camera."""
        if self._state.recording_phase == RecordingPhase.RECORDING:
            await self.stop_recording()

        # Cancel consumer task with timeout
        if self._consumer_task:
            self._consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
                await asyncio.wait_for(self._consumer_task, timeout=2.0)
            self._consumer_task = None

        await self._cleanup()

        self._state.phase = Phase.IDLE
        self._state.error = ""
        self._notify()

        logger.info("Streaming stopped")

    async def _cleanup(self) -> None:
        """Release all resources with timeout protection."""
        loop = asyncio.get_running_loop()
        try:
            await asyncio.wait_for(
                loop.run_in_executor(None, self._cleanup_sync),
                timeout=3.0
            )
        except asyncio.TimeoutError:
            logger.warning("Cleanup timed out after 3s - forcing resource release")
            # Force cleanup even if it might leave resources in bad state
            self._force_cleanup()

    def _cleanup_sync(self) -> None:
        """Synchronous cleanup (runs in thread to avoid blocking event loop)."""
        if self._frame_buffer:
            self._frame_buffer.stop()
            self._frame_buffer = None

        if self._audio_buffer:
            self._audio_buffer.stop()
            self._audio_buffer = None

        if self._audio:
            self._audio.close()
            self._audio = None

        if self._camera:
            self._camera.close()
            self._camera = None

    def _force_cleanup(self) -> None:
        """Force cleanup by nullifying references (used after timeout)."""
        self._frame_buffer = None
        self._audio_buffer = None
        self._audio = None
        self._camera = None

    async def start_recording(
        self, output_dir: Path, trial: int, *, trial_label: str = "", cameras_dir: Optional[Path] = None
    ) -> bool:
        """Start recording to file.

        Args:
            output_dir: Directory for output files (e.g., session/Cameras/device_id/)
            trial: Trial number
            trial_label: Optional trial label for CSV metadata
            cameras_dir: Optional module data directory for token derivation
                        (e.g., session/Cameras/). If not provided, uses output_dir.

        Returns:
            True on success
        """
        if self._state.phase != Phase.STREAMING:
            logger.warning("Cannot record: not streaming")
            return False
        if self._state.recording_phase != RecordingPhase.STOPPED:
            logger.warning("Already recording")
            return False

        output_dir.mkdir(parents=True, exist_ok=True)

        # Determine FPS for video container metadata
        # Use min of requested and measured hardware FPS for accurate playback speed
        requested_fps = self._state.settings.frame_rate
        hardware_fps = self._camera.hardware_fps if self._camera else requested_fps
        if hardware_fps > 1:
            actual_fps = min(requested_fps, max(1, int(hardware_fps + 0.5)))
        else:
            actual_fps = requested_fps

        self._frames_recorded = 0

        # Import recording modules
        from ..recording import VideoRecorder, TimingWriter

        resolution = (
            self._camera.resolution if self._camera else self._state.settings.resolution
        )

        # Determine if we need muxing (audio + video)
        use_muxer = (
            self._state.settings.audio_enabled
            and self._audio is not None
            and self._audio.is_running
        )

        # Build filename using standard module prefix
        device_name = self._state.device_name or "camera"
        safe_name = sanitize_device_id(device_name) if sanitize_device_id else device_name.lower()

        # Use cameras_dir for token derivation (so derive_session_token can climb to session)
        prefix_dir = cameras_dir if cameras_dir else output_dir
        if module_filename_prefix:
            prefix = module_filename_prefix(prefix_dir, "Cameras", trial, code="CAM")
            video_base = f"{prefix}_{safe_name}"
        else:
            # Fallback when running standalone without Logger
            video_base = f"trial{trial:03d}_{safe_name}"

        if use_muxer:
            from ..recording import AVMuxer

            video_path = output_dir / f"{video_base}.mp4"
            self._muxer = AVMuxer(
                path=video_path,
                resolution=resolution,
                video_fps=actual_fps,
                sample_rate=self._audio.sample_rate,
                audio_channels=self._audio.channels,
            )
            await self._muxer.start()
            self._recorder = None
        else:
            video_path = output_dir / f"{video_base}.avi"
            self._recorder = VideoRecorder(
                path=video_path,
                resolution=resolution,
                fps=actual_fps,
            )
            await self._recorder.start()
            self._muxer = None

        timing_path = output_dir / f"{video_base}_timing.csv"
        self._timing = TimingWriter(timing_path, trial, safe_name, trial_label)
        await self._timing.start()

        self._state.recording_phase = RecordingPhase.RECORDING
        self._state.session_dir = output_dir
        self._state.trial_number = trial
        self._notify()

        logger.info(
            "Recording started: %s at %d fps (requested=%d, hardware=%.1f, muxer=%s)",
            video_path,
            actual_fps,
            requested_fps,
            hardware_fps,
            use_muxer,
        )
        return True

    async def stop_recording(self) -> None:
        """Stop recording."""
        if self._recorder:
            await self._recorder.stop()
            self._recorder = None

        if self._muxer:
            await self._muxer.stop()
            self._muxer = None

        if self._timing:
            await self._timing.stop()
            self._timing = None

        self._state.recording_phase = RecordingPhase.STOPPED
        self._notify()

        logger.info("Recording stopped: %d frames", self._frames_recorded)

    async def _consumer_loop(self) -> None:
        """Consume frames from capture buffer and route to recording/preview.

        Records ALL frames from camera - no rate limiting. The camera is already
        configured for the desired FPS via fps_hint. Preview is throttled via
        preview_divisor to reduce UI overhead.
        """
        if not self._frame_buffer:
            return

        # Start audio consumer if available
        audio_task = None
        if self._audio_buffer and self._audio:
            audio_task = asyncio.create_task(self._audio_consumer_loop())

        # Timing state for preview and metrics (wall-clock based)
        preview_next = 0.0
        metrics_next = 0.0

        # FPS tracking via timestamp lists
        record_frame_times: list[float] = []
        preview_times: list[float] = []

        frame_count = 0
        logger.debug("Consumer loop started")

        def calc_fps(times: list[float]) -> float:
            """Calculate FPS from timestamp list."""
            if len(times) < 2:
                return 0.0
            elapsed = times[-1] - times[0]
            return (len(times) - 1) / elapsed if elapsed > 0 else 0.0

        try:
            async for frame in self._frame_buffer.frames():
                now = time.monotonic()
                frame_count += 1

                # Initialize timing on first frame
                if frame_count == 1:
                    logger.debug("First frame: %dx%d", frame.size[0], frame.size[1])
                    preview_next = now
                    metrics_next = now + 1.0

                # Preview interval from settings
                settings = self._state.settings
                base_interval = 1.0 / settings.frame_rate if settings.frame_rate > 0 else 1.0 / 30
                preview_interval = base_interval * settings.preview_divisor

                # Record ALL frames - no rate limiting
                if self._state.recording_phase == RecordingPhase.RECORDING:
                    await self._record_frame(frame)
                    self._frames_recorded += 1
                    frame_time = frame.timestamp_ns / 1e9
                    record_frame_times.append(frame_time)
                    if len(record_frame_times) > 30:
                        record_frame_times.pop(0)

                # Preview frame if due
                if self._preview_callback and now >= preview_next:
                    preview_data = self._frame_to_preview(frame)
                    if preview_data:
                        self._preview_callback(preview_data)
                    preview_times.append(now)
                    if len(preview_times) > 30:
                        preview_times.pop(0)
                    preview_next += preview_interval
                    if preview_next < now:
                        preview_next = now + preview_interval

                # Update metrics every second
                if now >= metrics_next:
                    metrics_next = now + 1.0
                    self._state.metrics = Metrics(
                        hardware_fps=self._camera.hardware_fps if self._camera else 0.0,
                        record_fps=calc_fps(record_frame_times),
                        preview_fps=calc_fps(preview_times),
                        frames_captured=self._camera.frame_count if self._camera else 0,
                        frames_recorded=self._frames_recorded,
                        frames_dropped=self._frame_buffer.drops if self._frame_buffer else 0,
                        audio_chunks=self._audio.chunk_count if self._audio else 0,
                    )
                    self._notify()

        except asyncio.CancelledError:
            if audio_task:
                audio_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await audio_task
            raise
        except Exception as e:
            logger.error("Consumer loop error: %s", e, exc_info=True)

    async def _audio_consumer_loop(self) -> None:
        """Consume audio chunks and write to muxer."""
        if not self._audio_buffer:
            return

        try:
            async for chunk in self._audio_buffer.chunks():
                if (
                    self._state.recording_phase == RecordingPhase.RECORDING
                    and self._muxer
                ):
                    await self._muxer.write_audio(chunk)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Audio consumer error: %s", e)

    async def _record_frame(self, frame: CapturedFrame) -> None:
        """Record a single frame."""
        if self._muxer:
            await self._muxer.write_video(frame)
        elif self._recorder:
            await self._recorder.write_frame(frame)

        if self._timing:
            await self._timing.write_frame(frame)

    def _frame_to_preview(self, frame: CapturedFrame) -> Optional[bytes]:
        """Convert frame to PPM for Tkinter."""
        try:
            import cv2

            rgb = cv2.cvtColor(frame.data, cv2.COLOR_BGR2RGB)

            scale = self._state.settings.preview_scale
            if scale < 1.0:
                h, w = rgb.shape[:2]
                new_w = max(1, int(w * scale))
                new_h = max(1, int(h * scale))
                rgb = cv2.resize(
                    rgb, (new_w, new_h), interpolation=cv2.INTER_NEAREST
                )

            h, w = rgb.shape[:2]
            ppm_data = f"P6\n{w} {h}\n255\n".encode() + rgb.tobytes()

            if frame.frame_number <= 3:
                logger.debug("Preview frame %d: %dx%d, scale=%.2f, ppm_len=%d",
                             frame.frame_number, w, h, scale, len(ppm_data))

            return ppm_data
        except Exception as e:
            logger.error("Preview conversion error: %s", e, exc_info=True)
            return None

    async def apply_settings(self, settings: Settings) -> None:
        """Apply new settings.

        Note: Resolution changes require restart.
        """
        old = self._state.settings
        self._state.settings = settings

        if self._state.phase == Phase.STREAMING:
            if old.resolution != settings.resolution:
                logger.info(
                    "Resolution change from %s to %s requires restart",
                    old.resolution,
                    settings.resolution,
                )

        self._notify()
