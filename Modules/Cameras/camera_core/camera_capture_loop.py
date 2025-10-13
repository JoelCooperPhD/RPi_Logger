#!/usr/bin/env python3
"""
CAMERA CAPTURE LOOP - Super tight async loop for frame capture.

This loop does ONLY:
1. Wait for frame from camera (blocking)
2. Read frame immediately
3. Store in shared buffer (atomic)
4. Track FPS
5. Increment frame counter
6. Loop back

NO processing, NO queuing, NO overlays - just raw capture at maximum speed.
"""

import asyncio
import logging
import time
from typing import Optional

import numpy as np
from picamera2 import Picamera2

# Handle relative import for both module and standalone use
try:
    from .camera_utils import RollingFPS
except ImportError:
    from camera_utils import RollingFPS

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

        # FPS tracking
        self.fps_tracker = RollingFPS(window_seconds=5.0)
        self.captured_frames = 0
        self.camera_hardware_fps: float = 0.0  # FPS from camera metadata (sensor rate)

        # Hardware frame tracking (for accurate drop detection)
        self.hardware_frame_number = 0  # Calculated from sensor timestamps
        self.last_sensor_timestamp_ns: Optional[int] = None
        self.expected_frame_interval_ns: Optional[int] = None

        # Latest frame storage (lock-free, just replace)
        self.latest_frame: Optional[np.ndarray] = None
        self.latest_metadata: Optional[dict] = None
        self.latest_capture_time: Optional[float] = None
        self.latest_capture_monotonic: Optional[float] = None
        self.latest_sensor_timestamp_ns: Optional[int] = None  # Hardware timestamp (nanoseconds)
        self.latest_hardware_fps: float = 0.0  # Hardware FPS from this frame's metadata
        self._frame_lock = asyncio.Lock()

        # Control
        self._running = False
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

    async def _capture_loop(self):
        """
        TIGHT CAPTURE LOOP - Using lores stream

        Uses capture_array("lores") instead of capture_request() to avoid
        stealing frames from the H.264 encoder on the main stream.

        This provides hardware-scaled preview frames without interfering
        with recording.
        """
        self.logger.info("Entering tight capture loop (using lores stream)")

        while self._running:
            try:
                # TIGHT: Atomic capture - get frame + metadata in single operation
                # Using capture_request() prevents missing frames due to double-wait
                # With dual-stream config, lores stream is independent from encoder
                loop = asyncio.get_event_loop()
                request = await loop.run_in_executor(None, self.picam2.capture_request)

                # Extract lores frame and metadata atomically
                raw_frame = request.make_array("lores")
                metadata = request.get_metadata()
                capture_time = time.time()
                capture_monotonic = time.perf_counter()

                # Release request immediately to free resources
                request.release()

                # TIGHT: Extract hardware FPS from metadata (sensor rate)
                hardware_fps = 0.0
                if 'FrameDuration' in metadata:
                    frame_duration_us = metadata['FrameDuration']
                    if frame_duration_us > 0:
                        hardware_fps = 1000000.0 / frame_duration_us
                        self.camera_hardware_fps = hardware_fps
                        # Calculate expected frame interval for drop detection
                        self.expected_frame_interval_ns = int(frame_duration_us * 1000)
                        # Debug: Log on first few frames
                        if self.captured_frames < 3:
                            self.logger.info(
                                "Frame %d: FrameDuration=%d us, expected_interval=%d ns (%.2f ms)",
                                self.captured_frames, frame_duration_us, self.expected_frame_interval_ns,
                                self.expected_frame_interval_ns / 1_000_000
                            )

                # TIGHT: Extract hardware timestamp (nanoseconds since boot)
                sensor_timestamp_ns = metadata.get('SensorTimestamp')

                # TIGHT: Calculate hardware frame number using timestamp deltas
                # This gives us ACCURATE frame counting even if frames are dropped
                dropped_since_last = 0
                if sensor_timestamp_ns is not None:
                    if self.last_sensor_timestamp_ns is not None and self.expected_frame_interval_ns is not None:
                        # Calculate how many frame intervals passed
                        delta_ns = sensor_timestamp_ns - self.last_sensor_timestamp_ns
                        # Round to nearest integer (handles small timing variations)
                        intervals_passed = round(delta_ns / self.expected_frame_interval_ns)
                        # Dropped frames = intervals - 1 (we expect 1 interval normally)
                        dropped_since_last = max(0, intervals_passed - 1)

                        # Debug: Log only actual dropped frames (not timing jitter)
                        if dropped_since_last > 0:
                            self.logger.warning(
                                "Frame %d: delta=%d ns (%.2f ms), expected=%d ns, intervals=%d, dropped=%d",
                                self.captured_frames, delta_ns, delta_ns / 1_000_000,
                                self.expected_frame_interval_ns, intervals_passed, dropped_since_last
                            )

                        # Increment hardware frame number by intervals passed
                        self.hardware_frame_number += intervals_passed
                    else:
                        # First frame with valid timestamp
                        self.hardware_frame_number = 0
                        if self.captured_frames < 3:
                            self.logger.info(
                                "Frame %d: First frame with timestamp, hw_frame_num=0, last_ts=%s, expected_interval=%s",
                                self.captured_frames, self.last_sensor_timestamp_ns, self.expected_frame_interval_ns
                            )

                    self.last_sensor_timestamp_ns = sensor_timestamp_ns
                else:
                    # No SensorTimestamp available - use software counting
                    self.hardware_frame_number = self.captured_frames
                    if self.captured_frames < 3:
                        self.logger.warning("Frame %d: No SensorTimestamp in metadata!", self.captured_frames)

                # TIGHT: Increment software counter (counts frames we received)
                self.captured_frames += 1

                # TIGHT: Track FPS (5 second rolling window)
                self.fps_tracker.add_frame(capture_time)

                # TIGHT: Add frame tracking to metadata
                metadata['CaptureFrameIndex'] = self.captured_frames - 1  # Software counter (0-indexed)
                metadata['HardwareFrameNumber'] = self.hardware_frame_number  # Hardware-based frame number
                metadata['DroppedSinceLast'] = dropped_since_last  # Calculated from timestamp deltas

                # Debug: Log metadata on first few frames
                if self.captured_frames <= 3:
                    self.logger.info(
                        "Frame %d: Metadata set - CaptureFrameIndex=%d, HardwareFrameNumber=%d, DroppedSinceLast=%d",
                        self.captured_frames - 1, metadata['CaptureFrameIndex'],
                        metadata['HardwareFrameNumber'], metadata['DroppedSinceLast']
                    )

                # TIGHT: Store latest frame atomically
                async with self._frame_lock:
                    self.latest_frame = raw_frame
                    self.latest_metadata = metadata
                    self.latest_capture_time = capture_time
                    self.latest_capture_monotonic = capture_monotonic
                    self.latest_sensor_timestamp_ns = sensor_timestamp_ns
                    self.latest_hardware_fps = hardware_fps

                # TIGHT: Immediately loop back - no delays!

            except asyncio.CancelledError:
                break
            except RuntimeError as exc:
                # Graceful shutdown - event loop is closing
                if "cannot schedule new futures" in str(exc):
                    self.logger.debug("Event loop shutting down, exiting capture loop")
                    break
                elif self._running:
                    self.logger.error("Capture error: %s", exc, exc_info=True)
                    await asyncio.sleep(0.1)
            except Exception as exc:
                if self._running:
                    self.logger.error("Capture error: %s", exc, exc_info=True)
                    await asyncio.sleep(0.1)  # Brief pause on error

        self.logger.info("Exited tight capture loop")

    async def get_latest_frame(self):
        """
        Get the latest captured frame (non-blocking).

        Returns: (frame, metadata, capture_time, capture_monotonic, sensor_timestamp_ns, hardware_fps) or (None, None, None, None, None, 0.0) if no frame yet
        """
        async with self._frame_lock:
            return (self.latest_frame, self.latest_metadata, self.latest_capture_time,
                    self.latest_capture_monotonic, self.latest_sensor_timestamp_ns, self.latest_hardware_fps)

    def get_fps(self) -> float:
        """Get current capture FPS (calculated from rolling window)."""
        return self.fps_tracker.get_fps()

    def get_hardware_fps(self) -> float:
        """Get camera hardware FPS (from sensor metadata)."""
        return self.camera_hardware_fps

    def get_frame_count(self) -> int:
        """Get total captured frame count."""
        return self.captured_frames


