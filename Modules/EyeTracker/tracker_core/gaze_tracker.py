#!/usr/bin/env python3
"""
Main Gaze Tracker Class
Orchestrates all components for gaze tracking functionality.
"""

import asyncio
import time
import logging
from typing import Optional
from .config.tracker_config import TrackerConfig as Config
from .device_manager import DeviceManager
from .stream_handler import StreamHandler, FramePacket
from .frame_processor import FrameProcessor
from .recording import RecordingManager, FrameTimingMetadata

logger = logging.getLogger(__name__)


class GazeTracker:
    """Main gaze tracker orchestration class"""

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

        # Stats
        self.frame_count = 0
        self.start_time = None
        self.no_frame_timeouts = 0  # When no frames available from stream
        self.dropped_frames = 0
        self.last_camera_frame_count = 0

        # Latest display frame for GUI access
        self._latest_display_frame = None

        # Components
        self.device_manager = device_manager or DeviceManager()
        self.stream_handler = stream_handler or StreamHandler()
        self.frame_processor = frame_processor or FrameProcessor(config)
        self.recording_manager = recording_manager or RecordingManager(config)

    async def connect(self) -> bool:
        """Connect to eye tracker device"""
        return await self.device_manager.connect()

    async def run(self):
        """Main processing loop"""
        if not self.device_manager.is_connected:
            logger.error("No device connected")
            return

        self.running = True
        self.start_time = time.time()

        # Create OpenCV window only if display is enabled (standalone mode)
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

            # Get RTSP URLs
            stream_urls = self.device_manager.get_stream_urls()

            # Start streaming
            stream_tasks = await self.stream_handler.start_streaming(
                stream_urls["video"],
                stream_urls["gaze"],
                imu_url=stream_urls.get("imu"),
                events_url=stream_urls.get("events"),
            ) or []

            # Create frame processing task
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
        """Process frames at target FPS without blocking the event loop."""
        frame_interval = 1.0 / self.config.fps
        fps_int = max(int(self.config.fps), 1)
        next_frame_deadline = time.perf_counter()
        no_frame_count = 0

        while self.running:
            try:
                wait_timeout = max(0.0, next_frame_deadline - time.perf_counter())
                frame_packet: Optional[FramePacket] = await self.stream_handler.next_frame(timeout=wait_timeout)

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
                # Async in standalone mode for better performance
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
                    self.recording_manager.write_imu_sample(next_imu)

                latest_event = self.stream_handler.get_latest_event()
                while True:
                    next_event = await self.stream_handler.next_event(timeout=0)
                    if next_event is None:
                        break
                    latest_event = next_event
                    self.recording_manager.write_event_sample(next_event)

                # Use sync processing in GUI mode to avoid cv2/Tkinter threading conflicts
                # Async in standalone mode for better performance
                if self.display_enabled:
                    display_frame = await self.frame_processor.add_overlays_async(
                        processed_frame,
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
                else:
                    # GUI mode: run synchronously in main thread to avoid Tkinter conflicts
                    display_frame = self.frame_processor.add_overlays(
                        processed_frame,
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
                    await asyncio.sleep(0)  # Yield to event loop

                # Store latest display frame for GUI access
                self._latest_display_frame = display_frame

                if self.recording_manager.is_recording:
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
                    self.recording_manager.write_frame(display_frame, metadata=frame_metadata)
                    self.recording_manager.write_gaze_sample(latest_gaze)

                # Only display frames and check keyboard if display is enabled (standalone mode)
                if self.display_enabled:
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

                await asyncio.sleep(0)

                now = time.perf_counter()
                next_frame_deadline = max(next_frame_deadline + frame_interval, now)

            except Exception as e:
                logger.error(f"Frame processing error: {e}")
                if not self.running:
                    break

    async def cleanup(self):
        """Clean up all resources"""
        logger.info("Cleaning up...")

        # Stop processing
        self.running = False

        # Stop streaming
        await self.stream_handler.stop_streaming()

        # Stop recording
        await self.recording_manager.cleanup()

        # Close device
        await self.device_manager.cleanup()

        # Close OpenCV windows
        self.frame_processor.destroy_windows()

        logger.info("Cleanup complete")
