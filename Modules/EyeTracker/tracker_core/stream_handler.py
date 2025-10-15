#!/usr/bin/env python3
"""
Stream Handler for Gaze Tracker
Handles video and gaze data streaming from eye tracker device.
"""

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass
from typing import Optional, Any, List

import numpy as np
from pupil_labs.realtime_api import (
    receive_video_frames,
    receive_gaze_data,
    receive_imu_data,
    receive_eye_events_data,
)
from .rolling_fps import RollingFPS

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class FramePacket:
    """Container for a scene frame and associated timing metadata."""

    image: np.ndarray
    received_monotonic: float
    timestamp_unix_seconds: Optional[float]
    camera_frame_index: int


class StreamHandler:
    """Handles streaming of video and gaze data"""

    def __init__(self):
        self.running = False
        self.last_frame: Optional[np.ndarray] = None
        self._last_frame_packet: Optional[FramePacket] = None
        self.last_gaze: Optional[Any] = None
        self.last_imu: Optional[Any] = None
        self.last_event: Optional[Any] = None
        self.camera_frames = 0
        self.tasks: List[asyncio.Task] = []
        self._video_task_active = False
        self._gaze_task_active = False
        self._imu_task_active = False
        self._event_task_active = False
        self.camera_fps_tracker = RollingFPS(window_seconds=5.0)
        self._frame_queue: asyncio.Queue[FramePacket] = asyncio.Queue(maxsize=6)
        self._gaze_queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=32)
        self._imu_queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=64)
        self._event_queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=64)

    def _update_running_flag(self) -> None:
        """Update the aggregate running flag based on individual streams."""
        self.running = any(
            (
                self._video_task_active,
                self._gaze_task_active,
                self._imu_task_active,
                self._event_task_active,
            )
        )

    async def start_streaming(
        self,
        video_url: str,
        gaze_url: str,
        *,
        imu_url: Optional[str] = None,
        events_url: Optional[str] = None,
    ):
        """Start video and gaze streaming tasks"""
        if self.running:
            return

        self._video_task_active = True
        self._gaze_task_active = True
        self._imu_task_active = bool(imu_url)
        self._event_task_active = bool(events_url)
        self._update_running_flag()
        logger.info(f"Video URL: {video_url}")
        logger.info(f"Gaze URL: {gaze_url}")
        if imu_url:
            logger.info(f"IMU URL: {imu_url}")
        if events_url:
            logger.info(f"Events URL: {events_url}")

        # Create streaming tasks
        self.tasks = [
            asyncio.create_task(self._stream_video_frames(video_url), name="video-stream"),
            asyncio.create_task(self._stream_gaze_data(gaze_url), name="gaze-stream"),
        ]

        if imu_url:
            self.tasks.append(
                asyncio.create_task(self._stream_imu_data(imu_url), name="imu-stream")
            )
        if events_url:
            self.tasks.append(
                asyncio.create_task(self._stream_eye_events(events_url), name="events-stream")
            )

        return self.tasks

    async def stop_streaming(self):
        """Stop streaming tasks"""
        self._video_task_active = False
        self._gaze_task_active = False
        self._imu_task_active = False
        self._event_task_active = False
        self._update_running_flag()

        # Cancel all tasks
        for task in self.tasks:
            if not task.done():
                task.cancel()

        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks = []
        self._drain_queues()

    async def _stream_video_frames(self, video_url: str):
        """Continuously stream video frames using correct API"""
        logger.info("Starting video stream...")

        frame_count = 0
        try:
            async for frame in receive_video_frames(video_url):
                if not self.running:
                    break

                frame_count += 1
                if frame_count == 1:
                    logger.info("First video frame received!")
                    logger.info(f"Video frame type: {type(frame)}")
                    logger.info(f"Video frame attributes: {[attr for attr in dir(frame) if not attr.startswith('_')]}")

                if frame:
                    try:
                        # Use the API-provided BGR buffer to preserve color information
                        pixel_data = frame.bgr_buffer()

                        if pixel_data is not None:
                            frame_array = np.ascontiguousarray(pixel_data)
                            self.camera_frames += 1
                            self.last_frame = frame_array
                            packet = FramePacket(
                                image=frame_array,
                                received_monotonic=time.perf_counter(),
                                timestamp_unix_seconds=getattr(frame, "timestamp_unix_seconds", None),
                                camera_frame_index=self.camera_frames,
                            )
                            self._last_frame_packet = packet
                            self.camera_fps_tracker.add_frame()
                            self._enqueue_latest(self._frame_queue, packet)

                            if self.camera_frames == 1:
                                logger.info(f"Frame shape: {pixel_data.shape}")
                                logger.info(f"Frame dtype: {pixel_data.dtype}")

                                # Check if it's grayscale or color
                                if len(pixel_data.shape) == 3:
                                    logger.info(f"Color channels: {pixel_data.shape[2]}")
                                    # Sample pixel to see values
                                    if pixel_data.shape[0] > 100 and pixel_data.shape[1] > 100:
                                        sample = pixel_data[100, 100]
                                        logger.info(f"Sample pixel: {sample}")
                                else:
                                    logger.info("Grayscale frame detected")

                            elif self.camera_frames % 30 == 1:  # Log every 30 frames
                                logger.info(f"Video frames received: {self.camera_frames}")
                        else:
                            if frame_count <= 5:
                                logger.warning(f"Frame {frame_count}: to_ndarray() returned None")

                    except Exception as e:
                        if frame_count <= 5:
                            logger.error(f"Frame {frame_count}: Error getting pixel data: {e}")

        except asyncio.CancelledError:
            logger.debug("Video stream task cancelled")
            raise
        except Exception as e:
            if self.running:
                logger.error(f"Video stream error: {e}")
        finally:
            self._video_task_active = False
            self._update_running_flag()

    async def _stream_gaze_data(self, gaze_url: str):
        """Continuously stream gaze data using correct API"""
        logger.info("Starting gaze stream...")

        gaze_count = 0
        try:
            async for gaze in receive_gaze_data(gaze_url):
                if not self.running:
                    break

                gaze_count += 1
                if gaze_count == 1:
                    logger.info("First gaze data received!")
                    logger.info(f"Gaze data type: {type(gaze)}")
                    logger.info(f"Gaze data attributes: {[attr for attr in dir(gaze) if not attr.startswith('_')]}")

                self.last_gaze = gaze
                self._enqueue_latest(self._gaze_queue, gaze)

                if gaze_count % 100 == 1:  # Log every 100 gaze samples
                    logger.info(f"Gaze samples received: {gaze_count}")

        except asyncio.CancelledError:
            logger.debug("Gaze stream task cancelled")
            raise
        except Exception as e:
            if self.running:
                logger.error(f"Gaze stream error: {e}")
        finally:
            self._gaze_task_active = False
            self._update_running_flag()

    async def _stream_imu_data(self, imu_url: str):
        """Continuously stream IMU samples."""
        logger.info("Starting IMU stream...")

        imu_count = 0
        try:
            async for imu in receive_imu_data(imu_url):
                if not self.running:
                    break

                imu_count += 1
                if imu_count == 1:
                    logger.info("First IMU sample received!")
                    logger.info(
                        "IMU sample attributes: %s",
                        [attr for attr in dir(imu) if not attr.startswith("_")],
                    )

                self.last_imu = imu
                self._enqueue_latest(self._imu_queue, imu)

                if imu_count % 100 == 1:
                    logger.info("IMU samples received: %d", imu_count)

        except asyncio.CancelledError:
            logger.debug("IMU stream task cancelled")
            raise
        except Exception as exc:
            if self.running:
                logger.error("IMU stream error: %s", exc)
        finally:
            self._imu_task_active = False
            self._update_running_flag()

    async def _stream_eye_events(self, events_url: str):
        """Continuously stream eye event samples."""
        logger.info("Starting eye events stream...")

        event_count = 0
        try:
            async for event in receive_eye_events_data(events_url):
                if not self.running:
                    break

                event_count += 1
                if event_count == 1:
                    logger.info("First eye event received!")
                    logger.info(
                        "Eye event attributes: %s",
                        [attr for attr in dir(event) if not attr.startswith("_")],
                    )

                self.last_event = event
                self._enqueue_latest(self._event_queue, event)

                if event_count % 50 == 1:
                    logger.info("Eye events received: %d", event_count)

        except asyncio.CancelledError:
            logger.debug("Eye events stream task cancelled")
            raise
        except Exception as exc:
            if self.running:
                logger.error("Eye events stream error: %s", exc)
        finally:
            self._event_task_active = False
            self._update_running_flag()

    def get_latest_frame(self) -> Optional[np.ndarray]:
        """Get the latest video frame"""
        return self.last_frame

    def get_latest_frame_packet(self) -> Optional[FramePacket]:
        """Get the latest frame packet with timing metadata."""
        return self._last_frame_packet

    def get_latest_gaze(self) -> Optional[Any]:
        """Get the latest gaze data"""
        return self.last_gaze

    def get_latest_imu(self) -> Optional[Any]:
        """Get the latest IMU sample."""
        return self.last_imu

    def get_latest_event(self) -> Optional[Any]:
        """Get the latest eye event sample."""
        return self.last_event

    def get_camera_fps(self) -> float:
        """Get rolling camera FPS over the last 5 seconds"""
        return self.camera_fps_tracker.get_fps()

    async def next_frame(self, timeout: Optional[float] = None) -> Optional[FramePacket]:
        """Return the next queued frame packet, or ``None`` on timeout."""
        return await self._dequeue_with_timeout(self._frame_queue, timeout)

    async def next_gaze(self, timeout: Optional[float] = None) -> Optional[Any]:
        """Return the next queued gaze sample, or ``None`` on timeout."""
        return await self._dequeue_with_timeout(self._gaze_queue, timeout)

    async def next_imu(self, timeout: Optional[float] = None) -> Optional[Any]:
        """Return the next queued IMU sample, or ``None`` on timeout."""
        return await self._dequeue_with_timeout(self._imu_queue, timeout)

    async def next_event(self, timeout: Optional[float] = None) -> Optional[Any]:
        """Return the next queued eye event, or ``None`` on timeout."""
        return await self._dequeue_with_timeout(self._event_queue, timeout)

    @staticmethod
    def _enqueue_latest(queue: asyncio.Queue, item: Any) -> None:
        """Drop the oldest entry when the queue is full, then enqueue."""
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty):
                _ = queue.get_nowait()
            queue.put_nowait(item)

    @staticmethod
    async def _dequeue_with_timeout(queue: asyncio.Queue, timeout: Optional[float]) -> Optional[Any]:
        if queue.empty() and timeout == 0:
            return None
        try:
            if timeout is None:
                return await queue.get()
            return await asyncio.wait_for(queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    def _drain_queues(self) -> None:
        for queue in (self._frame_queue, self._gaze_queue, self._imu_queue, self._event_queue):
            while True:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
