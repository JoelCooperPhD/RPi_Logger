#!/usr/bin/env python3
"""
Test actual camera hardware cleanup timing.
Find out what's REALLY slow.
"""

import asyncio
import time
from picamera2 import Picamera2


async def test_camera_lifecycle():
    """Test each camera operation to find blocking points."""

    print("=" * 80)
    print("CAMERA HARDWARE LIFECYCLE TEST")
    print("=" * 80)

    try:
        # ===== INITIALIZATION =====
        print("\n1. Creating Picamera2 instance...")
        start = time.perf_counter()
        picam2 = Picamera2()
        duration = time.perf_counter() - start
        print(f"   ✓ Created in {duration*1000:.1f}ms")

        # ===== CONFIGURATION =====
        print("\n2. Configuring camera...")
        start = time.perf_counter()
        config = picam2.create_preview_configuration(
            main={"size": (1920, 1080)},
            lores={"size": (640, 480)},
            display="lores"
        )
        picam2.configure(config)
        duration = time.perf_counter() - start
        print(f"   ✓ Configured in {duration*1000:.1f}ms")

        # ===== START =====
        print("\n3. Starting camera...")
        start = time.perf_counter()
        picam2.start()
        duration = time.perf_counter() - start
        print(f"   ✓ Started in {duration*1000:.1f}ms")

        # ===== CAPTURE SOME FRAMES =====
        print("\n4. Capturing frames...")
        for i in range(5):
            start = time.perf_counter()
            request = picam2.capture_request()
            capture_duration = time.perf_counter() - start

            array = request.make_array("lores")
            duration = time.perf_counter() - start

            request.release()
            release_duration = time.perf_counter() - start

            print(f"   Frame {i}: capture={capture_duration*1000:.1f}ms, "
                  f"make_array={(duration-capture_duration)*1000:.1f}ms, "
                  f"release={(release_duration-duration)*1000:.1f}ms")

        # Let it run for a bit
        await asyncio.sleep(1.0)

        # ===== STOP (THE CRITICAL ONE) =====
        print("\n5. Stopping camera... (THIS IS WHERE DELAYS HAPPEN?)")
        start = time.perf_counter()
        picam2.stop()
        duration = time.perf_counter() - start
        print(f"   {'⚠️ SLOW' if duration > 0.1 else '✓'} Stopped in {duration*1000:.1f}ms")

        # ===== CLOSE (ANOTHER CRITICAL ONE) =====
        print("\n6. Closing camera... (OR HERE?)")
        start = time.perf_counter()
        picam2.close()
        duration = time.perf_counter() - start
        print(f"   {'⚠️ SLOW' if duration > 0.1 else '✓'} Closed in {duration*1000:.1f}ms")

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 80)
    print("TESTING CLEANUP IN EXECUTOR")
    print("=" * 80)

    # Test again but with executor pattern
    try:
        print("\n7. Creating camera again...")
        picam2 = Picamera2()
        config = picam2.create_preview_configuration(
            main={"size": (1920, 1080)},
            lores={"size": (640, 480)},
            display="lores"
        )
        picam2.configure(config)
        picam2.start()
        print("   ✓ Camera running")

        await asyncio.sleep(0.5)

        # Stop in executor
        print("\n8. Stopping via executor...")
        loop = asyncio.get_running_loop()
        start = time.perf_counter()
        await loop.run_in_executor(None, picam2.stop)
        duration = time.perf_counter() - start
        print(f"   Executor stop: {duration*1000:.1f}ms")

        # Close in executor
        print("\n9. Closing via executor...")
        start = time.perf_counter()
        await loop.run_in_executor(None, picam2.close)
        duration = time.perf_counter() - start
        print(f"   Executor close: {duration*1000:.1f}ms")

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 80)
    print("CONCLUSION:")
    print("=" * 80)
    print("Look at the timings above.")
    print("If stop/close are fast (<100ms), problem is elsewhere.")
    print("If slow (>1s), THAT's your blocking operation.")


if __name__ == "__main__":
    asyncio.run(test_camera_lifecycle())
