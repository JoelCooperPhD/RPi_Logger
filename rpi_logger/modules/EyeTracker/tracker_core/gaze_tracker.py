
import asyncio
import time
import logging
from typing import Optional
from rpi_logger.core.logging_utils import get_module_logger
from .config.tracker_config import TrackerConfig as Config
from .device_manager import DeviceManager
from .stream_handler import StreamHandler, FramePacket
from .frame_processor import FrameProcessor
from .recording import RecordingManager, FrameTimingMetadata

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

        self.frame_count = 0
        self.start_time = None
        self.no_frame_timeouts = 0  # When no frames available from stream
        self.dropped_frames = 0
        self.last_camera_frame_count = 0

        self._latest_display_frame = None

        self.device_manager = device_manager or DeviceManager()
        self.device_manager.audio_stream_param = config.audio_stream_param
        self.stream_handler = stream_handler or StreamHandler()
        self.frame_processor = frame_processor or FrameProcessor(config)
        self.recording_manager = recording_manager or RecordingManager(
            config,
            device_manager=self.device_manager,
        )
        self.stream_handler.set_imu_listener(self.recording_manager.write_imu_sample)
        self.stream_handler.set_event_listener(self.recording_manager.write_event_sample)


    async def connect(self) -> bool:
        return await self.device_manager.connect()

    # Phase 1.4: Pause/resume methods
    async def pause(self):
        """
        Pause frame processing to save CPU while keeping streams alive.

        This is useful when the Eye Tracker module is visible in the UI
        but not actively being monitored. Streams stay connected so
        resume is fast.
        """
        if self._paused:
            logger.debug("Already paused")
            return

        self._paused = True
        logger.info("Eye tracker paused (CPU saving mode - streams remain connected)")

    async def resume(self):
        """
        Resume normal frame processing after pause.
        """
        if not self._paused:
            logger.debug("Already running")
            return

        self._paused = False
        logger.info("Eye tracker resumed")

    @property
    def is_paused(self) -> bool:
        """Check if currently paused"""
        return self._paused

    async def run(self):
        if not self.device_manager.is_connected:
            logger.error("No device connected")
            return

        self.running = True
        self.start_time = time.time()

        if self.display_enabled:
            self.frame_processor.create_window()
            logger.info("Starting gaze tracker - Press Q to quit, R to toggle recording")
        else:
            logger.info("Starting gaze tracker (GUI display mode)")

        try:
            experiment_dir = None
            if getattr(self.recording_manager, "current_experiment_dir", None) is None:
                try:
                    experiment_dir = self.recording_manager.start_experiment()
                except Exception as exc:
                    logger.error("Failed to initialize experiment directory: %s", exc)
                else:
                    logger.info("Experiment directory ready: %s", experiment_dir)

            stream_urls = self.device_manager.get_stream_urls()

            stream_tasks = await self.stream_handler.start_streaming(
                stream_urls["video"],
                stream_urls["gaze"],
                imu_url=stream_urls.get("imu"),
                events_url=stream_urls.get("events"),
                audio_url=stream_urls.get("audio"),
            ) or []

            frame_task = asyncio.create_task(self._process_frames(), name="frame-processor")

            try:
                await frame_task
            finally:
                await self.stream_handler.stop_streaming()
                if stream_tasks:
                    await asyncio.gather(*stream_tasks, return_exceptions=True)

        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        except Exception as e:
            logger.error(f"Runtime error: {e}")
        finally:
            await self.cleanup()

    async def _process_frames(self):
        frame_interval = 1.0 / self.config.fps
        fps_int = max(int(self.config.fps), 1)
        # Give a reasonable timeout for the first frame (10 seconds)
        next_frame_deadline = time.perf_counter() + 10.0
        no_frame_count = 0

        while self.running:
            try:
                # Phase 1.4: Check pause state early in loop
                if self._paused:
                    # Idle sleep with minimal CPU usage
                    # Streams stay alive in background
                    await asyncio.sleep(0.1)

                    # Update deadline to avoid burst processing on resume
                    next_frame_deadline = time.perf_counter() + frame_interval
                    continue

                wait_timeout = max(0.0, next_frame_deadline - time.perf_counter())
                # Phase 1.1: Use event-driven wait instead of polling
                try:
                    frame_packet: Optional[FramePacket] = await self.stream_handler.wait_for_frame(timeout=wait_timeout)
                except asyncio.TimeoutError:
                    frame_packet = None

                if frame_packet is None:
                    self.no_frame_timeouts += 1
                    no_frame_count += 1

                    if not self.stream_handler.running and self.stream_handler.camera_frames == self.last_camera_frame_count:
                        logger.info("Stream handler stopped; exiting frame loop")
                        self.running = False
                        break

                    if no_frame_count in (fps_int, fps_int * 5):
                        logger.warning("No frames received for %d second(s)", no_frame_count // fps_int)

                    next_frame_deadline = time.perf_counter() + frame_interval
                    continue

                self.frame_count += 1
                no_frame_count = 0

                raw_frame = frame_packet.image
                current_camera_frames = frame_packet.camera_frame_index
                new_camera_frames = current_camera_frames - self.last_camera_frame_count
                if new_camera_frames > 1:
                    self.dropped_frames += new_camera_frames - 1
                self.last_camera_frame_count = current_camera_frames

                # Use sync processing in GUI mode to avoid cv2/Tkinter threading conflicts
                if self.display_enabled:
                    processed_frame = await self.frame_processor.process_frame_async(raw_frame)
                else:
                    # GUI mode: run synchronously in main thread to avoid Tkinter conflicts
                    processed_frame = self.frame_processor.process_frame(raw_frame)
                    await asyncio.sleep(0)  # Yield to event loop

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

                # Phase 1.2 & 1.3: Separate display and recording overlays with early scaling
                display_frame = None
                recording_frame = None

                # Always create display frame (for GUI or OpenCV display)
                # Phase 1.3: Scale early for display (reduces overlay CPU)
                preview_frame = self.frame_processor.scale_for_preview(processed_frame)

                # Use synchronous version to avoid event loop issues
                display_frame = self.frame_processor.add_display_overlays(
                    preview_frame,
                    self.frame_count,
                    current_camera_frames,
                    self.start_time,
                    self.recording_manager.is_recording,
                    latest_gaze,
                    self.stream_handler.get_camera_fps(),
                    self.dropped_frames,
                    self.recording_manager.duplicated_frames,
                    self.config.fps,
                    experiment_label=self.recording_manager.current_experiment_label,
                )

                if self.recording_manager.is_recording:
                    # Minimal overlay for recording: frame number + optional gaze circle
                    if self.config.enable_recording_overlay:
                        frame_number = self.recording_manager.recorded_frame_count + 1  # +1 because we increment AFTER writing
                        recording_frame = self.frame_processor.add_minimal_recording_overlay(
                            processed_frame.copy(),
                            frame_number,
                            latest_gaze,
                            include_gaze=self.config.include_gaze_in_recording
                        )
                    else:
                        # No overlay, use raw processed frame
                        recording_frame = processed_frame.copy()

                # Store display frame if generated
                if display_frame is not None:
                    self._latest_display_frame = display_frame

                if self.recording_manager.is_recording and recording_frame is not None:
                    frame_metadata = FrameTimingMetadata(
                        capture_monotonic=frame_packet.received_monotonic,
                        capture_unix=frame_packet.timestamp_unix_seconds,
                        camera_frame_index=frame_packet.camera_frame_index,
                        display_frame_index=self.frame_count,
                        dropped_frames_total=self.dropped_frames,
                        duplicates_total=self.recording_manager.duplicated_frames,
                        available_camera_fps=self.stream_handler.get_camera_fps(),
                        requested_fps=self.config.fps,
                        gaze_timestamp=getattr(latest_gaze, "timestamp_unix_seconds", None),
                    )
                    self.recording_manager.write_frame(recording_frame, metadata=frame_metadata)
                    self.recording_manager.write_gaze_sample(latest_gaze)

                if self.display_enabled and display_frame is not None:
                    self.frame_processor.display_frame(display_frame)

                    command = self.frame_processor.check_keyboard()
                    if command == 'quit':
                        logger.info("Quit requested")
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

                now = time.perf_counter()
                next_frame_deadline = max(next_frame_deadline + frame_interval, now)

            except Exception as e:
                logger.error(f"Frame processing error: {e}")
                if not self.running:
                    break

    async def cleanup(self):
        logger.info("Cleaning up...")

        self.running = False

        await self.stream_handler.stop_streaming()

        await self.recording_manager.cleanup()

        await self.device_manager.cleanup()

        # Close OpenCV windows
        self.frame_processor.destroy_windows()

        logger.info("Cleanup complete")
