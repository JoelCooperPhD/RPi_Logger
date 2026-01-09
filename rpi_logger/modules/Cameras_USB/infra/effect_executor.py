"""Effect executor for USB camera module.

Handles side effects requested by the reducer:
- Camera probing and knowledge management
- Camera open/close and capture
- Audio device matching
- Recording to disk
"""

import asyncio
from pathlib import Path
from typing import Callable, Awaitable, Optional, Any
import logging

from ..core.state import (
    CameraCapabilities, CameraSettings,
    FrameMetrics, USBDeviceInfo, USBAudioDevice,
)
from ..core.actions import (
    Action,
    ProbingProgress, CameraReady, CameraError,
    AudioReady, AudioError,
    StreamingStarted,
    RecordingStarted, RecordingStopped, SettingsApplied,
    UpdateMetrics,
)
from ..core.effects import (
    Effect,
    EnsureCameraProbed, ProbeAudio,
    OpenCamera, CloseCamera, StartCapture, StopCapture, ApplyCameraSettings,
    OpenAudioDevice, CloseAudioDevice, StartAudioStream, StopAudioStream,
    StartEncoder, StopEncoder, StartMuxer, StopMuxer, StartTimingWriter, StopTimingWriter,
    SendStatus, CleanupResources,
)
from ..capture import USBSource, AudioSource, CapturedFrame
from ..recording import RecordingSession
from ..discovery import (
    probe_camera_modes,
    verify_camera_accessible,
    match_audio_to_camera,
    CameraKnowledge,
)

logger = logging.getLogger(__name__)