if __name__ == "__main__":
    """
    Simple standalone test for the camera capture loop.

    This test:
    1. Initializes a camera
    2. Starts the capture loop
    3. Monitors FPS and frame count for 10 seconds
    4. Displays stats every second
    5. Verifies frames are being captured
    """
    import sys

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%H:%M:%S'
    )

    async def test_capture_loop():
        """Test the capture loop standalone."""
        print("=" * 60)
        print("CAMERA CAPTURE LOOP TEST")
        print("=" * 60)

        # Initialize camera
        print("\n[1/4] Initializing camera...")
        try:
            picam2 = Picamera2(0)
            config = picam2.create_video_configuration(
                main={"size": (1920, 1080)},
                controls={"FrameDurationLimits": (33333, 33333)},  # ~30 FPS
            )
            picam2.configure(config)
            picam2.start()
            print("✓ Camera initialized successfully")
        except Exception as e:
            print(f"✗ Camera initialization failed: {e}")
            return False

        # Create capture loop
        print("\n[2/4] Creating capture loop...")
        capture_loop = CameraCaptureLoop(camera_id=0, picam2=picam2)
        print("✓ Capture loop created")

        # Start capture loop
        print("\n[3/4] Starting capture loop...")
        await capture_loop.start()
        await asyncio.sleep(0.5)  # Let it warm up
        print("✓ Capture loop started")

        # Monitor for 10 seconds
        print("\n[4/4] Monitoring capture for 10 seconds...")
        print("\nTime | FPS (calc) | FPS (hw) | Frames | Frame Shape")
        print("-" * 60)

        test_duration = 10
        last_frame_count = 0
        success = True

        for i in range(test_duration):
            await asyncio.sleep(1.0)

            # Get stats
            fps = capture_loop.get_fps()
            hardware_fps = capture_loop.get_hardware_fps()
            frame_count = capture_loop.get_frame_count()
            frame, metadata, capture_time, _, _, _ = await capture_loop.get_latest_frame()

            # Check progress
            frames_this_second = frame_count - last_frame_count
            last_frame_count = frame_count

            # Display stats
            if frame is not None:
                print(f"{i+1:4d}s | {fps:10.2f} | {hardware_fps:8.2f} | {frame_count:6d} | {frame.shape}")
            else:
                print(f"{i+1:4d}s | {fps:10.2f} | {hardware_fps:8.2f} | {frame_count:6d} | No frame yet")
                if i > 2:  # Should have frames by 3 seconds
                    success = False

            # Verify frames are increasing
            if i > 0 and frames_this_second == 0:
                print(f"  ⚠ WARNING: No new frames captured in the last second!")
                success = False

        # Stop capture loop
        print("\n[5/5] Stopping capture loop...")
        await capture_loop.stop()
        picam2.stop()
        picam2.close()
        print("✓ Capture loop stopped")

        # Final results
        print("\n" + "=" * 60)
        final_fps = capture_loop.get_fps()
        final_count = capture_loop.get_frame_count()

        print("TEST RESULTS:")
        print(f"  Total frames captured: {final_count}")
        print(f"  Final FPS: {final_fps:.2f}")
        print(f"  Expected frames (~30 FPS × 10s): ~300")

        if success and final_count > 200:  # Allow some margin
            print("\n✓ TEST PASSED - Capture loop working correctly!")
            return True
        else:
            print("\n✗ TEST FAILED - Issues detected")
            return False

    # Run test
    try:
        result = asyncio.run(test_capture_loop())
        sys.exit(0 if result else 1)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
