#!/usr/bin/env python3
"""
Main Gaze Tracker Class
Orchestrates all components for gaze tracking functionality.
"""

import asyncio
import time
import logging
from typing import Optional
from config import Config
from device_manager import DeviceManager
from stream_handler import StreamHandler, FramePacket
from frame_processor import FrameProcessor
from recording_manager import RecordingManager, FrameTimingMetadata

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
    ):
        self.config = config
        self.running = False

        # Stats
        self.frame_count = 0
        self.start_time = None
        self.no_frame_timeouts = 0  # When no frames available from stream
        self.dropped_frames = 0
        self.last_camera_frame_count = 0

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

        # Create OpenCV window
        self.frame_processor.create_window()
        logger.info("Starting gaze tracker - Press Q to quit, R to toggle recording")

        try:
            # Get RTSP URLs
            video_url, gaze_url = self.device_manager.get_rtsp_urls()

            # Start streaming
            stream_tasks = await self.stream_handler.start_streaming(video_url, gaze_url) or []

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

                processed_frame = await self.frame_processor.process_frame_async(raw_frame)

                latest_gaze = self.stream_handler.get_latest_gaze()
                while True:
                    next_gaze = await self.stream_handler.next_gaze(timeout=0)
                    if next_gaze is None:
                        break
                    latest_gaze = next_gaze

                display_frame = await self.frame_processor.add_overlays_async(
                    processed_frame,
                    self.frame_count,
                    current_camera_frames,
                    self.start_time,
                    self.recording_manager.is_recording,
                    latest_gaze,
                    self.stream_handler.get_camera_fps(),
                    self.dropped_frames,
                    self.recording_manager.duplicated_frames,  # Use recording manager's duplicated frames
                    self.config.fps,
                )

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
