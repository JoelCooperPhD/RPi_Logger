#!/usr/bin/env python3
"""Minimal FPS test for USB camera on Windows.

Tests different configurations to find maximum achievable FPS.
"""

import cv2
import time
import sys


def test_camera(device=0, width=640, height=480, fps_hint=30, backend=None, fourcc=None):
    """Test camera with specific settings."""

    # Open camera
    if backend:
        cap = cv2.VideoCapture(device, backend)
        backend_name = {
            cv2.CAP_DSHOW: "DSHOW",
            cv2.CAP_MSMF: "MSMF",
            cv2.CAP_ANY: "ANY",
        }.get(backend, str(backend))
    else:
        cap = cv2.VideoCapture(device)
        backend_name = "DEFAULT"

    if not cap.isOpened():
        print(f"  FAILED to open camera with {backend_name}")
        return None

    # Set fourcc before resolution
    if fourcc:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))

    # Set properties
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps_hint)

    # Reduce buffer size to minimize latency
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    # Read actual values
    actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    actual_fps = cap.get(cv2.CAP_PROP_FPS)
    actual_fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
    fourcc_str = "".join([chr((actual_fourcc >> 8 * i) & 0xFF) for i in range(4)])

    print(f"  Backend: {backend_name}, Codec: {fourcc_str}, "
          f"Resolution: {actual_width}x{actual_height}, "
          f"Reported FPS: {actual_fps}")

    # Warm up - discard first few frames
    for _ in range(10):
        cap.read()

    # Measure actual FPS over 3 seconds
    frame_count = 0
    start_time = time.perf_counter()
    test_duration = 3.0

    intervals = []
    last_time = start_time

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        now = time.perf_counter()
        frame_count += 1
        intervals.append(now - last_time)
        last_time = now

        if now - start_time >= test_duration:
            break

    cap.release()

    elapsed = time.perf_counter() - start_time
    measured_fps = frame_count / elapsed if elapsed > 0 else 0

    # Calculate stats
    if intervals:
        avg_interval = sum(intervals) / len(intervals)
        min_interval = min(intervals)
        max_interval = max(intervals)
        print(f"  Measured: {measured_fps:.1f} fps ({frame_count} frames in {elapsed:.1f}s)")
        print(f"  Intervals: avg={avg_interval*1000:.1f}ms, "
              f"min={min_interval*1000:.1f}ms, max={max_interval*1000:.1f}ms")

    return measured_fps


def main():
    device = 0
    if len(sys.argv) > 1:
        try:
            device = int(sys.argv[1])
        except ValueError:
            device = sys.argv[1]

    print(f"Testing camera: {device}")
    print(f"OpenCV version: {cv2.__version__}")
    print(f"Available backends: {cv2.videoio_registry.getBackendName(cv2.CAP_DSHOW)}")
    print()

    results = []

    # Test 1: Default settings
    print("Test 1: Default (no backend specified)")
    fps = test_camera(device)
    if fps:
        results.append(("Default", fps))
    print()

    # Test 2: DirectShow backend
    print("Test 2: DirectShow backend")
    fps = test_camera(device, backend=cv2.CAP_DSHOW)
    if fps:
        results.append(("DSHOW", fps))
    print()

    # Test 3: DirectShow + MJPG
    print("Test 3: DirectShow + MJPG codec")
    fps = test_camera(device, backend=cv2.CAP_DSHOW, fourcc="MJPG")
    if fps:
        results.append(("DSHOW+MJPG", fps))
    print()

    # Test 4: MSMF backend
    print("Test 4: Media Foundation backend")
    fps = test_camera(device, backend=cv2.CAP_MSMF)
    if fps:
        results.append(("MSMF", fps))
    print()

    # Test 5: MSMF + MJPG
    print("Test 5: Media Foundation + MJPG")
    fps = test_camera(device, backend=cv2.CAP_MSMF, fourcc="MJPG")
    if fps:
        results.append(("MSMF+MJPG", fps))
    print()

    # Test 6: Lower resolution
    print("Test 6: DirectShow + MJPG at 320x240")
    fps = test_camera(device, width=320, height=240, backend=cv2.CAP_DSHOW, fourcc="MJPG")
    if fps:
        results.append(("DSHOW+MJPG 320x240", fps))
    print()

    # Test 7: Higher FPS hint
    print("Test 7: DirectShow + MJPG with 60fps hint")
    fps = test_camera(device, fps_hint=60, backend=cv2.CAP_DSHOW, fourcc="MJPG")
    if fps:
        results.append(("DSHOW+MJPG fps=60", fps))
    print()

    # Test 8: YUY2/YUYV codec (uncompressed)
    print("Test 8: DirectShow + YUY2 codec")
    fps = test_camera(device, backend=cv2.CAP_DSHOW, fourcc="YUY2")
    if fps:
        results.append(("DSHOW+YUY2", fps))
    print()

    # Summary
    print("=" * 50)
    print("SUMMARY (sorted by FPS)")
    print("=" * 50)
    results.sort(key=lambda x: x[1], reverse=True)
    for name, fps in results:
        print(f"  {name:25s}: {fps:.1f} fps")

    if results:
        best = results[0]
        print()
        print(f"Best configuration: {best[0]} at {best[1]:.1f} fps")


if __name__ == "__main__":
    main()
