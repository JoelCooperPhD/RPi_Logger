import asyncio
import time
from typing import Optional

from rpi_logger.core.logging_utils import get_module_logger
from .config.tracker_config import TrackerConfig as Config
from .device_manager import DeviceManager
from .stream_handler import StreamHandler, FramePacket
from .frame_processor import FrameProcessor
from .recording import RecordingManager
from .rolling_fps import RollingFPS

logger = get_module_logger(__name__)


class GazeTracker:

    def __init__(
        self,
        config: Config,
        *,
        device_manager: Optional[DeviceManager] = None,
        stream_handler: Optional[StreamHandler] = None,
        frame_processor: Optional[FrameProcessor] = None,
        recording_manager: Optional[RecordingManager] = None,
        display_enabled: bool = True,
    ):
        self.config = config
        self.running = False
        self.display_enabled = display_enabled  # Controls OpenCV window display

        # Phase 1.4: Pause state
        self._paused = False
        # Phase 1.6: Reduced processing mode (when window not visible)
        self._reduced_processing = False

        self.frame_count = 0
        self.start_time = None
        self.no_frame_timeouts = 0  # When no frames available from stream

        self._latest_display_frame = None
        self._display_fps_tracker = RollingFPS(window_seconds=5.0)

        # Frame skip counters for downsampling (checked before any processing)
        # Note: Single-writer pattern - only modified in _process_frames() coroutine.
        # CPython GIL protects simple increments; no lock needed.
        self._preview_frame_counter = 0
        self._recording_frame_counter = 0
        self._eyes_frame_counter = 0

        self.device_manager = device_manager or DeviceManager()
        self.device_manager.audio_stream_param = config.audio_stream_param
        self.stream_handler = stream_handler or StreamHandler()
        self.frame_processor = frame_processor or FrameProcessor(config)
        self.recording_manager = recording_manager or RecordingManager(config)
        self.stream_handler.set_imu_listener(self.recording_manager.write_imu_sample)
        self.stream_handler.set_event_listener(self.recording_manager.write_event_sample)

    # Phase 1.4: Pause/resume methods
    async def pause(self):
        """
        Pause frame processing to save CPU while keeping streams alive.

        This is useful when the Eye Tracker module is visible in the UI
        but not actively being monitored. Streams stay connected so
        resume is fast.
        """
        if self._paused:
            return

        self._paused = True

    async def resume(self):
        """
        Resume normal frame processing after pause.
        """
        if not self._paused:
            return

        self._paused = False

    @property
    def is_paused(self) -> bool:
        """Check if currently paused"""
        return self._paused

    def set_reduced_processing(self, enabled: bool) -> None:
        """Enable reduced processing when window not visible."""
        self._reduced_processing = enabled

    @property
    def is_reduced_processing(self) -> bool:
        """Check if in reduced processing mode"""
        return self._reduced_processing

    def get_display_fps(self) -> float:
        """Get current display output FPS."""
        return self._display_fps_tracker.get_fps()

    async def run(self):
        if not self.device_manager.is_connected:
            logger.error("No device connected")
            return

        self.running = True
        self.start_time = time.time()

        if self.display_enabled:
            self.frame_processor.create_window()

        try:
            experiment_dir = None
            if getattr(self.recording_manager, "current_experiment_dir", None) is None:
                try:
                    experiment_dir = self.recording_manager.start_experiment()
                except Exception as exc:
                    logger.error("Failed to initialize experiment directory: %s", exc)

            stream_urls = self.device_manager.get_stream_urls()

            stream_tasks = await self.stream_handler.start_streaming(
                stream_urls["video"],
                stream_urls["gaze"],
                imu_url=stream_urls.get("imu"),
                events_url=stream_urls.get("events"),
                audio_url=stream_urls.get("audio"),
                eyes_url=stream_urls.get("eyes"),
            ) or []

            frame_task = asyncio.create_task(self._process_frames(), name="frame-processor")

            try:
                await frame_task
            finally:
                await self.stream_handler.stop_streaming()
                if stream_tasks:
                    await asyncio.gather(*stream_tasks, return_exceptions=True)

        except KeyboardInterrupt:
            pass
        except Exception as e:
            logger.error("Runtime error: %s", e)
        finally:
            await self.cleanup()

    async def _process_frames(self):
        # Track time without frames for warnings (elapsed-time based)
        no_frame_since: Optional[float] = None
        warned_5s = False

        while self.running:
            try:
                # Phase 1.4: Check pause state early in loop
                if self._paused:
                    # Idle sleep with minimal CPU usage
                    # Streams stay alive in background
                    await asyncio.sleep(0.1)
                    continue

                # Phase 1.6: Reduced processing mode when not visible and not recording
                # Skip processing on 9/10 frames but don't artificially delay
                if self._reduced_processing and not self.recording_manager.is_recording:
                    if self.frame_count % 10 != 0:
                        # Drain the frame without processing
                        _ = await self.stream_handler.wait_for_frame(timeout=1.0)
                        self.frame_count += 1
                        continue

                # Wait for next frame with a reasonable timeout for stream health detection
                try:
                    frame_packet: Optional[FramePacket] = await self.stream_handler.wait_for_frame(timeout=1.0)
                except asyncio.TimeoutError:
                    frame_packet = None

                if frame_packet is None:
                    self.no_frame_timeouts += 1

                    # Track elapsed time without frames for warnings
                    if no_frame_since is None:
                        no_frame_since = time.perf_counter()
                    elapsed = time.perf_counter() - no_frame_since
                    if elapsed >= 5.0 and not warned_5s:
                        logger.warning("No frames received for 5 seconds")
                        warned_5s = True
                    continue

                # Reset no-frame tracking on successful frame
                self.frame_count += 1
                no_frame_since = None
                warned_5s = False

                raw_frame = frame_packet.image

                # === EARLY SKIP CHECK ===
                # Determine if we need this frame BEFORE any expensive processing.
                # This saves ~66% CPU at 10fps (skip 2/3 of frames).
                self._preview_frame_counter += 1
                self._recording_frame_counter += 1

                preview_skip_factor = self.config.preview_skip_factor()
                recording_skip_factor = self.config.recording_skip_factor()

                skip_display = (self._preview_frame_counter % preview_skip_factor != 0)
                # Only skip recording frames when actively recording
                is_recording = self.recording_manager.is_recording
                skip_recording = is_recording and (self._recording_frame_counter % recording_skip_factor != 0)

                # === STREAM DRAINING (always runs at 30fps) ===
                # Must drain all streams to prevent queue buildup, regardless of skip state
                latest_gaze = self.stream_handler.get_latest_gaze()
                while True:
                    next_gaze = await self.stream_handler.next_gaze(timeout=0)
                    if next_gaze is None:
                        break
                    latest_gaze = next_gaze

                latest_imu = self.stream_handler.get_latest_imu()
                while True:
                    next_imu = await self.stream_handler.next_imu(timeout=0)
                    if next_imu is None:
                        break
                    latest_imu = next_imu

                latest_event = self.stream_handler.get_latest_event()
                while True:
                    next_event = await self.stream_handler.next_event(timeout=0)
                    if next_event is None:
                        break
                    latest_event = next_event

                while True:
                    next_audio = await self.stream_handler.next_audio(timeout=0)
                    if next_audio is None:
                        break
                    self.recording_manager.write_audio_sample(next_audio)

                # Drain eyes frames with early skip downsampling
                # At 200Hz source, skip most frames before queuing for recording
                eyes_drained = 0
                eyes_written = 0
                eyes_skip_factor = self.config.eyes_recording_skip_factor()
                while True:
                    next_eyes = await self.stream_handler.next_eyes(timeout=0)
                    if next_eyes is None:
                        break
                    eyes_drained += 1
                    self._eyes_frame_counter += 1
                    # Only queue for recording when counter aligns with skip factor
                    if is_recording and (self._eyes_frame_counter % eyes_skip_factor == 0):
                        eyes_written += 1
                        self.recording_manager.write_eyes_frame(
                            next_eyes.image,
                            timestamp_unix=next_eyes.timestamp_unix_seconds,
                            timestamp_ns=next_eyes.timestamp_unix_ns,
                        )

                # Write gaze sample at full rate when recording (for temporal accuracy)
                if is_recording:
                    self.recording_manager.write_gaze_sample(latest_gaze)

                # === SKIP FAST PATH ===
                # If skipping both display AND recording, skip expensive frame processing
                if skip_display and (skip_recording or not is_recording):
                    await asyncio.sleep(0)  # Yield to event loop
                    continue

                # === FRAME PROCESSING (only for frames we'll use) ===
                display_frame = None
                recording_frame = None

                # OpenCV mode: can use async processing in background thread
                # GUI mode: run synchronously to avoid Tkinter threading conflicts
                if self.display_enabled:
                    processed_frame = await self.frame_processor.process_frame_async(raw_frame)
                else:
                    processed_frame = self.frame_processor.process_frame(raw_frame)
                    await asyncio.sleep(0)  # Yield to event loop

                # === DISPLAY FRAME PREPARATION ===
                if not skip_display:
                    # Scale early for display (reduces overlay CPU)
                    preview_frame = self.frame_processor.scale_for_preview(processed_frame)

                    # Check if preview_frame shares memory with processed_frame
                    is_preview_shared = (preview_frame is processed_frame)

                    # If they share memory and we are recording, copy to avoid
                    # burning display overlays into the recording
                    if is_preview_shared and is_recording and not skip_recording:
                        preview_frame = preview_frame.copy()

                    display_frame = self.frame_processor.add_display_overlays(
                        preview_frame,
                        latest_gaze,
                    )

                # === RECORDING FRAME PREPARATION ===
                if is_recording and not skip_recording:
                    if self.config.enable_recording_overlay:
                        frame_number = self.recording_manager.recorded_frame_count + 1
                        recording_frame = self.frame_processor.add_minimal_recording_overlay(
                            processed_frame,
                            frame_number,
                            latest_gaze,
                            include_gaze=self.config.include_gaze_in_recording
                        )
                    else:
                        recording_frame = processed_frame

                # Store display frame if generated
                if display_frame is not None:
                    self._latest_display_frame = display_frame
                    self._display_fps_tracker.add_frame()

                # Write recording frame (already filtered, no skip check needed)
                if recording_frame is not None:
                    self.recording_manager.write_frame(recording_frame)

                if self.display_enabled and display_frame is not None:
                    self.frame_processor.display_frame(display_frame)

                    command = self.frame_processor.check_keyboard()
                    if command == 'quit':
                        self.running = False
                        if self.stream_handler.running:
                            await self.stream_handler.stop_streaming()
                        break
                    elif command == 'record':
                        await self.recording_manager.toggle_recording()
                    elif command == 'pause':  # Phase 1.4: Pause/resume toggle
                        if self.is_paused:
                            await self.resume()
                        else:
                            await self.pause()

                await asyncio.sleep(0)

            except Exception as e:
                logger.error("Frame processing error: %s", e)
                if not self.running:
                    break

    async def cleanup(self):

        self.running = False

        await self.stream_handler.stop_streaming()

        await self.recording_manager.cleanup()

        await self.device_manager.cleanup()

        # Close OpenCV windows
        self.frame_processor.destroy_windows()
