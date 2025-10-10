#!/usr/bin/env python3
"""
CAMERA COLLATOR LOOP - Timing-based frame collation.

This loop runs at a specified FPS (e.g., 10 FPS) and:
1. Waits for precise timing interval
2. Grabs latest frame from capture loop
3. Duplicates if no new frame available
4. Passes frame to processor queue
5. Tracks collation FPS
6. Loop back

This decouples capture rate from display/recording rate.
"""

import asyncio
import logging
import time
from typing import Optional

import numpy as np

# Handle relative import for both module and standalone use
try:
    from .camera_utils import RollingFPS
except ImportError:
    from camera_utils import RollingFPS

logger = logging.getLogger("CameraCollator")


class CameraCollatorLoop:
    """
    Timing-based frame collation loop.

    Runs at specified FPS (independent of camera capture rate),
    grabs latest frames from capture loop, handles duplicates.
    """

    def __init__(self, camera_id: int, target_fps: float, capture_loop):
        self.camera_id = camera_id
        self.target_fps = target_fps
        self.capture_loop = capture_loop
        self.logger = logging.getLogger(f"CameraCollator{camera_id}")

        # FPS tracking
        self.fps_tracker = RollingFPS(window_seconds=5.0)
        self.collated_frames = 0

        # Frame storage
        self.last_collated_frame: Optional[np.ndarray] = None
        self._output_queue: Optional[asyncio.Queue] = None  # Created in start()

        # Control
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the collation loop."""
        if self._running:
            return
        self._running = True
        # Create queue in the running event loop with larger buffer for smoother playback
        self._output_queue = asyncio.Queue(maxsize=10)
        self._task = asyncio.create_task(self._collation_loop())
        self.logger.info("Camera collation loop started at %.1f FPS", self.target_fps)

    async def stop(self):
        """Stop the collation loop."""
        if not self._running:
            return
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.logger.info("Camera collation loop stopped")

    async def _collation_loop(self):
        """
        TIMING-BASED COLLATION LOOP

        This runs at exact target FPS (e.g., 10 FPS).
        Grabs latest frame from capture, duplicates if needed.
        """
        self.logger.info("Entering collation loop at %.1f FPS", self.target_fps)

        frame_interval = 1.0 / self.target_fps if self.target_fps > 0 else 0.033
        next_frame_time = time.perf_counter()

        while self._running:
            try:
                # TIMING: Wait until it's time for next frame
                now = time.perf_counter()
                wait_time = next_frame_time - now
                if wait_time > 0:
                    await asyncio.sleep(wait_time)

                # TIMING: Grab latest frame from capture loop
                frame, metadata, capture_time, capture_monotonic, _ = await self.capture_loop.get_latest_frame()

                # TIMING: Get hardware FPS from capture loop (always current)
                hardware_fps = self.capture_loop.get_hardware_fps()

                # TIMING: Handle no frame or duplicate
                is_duplicate = False
                if frame is None:
                    # No frames from camera yet, use last collated
                    if self.last_collated_frame is None:
                        # No frames at all yet, skip this cycle
                        next_frame_time += frame_interval
                        continue
                    frame = self.last_collated_frame
                    is_duplicate = True
                else:
                    # Got new frame, store reference (no copy needed - frame already owned by capture loop)
                    self.last_collated_frame = frame

                # TIMING: Increment collated frame counter
                self.collated_frames += 1

                # TIMING: Track collation FPS
                self.fps_tracker.add_frame(time.time())

                # TIMING: Pass to output queue (non-blocking)
                frame_data = {
                    'frame': frame,
                    'metadata': metadata,
                    'capture_time': capture_time,
                    'capture_monotonic': capture_monotonic,
                    'hardware_fps': hardware_fps,
                    'is_duplicate': is_duplicate,
                    'collated_frame_num': self.collated_frames,
                }

                try:
                    self._output_queue.put_nowait(frame_data)
                except asyncio.QueueFull:
                    # Drop oldest, add newest
                    try:
                        self._output_queue.get_nowait()
                        self._output_queue.put_nowait(frame_data)
                    except (asyncio.QueueEmpty, asyncio.QueueFull):
                        pass

                # TIMING: Schedule next frame
                next_frame_time += frame_interval

            except asyncio.CancelledError:
                break
            except Exception as exc:
                if self._running:
                    self.logger.error("Collation error: %s", exc, exc_info=True)
                    await asyncio.sleep(0.1)

        self.logger.info("Exited collation loop")

    async def get_frame(self):
        """
        Get LATEST collated frame, discarding any older queued frames.

        This ensures display always shows the freshest frame, preventing
        lag when processor falls behind collator.

        Returns: frame_data dict or None on timeout
        """
        latest_frame = None

        # Drain queue to get only the newest frame (discard old frames)
        try:
            while True:
                latest_frame = self._output_queue.get_nowait()
        except asyncio.QueueEmpty:
            pass

        # If no frames were in queue, wait for next one
        if latest_frame is None:
            try:
                # Adaptive timeout: 2x frame interval (e.g., 66ms for 30 FPS)
                timeout = 2.0 / self.target_fps if self.target_fps > 0 else 0.1
                latest_frame = await asyncio.wait_for(self._output_queue.get(), timeout=timeout)
            except asyncio.TimeoutError:
                return None

        return latest_frame

    def get_fps(self) -> float:
        """Get current collation FPS."""
        return self.fps_tracker.get_fps()

    def get_frame_count(self) -> int:
        """Get total collated frame count."""
        return self.collated_frames


if __name__ == "__main__":
    """
    Simple standalone test for the camera collation loop.

    This test:
    1. Initializes a camera
    2. Starts capture loop (30 FPS)
    3. Starts collation loop (10 FPS)
    4. Monitors both loops for 10 seconds
    5. Verifies collation runs at target FPS
    6. Checks frame retrieval from queue
    """
    import sys

    # Handle relative import for standalone use
    try:
        from .camera_capture_loop import CameraCaptureLoop
    except ImportError:
        from camera_capture_loop import CameraCaptureLoop

    from picamera2 import Picamera2

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%H:%M:%S'
    )

    async def test_single_fps(target_fps: float, test_duration: int, picam2, capture_loop):
        """Test collation at a specific FPS."""
        print(f"\n{'='*60}")
        print(f"Testing Collation at {target_fps} FPS")
        print(f"{'='*60}")

        # Create collation loop
        collator_loop = CameraCollatorLoop(
            camera_id=0,
            target_fps=target_fps,
            capture_loop=capture_loop
        )

        # Start collation loop
        await collator_loop.start()
        await asyncio.sleep(0.5)  # Let it warm up

        print(f"\nMonitoring for {test_duration} seconds...")
        print("\nTime | Capture FPS | Collation FPS | Capture Δ | Collated Δ | Duplicates")
        print("-" * 80)

        last_capture_count = capture_loop.get_frame_count()
        last_collated_count = 0
        success = True

        for i in range(test_duration):
            await asyncio.sleep(1.0)

            # Get stats
            capture_fps = capture_loop.get_fps()
            capture_count = capture_loop.get_frame_count()
            collation_fps = collator_loop.get_fps()
            collated_count = collator_loop.get_frame_count()

            # Calculate deltas
            capture_delta = capture_count - last_capture_count
            collated_delta = collated_count - last_collated_count
            last_capture_count = capture_count
            last_collated_count = collated_count

            # Display stats
            # Calculate expected duplicates for this interval
            expected_duplicates = max(0, collated_delta - capture_delta)
            print(f"{i+1:4d}s | {capture_fps:11.2f} | {collation_fps:13.2f} | "
                  f"{capture_delta:9d} | {collated_delta:10d} | {expected_duplicates:10d}")

            # Verify collation is running at target FPS (after warm-up)
            if i > 1:
                # Allow 25% margin for very high FPS
                margin = 0.25 if target_fps > 45 else 0.20
                if abs(collation_fps - target_fps) > target_fps * margin:
                    print(f"  ⚠ WARNING: Collation FPS ({collation_fps:.2f}) "
                          f"deviates from target ({target_fps:.2f})")
                    success = False

            # Verify frames are increasing
            if i > 0 and collated_delta == 0:
                print(f"  ⚠ WARNING: No new collated frames in the last second!")
                success = False

        # Stop collation loop
        await collator_loop.stop()

        # Final results
        final_capture_count = capture_loop.get_frame_count()
        final_collation_fps = collator_loop.get_fps()
        final_collated_count = collator_loop.get_frame_count()

        print("\nRESULTS:")
        print(f"  Collated frames: {final_collated_count}")
        print(f"  Collation FPS: {final_collation_fps:.2f}")
        print(f"  Expected frames: ~{int(target_fps * test_duration)}")

        if final_capture_count > 0:
            print(f"  Frame ratio: {final_collated_count/final_capture_count:.2%}")

            # Calculate actual duplicates needed
            total_duplicates = max(0, final_collated_count - final_capture_count)
            print(f"  Duplicate frames needed: {total_duplicates}")

            if target_fps > 30:
                expected_duplicates_approx = final_collated_count - final_capture_count
                print(f"  Expected duplicates: ~{max(0, expected_duplicates_approx)}")

        # Validate
        expected_collated = target_fps * test_duration
        margin = 0.25 if target_fps > 45 else 0.20

        if (success and
            final_collated_count >= expected_collated * (1 - margin) and
            abs(final_collation_fps - target_fps) <= target_fps * margin):
            print(f"✓ PASSED - {target_fps} FPS test successful!")
            return True
        else:
            print(f"✗ FAILED - {target_fps} FPS test failed")
            return False

    async def test_collator_loop():
        """Test the collation loop with multiple FPS scenarios."""
        print("=" * 60)
        print("CAMERA COLLATION LOOP TEST - MULTI-FPS")
        print("=" * 60)
        print("\nThis test will verify collation at:")
        print("  • 60 FPS (2x camera rate - requires duplicates)")
        print("  • 30 FPS (equal to camera rate)")
        print("  • 10 FPS (1/3 camera rate)")

        # Initialize camera
        print("\n[1/3] Initializing camera...")
        try:
            picam2 = Picamera2(0)
            config = picam2.create_video_configuration(
                main={"size": (1920, 1080)},
                controls={"FrameDurationLimits": (33333, 33333)},  # ~30 FPS
            )
            picam2.configure(config)
            picam2.start()
            print("✓ Camera initialized (target: ~30 FPS)")
        except Exception as e:
            print(f"✗ Camera initialization failed: {e}")
            return False

        # Create capture loop
        print("\n[2/3] Creating capture loop...")
        capture_loop = CameraCaptureLoop(camera_id=0, picam2=picam2)
        await capture_loop.start()
        await asyncio.sleep(0.5)
        print("✓ Capture loop started")

        # Test scenarios
        print("\n[3/3] Running collation tests...")

        test_scenarios = [
            (60.0, 5),  # 60 FPS for 5 seconds (faster than camera)
            (30.0, 5),  # 30 FPS for 5 seconds (equal to camera)
            (10.0, 5),  # 10 FPS for 5 seconds (slower than camera)
        ]

        results = []
        for target_fps, duration in test_scenarios:
            result = await test_single_fps(target_fps, duration, picam2, capture_loop)
            results.append((target_fps, result))
            if target_fps != test_scenarios[-1][0]:  # Not the last test
                print("\nWaiting 2 seconds before next test...")
                await asyncio.sleep(2.0)

        # Cleanup
        print(f"\n{'='*60}")
        print("Cleaning up...")
        await capture_loop.stop()
        picam2.stop()
        picam2.close()
        print("✓ Cleanup complete")

        # Summary
        print(f"\n{'='*60}")
        print("TEST SUMMARY")
        print(f"{'='*60}")

        all_passed = True
        for target_fps, passed in results:
            status = "✓ PASSED" if passed else "✗ FAILED"
            print(f"  {target_fps:5.1f} FPS: {status}")
            if not passed:
                all_passed = False

        if all_passed:
            print("\n✓ ALL TESTS PASSED")
            print("  • Collation handles faster-than-camera FPS (duplicates)")
            print("  • Collation matches camera FPS (1:1)")
            print("  • Collation handles slower-than-camera FPS (skipping)")
            return True
        else:
            print("\n✗ SOME TESTS FAILED")
            return False

    # Run test
    try:
        result = asyncio.run(test_collator_loop())
        sys.exit(0 if result else 1)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