class EffectExecutor:
    """Executes side effects for the USB camera module."""

    def __init__(
        self,
        knowledge: CameraKnowledge,
        status_callback: Optional[Callable[[str, dict], None]] = None,
        settings_save_callback: Optional[Callable[..., None]] = None,
    ):
        self._knowledge = knowledge
        self._status_callback = status_callback
        self._settings_save_callback = settings_save_callback

        self._camera: Optional[USBSource] = None
        self._audio: Optional[AudioSource] = None
        self._recording: Optional[RecordingSession] = None

        self._capture_task: Optional[asyncio.Task] = None
        self._audio_task: Optional[asyncio.Task] = None

        self._preview_callback: Optional[Callable[[bytes], None]] = None
        self._device_info: Optional[USBDeviceInfo] = None
        self._audio_device: Optional[USBAudioDevice] = None
        self._settings = CameraSettings()

    def set_preview_callback(self, callback: Optional[Callable[[bytes], None]]) -> None:
        self._preview_callback = callback

    def set_device_info(self, device_info: USBDeviceInfo) -> None:
        self._device_info = device_info

    async def __call__(
        self,
        effect: Effect,
        dispatch: Callable[[Action], Awaitable[None]]
    ) -> None:
        """Execute an effect."""
        match effect:
            case EnsureCameraProbed(device, vid_pid, display_name):
                await self._ensure_probed(device, vid_pid, display_name, dispatch)

            case ProbeAudio(bus_path):
                await self._probe_audio(bus_path, dispatch)

            case OpenCamera(device, resolution, fps):
                await self._open_camera(device, resolution, fps)

            case CloseCamera():
                await self._close_camera()

            case StartCapture():
                self._start_capture_loop(dispatch)

            case StopCapture():
                await self._stop_capture_loop()

            case ApplyCameraSettings(settings):
                await self._apply_settings(settings, dispatch)

            case OpenAudioDevice(sounddevice_index, sample_rate, channels, supported_rates):
                await self._open_audio(sounddevice_index, sample_rate, channels, supported_rates)

            case CloseAudioDevice():
                await self._close_audio()

            case StartAudioStream():
                self._start_audio_loop(dispatch)

            case StopAudioStream():
                await self._stop_audio_loop()

            case StartEncoder(video_path, fps, resolution, with_audio):
                await self._start_recording(video_path, fps, resolution, with_audio, dispatch)

            case StopEncoder():
                await self._stop_recording(dispatch)

            case StartMuxer(output_path, video_fps, resolution, audio_sample_rate, audio_channels):
                pass  # Handled by RecordingSession

            case StopMuxer():
                pass

            case StartTimingWriter(output_path):
                pass  # Handled by RecordingSession

            case StopTimingWriter():
                pass

            case SendStatus(status_type, payload):
                if self._status_callback:
                    self._status_callback(status_type, payload)

            case CleanupResources():
                await self._cleanup()

    async def _ensure_probed(
        self,
        device: int | str,
        vid_pid: str,
        display_name: str,
        dispatch: Callable[[Action], Awaitable[None]]
    ) -> None:
        """Ensure camera capabilities are known - probe if needed."""
        try:
            # Check if we already know this camera
            profile = await self._knowledge.get(vid_pid)

            if profile:
                # Known camera - verify it's still accessible
                await dispatch(ProbingProgress("Verifying camera..."))
                accessible = await verify_camera_accessible(device)

                if accessible:
                    logger.info("Known camera %s (%s) - using cached %d modes",
                               vid_pid, display_name, len(profile.modes))
                    capabilities = CameraCapabilities(
                        camera_id=f"usb:{device}",
                        modes=tuple(profile.modes),
                        controls={},
                        default_resolution=profile.default_resolution,
                        default_fps=profile.default_fps,
                    )
                    await dispatch(CameraReady(capabilities))
                    return
                else:
                    logger.warning("Known camera %s not accessible, will re-probe", vid_pid)

            # Unknown camera or failed verification - probe it
            await dispatch(ProbingProgress("Probing camera modes..."))

            loop = asyncio.get_running_loop()
            def on_progress(msg: str):
                loop.call_soon_threadsafe(
                    lambda: loop.create_task(dispatch(ProbingProgress(msg)))
                )

            probed_modes = await probe_camera_modes(device, on_progress=on_progress)

            # Create profile with filtered modes
            profile = CameraKnowledge.create_profile_from_probe(
                vid_pid=vid_pid,
                display_name=display_name,
                probed_modes=probed_modes,
            )

            # Store in knowledge
            await self._knowledge.register(profile)

            capabilities = CameraCapabilities(
                camera_id=f"usb:{device}",
                modes=tuple(profile.modes),
                controls={},
                default_resolution=profile.default_resolution,
                default_fps=profile.default_fps,
            )

            logger.info("Probed camera %s: %d modes (filtered from %d)",
                       vid_pid, len(profile.modes), len(probed_modes))
            await dispatch(CameraReady(capabilities))

        except Exception as e:
            logger.error("Camera probing failed: %s", e)
            await dispatch(CameraError(str(e)))

    async def _probe_audio(
        self,
        bus_path: str,
        dispatch: Callable[[Action], Awaitable[None]]
    ) -> None:
        """Find matching audio device for the camera."""
        try:
            audio_device = await match_audio_to_camera(bus_path)
            self._audio_device = audio_device
            await dispatch(AudioReady(audio_device))
        except Exception as e:
            logger.warning("Audio probing failed: %s", e)
            await dispatch(AudioReady(None))

    async def _open_camera(
        self,
        device: int | str,
        resolution: tuple[int, int],
        fps: float,
    ) -> None:
        if self._camera:
            self._camera.close()

        self._camera = USBSource(
            device=device,
            resolution=resolution,
            fps=fps,
        )

        def on_error(msg: str):
            logger.error("Camera error: %s", msg)

        self._camera.set_error_callback(on_error)

        if not self._camera.open():
            raise RuntimeError(f"Failed to open camera {device}")

        self._settings = CameraSettings(
            resolution=self._camera.resolution,
            frame_rate=int(fps),
        )

    async def _close_camera(self) -> None:
        if self._camera:
            self._camera.close()
            self._camera = None

    def _start_capture_loop(self, dispatch: Callable[[Action], Awaitable[None]]) -> None:
        if self._capture_task and not self._capture_task.done():
            return

        if self._camera:
            self._camera.start_capture()
            self._capture_task = asyncio.create_task(self._capture_loop(dispatch))

    async def _stop_capture_loop(self) -> None:
        if self._camera:
            self._camera.stop_capture()

        if self._capture_task:
            self._capture_task.cancel()
            try:
                await self._capture_task
            except asyncio.CancelledError:
                pass
            self._capture_task = None

    async def _capture_loop(self, dispatch: Callable[[Action], Awaitable[None]]) -> None:
        if not self._camera:
            return

        frame_count = 0
        record_count = 0
        preview_count = 0
        preview_divisor = self._settings.preview_divisor

        capture_start_time = 0.0
        record_intervals: list[float] = []
        preview_intervals: list[float] = []
        last_record_time = 0.0
        last_preview_time = 0.0
        record_fps_actual = 0.0
        preview_fps_actual = 0.0

        async for frame in self._camera.frames():
            frame_count += 1
            now = frame.wall_time

            if capture_start_time == 0.0:
                capture_start_time = now

            if self._recording:
                await self._recording.write_frame(frame)
                record_count += 1
                if last_record_time > 0:
                    record_intervals.append(now - last_record_time)
                    if len(record_intervals) > 30:
                        record_intervals.pop(0)
                    if len(record_intervals) >= 3:
                        avg_interval = sum(record_intervals) / len(record_intervals)
                        record_fps_actual = 1.0 / avg_interval if avg_interval > 0 else 0.0
                last_record_time = now

            if self._preview_callback and frame_count % preview_divisor == 0:
                preview_data = self._frame_to_ppm(frame)
                if preview_data:
                    self._preview_callback(preview_data)
                preview_count += 1
                if last_preview_time > 0:
                    preview_intervals.append(now - last_preview_time)
                    if len(preview_intervals) > 30:
                        preview_intervals.pop(0)
                    if len(preview_intervals) >= 5:
                        avg_interval = sum(preview_intervals) / len(preview_intervals)
                        preview_fps_actual = 1.0 / avg_interval if avg_interval > 0 else 0.0
                last_preview_time = now

            if frame_count % 30 == 0:
                elapsed = now - capture_start_time
                capture_fps_actual = frame_count / elapsed if elapsed > 0 else 0.0
                metrics = FrameMetrics(
                    frames_captured=frame_count,
                    frames_recorded=record_count,
                    frames_previewed=preview_count,
                    frames_dropped=self._camera.drops,
                    audio_chunks_captured=self._audio.chunk_count if self._audio else 0,
                    last_frame_time=now,
                    capture_fps_actual=capture_fps_actual,
                    record_fps_actual=record_fps_actual,
                    preview_fps_actual=preview_fps_actual,
                )
                await dispatch(UpdateMetrics(metrics))

    def _frame_to_ppm(self, frame: CapturedFrame) -> Optional[bytes]:
        try:
            import cv2

            rgb = frame.data
            if frame.color_format == "BGR":
                rgb = cv2.cvtColor(frame.data, cv2.COLOR_BGR2RGB)

            scale = self._settings.preview_scale
            if scale < 1.0:
                h, w = rgb.shape[:2]
                new_w = int(w * scale)
                new_h = int(h * scale)
                if new_w > 0 and new_h > 0:
                    rgb = cv2.resize(rgb, (new_w, new_h), interpolation=cv2.INTER_NEAREST)

            h, w = rgb.shape[:2]
            header = f"P6\n{w} {h}\n255\n".encode('ascii')
            return header + rgb.tobytes()
        except Exception as e:
            logger.warning("Preview frame error: %s", e)
            return None

    async def _apply_settings(
        self,
        settings: CameraSettings,
        dispatch: Callable[[Action], Awaitable[None]]
    ) -> None:
        old_settings = self._settings
        self._settings = settings

        resolution_changed = old_settings.resolution != settings.resolution
        fps_changed = old_settings.frame_rate != settings.frame_rate

        if self._camera and (resolution_changed or fps_changed):
            # Stop capture task before reconfiguring
            await self._stop_capture_loop()

            # Reconfigure camera (closes and reopens with new settings)
            self._camera.close()
            self._camera = USBSource(
                device=self._camera._device,
                resolution=settings.resolution,
                fps=float(settings.frame_rate),
            )
            self._camera.set_error_callback(lambda msg: logger.error("Camera error: %s", msg))

            if self._camera.open():
                # Restart capture loop
                self._start_capture_loop(dispatch)
            else:
                logger.error("Failed to reopen camera with new settings")

        if self._settings_save_callback:
            self._settings_save_callback(settings)

        await dispatch(SettingsApplied(settings))

    async def _open_audio(
        self,
        sounddevice_index: int,
        sample_rate: int,
        channels: int,
        supported_rates: tuple[int, ...] = (),
    ) -> None:
        if self._audio:
            self._audio.close()

        self._audio = AudioSource(
            device_index=sounddevice_index,
            sample_rate=sample_rate,
            channels=channels,
            supported_rates=supported_rates,
        )

        def on_error(msg: str):
            logger.error("Audio error: %s", msg)

        self._audio.set_error_callback(on_error)
        self._audio.open()

    async def _close_audio(self) -> None:
        if self._audio:
            self._audio.close()
            self._audio = None

    def _start_audio_loop(self, dispatch: Callable[[Action], Awaitable[None]]) -> None:
        if self._audio_task and not self._audio_task.done():
            return

        if self._audio:
            self._audio.start_capture()
            self._audio_task = asyncio.create_task(self._audio_loop(dispatch))

    async def _stop_audio_loop(self) -> None:
        if self._audio:
            self._audio.stop_capture()

        if self._audio_task:
            self._audio_task.cancel()
            try:
                await self._audio_task
            except asyncio.CancelledError:
                pass
            self._audio_task = None

    async def _audio_loop(self, dispatch: Callable[[Action], Awaitable[None]]) -> None:
        if not self._audio:
            return

        async for chunk in self._audio.chunks():
            if self._recording:
                await self._recording.write_audio(chunk)

    async def _start_recording(
        self,
        video_path: Path,
        fps: int,
        resolution: tuple[int, int],
        with_audio: bool,
        dispatch: Callable[[Action], Awaitable[None]]
    ) -> None:
        session_dir = video_path.parent.parent
        trial = int(video_path.stem.split('_')[1]) if '_' in video_path.stem else 1
        device_id = self._device_info.stable_id if self._device_info else "usbcam0"

        self._recording = RecordingSession(
            session_dir=session_dir,
            device_id=device_id,
            trial_number=trial,
            resolution=resolution,
            fps=fps,
            with_audio=with_audio,
            audio_sample_rate=self._settings.sample_rate,
            audio_channels=self._audio_device.channels if self._audio_device else 2,
        )
        await self._recording.start()
        await dispatch(RecordingStarted())

        if self._status_callback:
            self._status_callback("recording_started", {
                "video_path": str(video_path),
                "device_id": device_id,
                "with_audio": with_audio,
            })

    async def _stop_recording(self, dispatch: Callable[[Action], Awaitable[None]]) -> None:
        if self._recording:
            await self._recording.stop()
            self._recording = None

        await dispatch(RecordingStopped())

        if self._status_callback:
            self._status_callback("recording_stopped", {})

    async def _cleanup(self) -> None:
        await self._stop_capture_loop()
        await self._stop_audio_loop()

        if self._recording:
            await self._recording.stop()
            self._recording = None

        await self._close_camera()
        await self._close_audio()
