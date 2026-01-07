#!/usr/bin/env python3
"""Test CSI camera capture in a subprocess scenario - simulating the real app."""

import asyncio
import multiprocessing
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Force spawn method like master.py does
try:
    multiprocessing.set_start_method('spawn', force=True)
except RuntimeError:
    pass

DEBUG_LOG = '/tmp/csi_debug.log'

def debug_log(component: str, msg: str) -> None:
    ts = time.strftime('%H:%M:%S') + f'.{int((time.time() % 1) * 1000):03d}'
    pid = os.getpid()
    try:
        with open(DEBUG_LOG, 'a') as f:
            f.write(f"{ts} [{component}] [{pid}:MainThread] {msg}\n")
            f.flush()
    except Exception:
        pass


def capture_in_subprocess(sensor_id: str, result_queue):
    """This runs in a subprocess, simulating CSICameras module."""
    import asyncio

    async def do_capture():
        debug_log("SUBPROCESS", f"Starting in subprocess PID={os.getpid()}")

        from rpi_logger.modules.CSICameras.csi_core.capture import PicamCapture

        debug_log("SUBPROCESS", "Creating PicamCapture...")
        capture = PicamCapture(
            sensor_id=sensor_id,
            resolution=(1440, 1088),
            fps=60.0,
            lores_size=(320, 240),
        )

        debug_log("SUBPROCESS", "Starting capture...")
        await capture.start()
        debug_log("SUBPROCESS", "Capture started, getting frames...")

        frame_count = 0
        max_frames = 10

        try:
            async for frame in capture.frames():
                frame_count += 1
                debug_log("SUBPROCESS", f"Frame {frame_count} shape={frame.data.shape}")
                if frame_count >= max_frames:
                    break
        except asyncio.TimeoutError:
            debug_log("SUBPROCESS", f"Timeout after {frame_count} frames")
        except Exception as e:
            debug_log("SUBPROCESS", f"Error: {type(e).__name__}: {e}")

        debug_log("SUBPROCESS", "Stopping capture...")
        await capture.stop()
        debug_log("SUBPROCESS", f"Done, captured {frame_count} frames")

        return frame_count

    try:
        result = asyncio.run(do_capture())
        result_queue.put(("success", result))
    except Exception as e:
        debug_log("SUBPROCESS", f"Fatal error: {type(e).__name__}: {e}")
        result_queue.put(("error", str(e)))


async def test_subprocess_with_scanner():
    """Test capture in subprocess while scanner runs in main process."""
    from rpi_logger.core.devices.csi_scanner import CSIScanner

    debug_log("MAIN", "=" * 60)
    debug_log("MAIN", "TEST: Subprocess capture with scanner in main process")
    debug_log("MAIN", "=" * 60)

    # Start scanner in main process (like real app)
    debug_log("MAIN", "Starting scanner in main process...")
    scanner = CSIScanner(scan_interval=2.0)
    await scanner.start()
    debug_log("MAIN", "Scanner started")

    # Wait for scanner to do a couple scans
    await asyncio.sleep(3)
    debug_log("MAIN", "Scanner warmup complete")

    # Now spawn subprocess for capture (like real app spawns CSICameras module)
    result_queue = multiprocessing.Queue()

    debug_log("MAIN", "Spawning capture subprocess...")
    proc = multiprocessing.Process(
        target=capture_in_subprocess,
        args=("0", result_queue)
    )
    proc.start()
    debug_log("MAIN", f"Subprocess spawned PID={proc.pid}")

    # Wait for subprocess with timeout
    proc.join(timeout=30)

    if proc.is_alive():
        debug_log("MAIN", "Subprocess timed out, terminating...")
        proc.terminate()
        proc.join(timeout=5)
        success = False
        result = "timeout"
    else:
        try:
            status, result = result_queue.get_nowait()
            success = (status == "success" and result >= 10)
        except:
            success = False
            result = "no result"

    debug_log("MAIN", f"Subprocess result: success={success} frames={result}")

    # Stop scanner
    debug_log("MAIN", "Stopping scanner...")
    await scanner.stop()
    debug_log("MAIN", "Scanner stopped")

    return success


if __name__ == "__main__":
    # Clear log
    with open(DEBUG_LOG, 'w') as f:
        f.write("")

    print(f"Testing subprocess capture scenario...")
    print(f"Check {DEBUG_LOG} for details")
    print()

    result = asyncio.run(test_subprocess_with_scanner())

    print(f"\n{'=' * 60}")
    print(f"DEBUG LOG:")
    print(f"{'=' * 60}")
    with open(DEBUG_LOG, 'r') as f:
        print(f.read())

    print(f"\n{'=' * 60}")
    print(f"RESULT: {'PASS' if result else 'FAIL'}")
    print(f"{'=' * 60}")

    sys.exit(0 if result else 1)
