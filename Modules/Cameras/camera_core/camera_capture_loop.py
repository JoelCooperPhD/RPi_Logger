#!/usr/bin/env python3
"""
Tight async loop for frame capture at camera's native FPS.
Captures frames, tracks timing, and detects drops using hardware timestamps.
"""

import asyncio
import logging
import time
from typing import Optional

import numpy as np
from picamera2 import Picamera2

from .camera_utils import RollingFPS
from .constants import (
    FRAME_DURATION_MIN_US,
    FRAME_DURATION_MAX_US,
    CAPTURE_SLEEP_INTERVAL,
    FRAME_LOG_COUNT,
)

logger = logging.getLogger("CameraCapture")


class CameraCaptureLoop:
    """
    Super tight camera capture loop.

    Runs in dedicated thread, captures frames at camera's native FPS (~30),
    stores latest frame atomically for other loops to consume.
    """

    def __init__(self, camera_id: int, picam2: Picamera2):
        self.camera_id = camera_id
        self.picam2 = picam2
        self.logger = logging.getLogger(f"CameraCapture{camera_id}")

        self.fps_tracker = RollingFPS(window_seconds=5.0)
        self.captured_frames = 0
        self.camera_hardware_fps: float = 0.0

        self.hardware_frame_number = 0
        self.last_sensor_timestamp_ns: Optional[int] = None
        self.expected_frame_interval_ns: Optional[int] = None

        self.latest_frame: Optional[np.ndarray] = None
        self.latest_metadata: Optional[dict] = None
        self.latest_capture_time: Optional[float] = None
        self.latest_capture_monotonic: Optional[float] = None
        self.latest_sensor_timestamp_ns: Optional[int] = None
        self.latest_hardware_fps: float = 0.0
        self._frame_lock = asyncio.Lock()

        # Event-driven coordination (eliminates polling)
        # This event is set when a new frame is captured
        # Processor waits on this event instead of polling
        self._frame_ready_event = asyncio.Event()

        self._running = False
        self._paused = False  # Pause state for CPU saving
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the capture loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._capture_loop())
        self.logger.info("Camera capture loop started")

    async def stop(self):
        """Stop the capture loop."""
        if not self._running:
            return
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.logger.info("Camera capture loop stopped")

    async def pause(self):
        """
        Pause the capture loop (idles but keeps task alive).
        Saves CPU by not polling hardware.
        """
        if not self._paused:
            self._paused = True
            self.logger.info("Camera %d capture loop paused (CPU saving mode)", self.camera_id)

    async def resume(self):
        """Resume the capture loop."""
        if self._paused:
            self._paused = False
            self.logger.info("Camera %d capture loop resumed", self.camera_id)

    async def _capture_loop(self):
        """
        Capture loop using lores stream for preview.
        Uses dual-stream config so preview doesn't interfere with H.264 recording.
        """
        self.logger.info("Entering tight capture loop (using lores stream)")
        self.logger.info("Camera %d capture loop started, _running=%s", self.camera_id, self._running)

        while self._running:
            try:
                # Check pause state - idle if paused (no CPU usage)
                if self._paused:
                    await asyncio.sleep(0.1)  # Idle sleep, minimal CPU
                    continue

                loop = asyncio.get_event_loop()
                # Add timeout to prevent indefinite blocking if camera hangs
                # 5-second timeout is reasonable for camera hardware recovery
                try:
                    request = await asyncio.wait_for(
                        loop.run_in_executor(None, self.picam2.capture_request),
                        timeout=5.0
                    )
                except asyncio.TimeoutError:
                    self.logger.error("Camera capture timed out after 5 seconds (hardware may be hung)")
                    await asyncio.sleep(1.0)  # Brief pause before retry
                    continue

                raw_frame = request.make_array("lores")
                metadata = request.get_metadata()
                capture_time = time.time()
                capture_monotonic = time.perf_counter()
                request.release()

                hardware_fps = 0.0
                if 'FrameDuration' in metadata:
                    frame_duration_us = metadata['FrameDuration']
                    # Validate frame duration to prevent overflow and detect hardware issues
                    if FRAME_DURATION_MIN_US <= frame_duration_us <= FRAME_DURATION_MAX_US:
                        hardware_fps = 1000000.0 / frame_duration_us
                        self.camera_hardware_fps = hardware_fps
                        # Safe conversion: max value is FRAME_DURATION_MAX_US * 1000 = 10^10 (fits in int64)
                        self.expected_frame_interval_ns = int(frame_duration_us * 1000)
                        if self.captured_frames < FRAME_LOG_COUNT:
                            self.logger.info(
                                "Frame %d: FrameDuration=%d us, expected_interval=%d ns (%.2f ms)",
                                self.captured_frames, frame_duration_us, self.expected_frame_interval_ns,
                                self.expected_frame_interval_ns / 1_000_000
                            )
                    elif frame_duration_us > 0:
                        self.logger.warning(
                            "Frame %d: Invalid FrameDuration=%d us (outside range %d-%d)",
                            self.captured_frames, frame_duration_us,
                            FRAME_DURATION_MIN_US, FRAME_DURATION_MAX_US
                        )

                sensor_timestamp_ns = metadata.get('SensorTimestamp')

                # Calculate hardware frame number using timestamp deltas for accurate drop detection
                dropped_since_last = 0
                if sensor_timestamp_ns is not None:
                    # Only perform drop detection if both prerequisites are met:
                    # 1. We have a previous timestamp to compare against
                    # 2. We know the expected frame interval
                    if self.last_sensor_timestamp_ns is not None and self.expected_frame_interval_ns is not None:
                        delta_ns = sensor_timestamp_ns - self.last_sensor_timestamp_ns
                        intervals_passed = round(delta_ns / self.expected_frame_interval_ns)
                        dropped_since_last = max(0, intervals_passed - 1)

                        if dropped_since_last > 0:
                            self.logger.warning(
                                "Frame %d: delta=%d ns (%.2f ms), expected=%d ns, intervals=%d, dropped=%d",
                                self.captured_frames, delta_ns, delta_ns / 1_000_000,
                                self.expected_frame_interval_ns, intervals_passed, dropped_since_last
                            )

                        self.hardware_frame_number += intervals_passed
                    else:
                        # First frame with valid timestamp - initialize tracking
                        # Don't increment hardware_frame_number yet, wait for second frame
                        if self.last_sensor_timestamp_ns is None:
                            self.hardware_frame_number = 0
                            if self.captured_frames < 3:
                                self.logger.info(
                                    "Frame %d: First frame with timestamp, hw_frame_num=0, expected_interval=%s",
                                    self.captured_frames, self.expected_frame_interval_ns
                                )

                    # Always update last_sensor_timestamp_ns when we have valid data
                    self.last_sensor_timestamp_ns = sensor_timestamp_ns
                else:
                    # Fallback: use software counter if no hardware timestamp available
                    self.hardware_frame_number = self.captured_frames
                    if self.captured_frames < 3:
                        self.logger.warning("Frame %d: No SensorTimestamp in metadata!", self.captured_frames)

                self.captured_frames += 1
                self.fps_tracker.add_frame(capture_time)

                metadata['CaptureFrameIndex'] = self.captured_frames - 1
                metadata['HardwareFrameNumber'] = self.hardware_frame_number
                metadata['DroppedSinceLast'] = dropped_since_last

                if self.captured_frames <= 3:
                    self.logger.info(
                        "Frame %d: Metadata set - CaptureFrameIndex=%d, HardwareFrameNumber=%d, DroppedSinceLast=%d",
                        self.captured_frames - 1, metadata['CaptureFrameIndex'],
                        metadata['HardwareFrameNumber'], metadata['DroppedSinceLast']
                    )

                async with self._frame_lock:
                    self.latest_frame = raw_frame
                    self.latest_metadata = metadata
                    self.latest_capture_time = capture_time
                    self.latest_capture_monotonic = capture_monotonic
                    self.latest_sensor_timestamp_ns = sensor_timestamp_ns
                    self.latest_hardware_fps = hardware_fps

                # Signal that a new frame is ready (event-driven coordination)
                # This wakes up any task waiting in wait_for_frame()
                if self.captured_frames <= 3:
                    self.logger.info("Frame %d: Setting frame_ready_event", self.captured_frames - 1)
                self._frame_ready_event.set()

            except asyncio.CancelledError:
                break
            except RuntimeError as exc:
                if "cannot schedule new futures" in str(exc):
                    self.logger.debug("Event loop shutting down, exiting capture loop")
                    break
                elif self._running:
                    self.logger.error("Capture error: %s", exc, exc_info=True)
                    await asyncio.sleep(0.1)
            except Exception as exc:
                if self._running:
                    self.logger.error("Capture error: %s", exc, exc_info=True)
                    await asyncio.sleep(0.1)

        self.logger.info("Exited tight capture loop")

    async def get_latest_frame(self):
        """Get latest frame with metadata and timing info (polling mode - deprecated)."""
        async with self._frame_lock:
            return (self.latest_frame, self.latest_metadata, self.latest_capture_time,
                    self.latest_capture_monotonic, self.latest_sensor_timestamp_ns, self.latest_hardware_fps)

    async def wait_for_frame(self, timeout: float = 10.0):
        """
        Wait for a new frame (event-driven, zero-overhead).

        This method blocks until a new frame is captured, eliminating the need
        for polling loops. This is the preferred method for frame consumption.

        Args:
            timeout: Maximum time to wait for a frame (seconds). Default 10s.

        Returns:
            Tuple: (frame, metadata, capture_time, capture_monotonic, sensor_timestamp_ns, hardware_fps)

        Raises:
            asyncio.TimeoutError: If no frame received within timeout period

        Performance:
        - No CPU waste from polling
        - Immediate response to new frames (no polling delay)
        - Typical overhead: < 1μs per frame vs ~1ms polling delay
        """
        # Wait for the event with timeout (blocks until new frame captured)
        try:
            await asyncio.wait_for(self._frame_ready_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            self.logger.error("Timeout waiting for frame (no frames captured in %s seconds)", timeout)
            raise

        # Clear event for next frame
        # Must be done AFTER wait returns and BEFORE getting frame data
        # This ensures we don't miss events between clearing and next wait
        self._frame_ready_event.clear()

        # Get frame data atomically
        async with self._frame_lock:
            return (self.latest_frame, self.latest_metadata, self.latest_capture_time,
                    self.latest_capture_monotonic, self.latest_sensor_timestamp_ns, self.latest_hardware_fps)

    def get_fps(self) -> float:
        return self.fps_tracker.get_fps()

    def get_hardware_fps(self) -> float:
        return self.camera_hardware_fps

    def get_frame_count(self) -> int:
        return self.captured_frames
