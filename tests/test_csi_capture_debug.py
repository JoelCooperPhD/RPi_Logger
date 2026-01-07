#!/usr/bin/env python3
"""Standalone test to debug CSI camera capture blocking issue."""

import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


async def test_capture_sequence():
    """Test the full probe -> capture sequence with debug logging."""
    from rpi_logger.modules.CSICameras.csi_core.backends import picam_backend
    from rpi_logger.modules.CSICameras.csi_core.capture import PicamCapture

    debug_log("TEST", "=" * 60)
    debug_log("TEST", "STARTING CAPTURE SEQUENCE TEST")
    debug_log("TEST", "=" * 60)

    sensor_id = "0"

    # Phase 1: Probe
    debug_log("TEST", f"PHASE_1_PROBE_START sensor={sensor_id}")
    probe_start = time.time()
    caps = await picam_backend.probe(sensor_id)
    probe_ms = int((time.time() - probe_start) * 1000)
    debug_log("TEST", f"PHASE_1_PROBE_DONE elapsed={probe_ms}ms caps={caps is not None}")

    if not caps:
        debug_log("TEST", "ABORT: probe returned None")
        return False

    # Phase 2: Initialize capture (like bridge does)
    debug_log("TEST", "PHASE_2_INIT_CAPTURE_START")
    init_start = time.time()

    resolution = (1440, 1088)  # IMX296 native
    fps = 60.0
    lores_size = (320, 240)

    capture = PicamCapture(
        sensor_id=sensor_id,
        resolution=resolution,
        fps=fps,
        lores_size=lores_size,
    )

    await capture.start()
    init_ms = int((time.time() - init_start) * 1000)
    debug_log("TEST", f"PHASE_2_INIT_CAPTURE_DONE elapsed={init_ms}ms")

    # Phase 3: Capture frames
    debug_log("TEST", "PHASE_3_CAPTURE_FRAMES_START")
    frame_count = 0
    max_frames = 30

    try:
        async for frame in capture.frames():
            frame_count += 1
            if frame_count <= 5 or frame_count % 10 == 0:
                debug_log("TEST", f"PHASE_3_FRAME frame={frame_count} shape={frame.data.shape if hasattr(frame.data, 'shape') else 'N/A'}")
            if frame_count >= max_frames:
                break
    except asyncio.TimeoutError:
        debug_log("TEST", f"PHASE_3_TIMEOUT after {frame_count} frames")
    except Exception as e:
        debug_log("TEST", f"PHASE_3_ERROR {type(e).__name__}: {e}")

    debug_log("TEST", f"PHASE_3_CAPTURE_FRAMES_DONE total={frame_count}")

    # Phase 4: Cleanup
    debug_log("TEST", "PHASE_4_CLEANUP_START")
    await capture.stop()
    debug_log("TEST", "PHASE_4_CLEANUP_DONE")

    success = frame_count >= max_frames
    debug_log("TEST", f"TEST_COMPLETE success={success} frames={frame_count}/{max_frames}")
    return success


async def test_with_scanner_running():
    """Test capture while scanner is running (simulates real app)."""
    from rpi_logger.core.devices.csi_scanner import CSIScanner

    debug_log("TEST", "=" * 60)
    debug_log("TEST", "STARTING TEST WITH SCANNER RUNNING")
    debug_log("TEST", "=" * 60)

    # Start scanner (like main app does)
    scanner = CSIScanner(scan_interval=2.0)
    await scanner.start()
    debug_log("TEST", "SCANNER_STARTED")

    # Wait a bit for scanner to do a few scans
    await asyncio.sleep(3)
    debug_log("TEST", "SCANNER_WARMUP_DONE")

    # Now try capture sequence
    try:
        success = await test_capture_sequence()
    finally:
        await scanner.stop()
        debug_log("TEST", "SCANNER_STOPPED")

    return success


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-scanner", action="store_true", dest="with_scanner", help="Run test with scanner active")
    args = parser.parse_args()

    # Clear log
    with open(DEBUG_LOG, 'w') as f:
        f.write("")

    print(f"Running test... (check {DEBUG_LOG})")

    if args.with_scanner:
        result = asyncio.run(test_with_scanner_running())
    else:
        result = asyncio.run(test_capture_sequence())

    print(f"\n{'=' * 60}")
    print(f"DEBUG LOG:")
    print(f"{'=' * 60}")
    with open(DEBUG_LOG, 'r') as f:
        print(f.read())

    sys.exit(0 if result else 1)
