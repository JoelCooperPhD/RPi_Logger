#!/usr/bin/env python3
"""
Debug script to test eye tracker detection and data reception
"""

import sys
import time
from pupil_labs.realtime_api.simple import discover_one_device

print("="*70)
print("EYE TRACKER DEBUG TEST")
print("="*70)
print()

# Step 1: Try to discover device
print("Step 1: Discovering device (10 second timeout)...")
try:
    device = discover_one_device(max_search_duration_seconds=10)
    if device:
        print(f"✓ Device found: {device}")
        print(f"  Type: {type(device)}")
        try:
            print(f"  Device info: {dir(device)}")
        except:
            pass
    else:
        print("✗ No device found")
        sys.exit(1)
except Exception as e:
    print(f"✗ Discovery failed: {e}")
    sys.exit(1)

# Step 2: Try to get gaze data
print("\nStep 2: Testing gaze data reception...")
gaze_received = False
for i in range(10):
    try:
        print(f"  Attempt {i+1}/10...", end="")
        gaze = device.receive_gaze_datum(timeout_seconds=1.0)
        if gaze:
            print(f" ✓ Got gaze data!")
            print(f"    x={gaze.x:.2f}, y={gaze.y:.2f}, worn={gaze.worn}")
            gaze_received = True
            break
        else:
            print(" - No data")
    except Exception as e:
        print(f" ✗ Error: {e}")
    time.sleep(0.5)

if not gaze_received:
    print("  ⚠ No gaze data received in 10 attempts")

# Step 3: Try to get scene frame
print("\nStep 3: Testing scene video frame reception...")
frame_received = False
for i in range(5):
    try:
        print(f"  Attempt {i+1}/5...", end="")
        frame = device.receive_scene_video_frame(timeout_seconds=1.0)
        if frame:
            print(f" ✓ Got scene frame!")
            print(f"    Shape: {frame.bgr_pixels.shape}")
            print(f"    Timestamp: {frame.timestamp_unix_seconds}")
            frame_received = True
            break
        else:
            print(" - No frame")
    except Exception as e:
        print(f" ✗ Error: {e}")
    time.sleep(0.5)

if not frame_received:
    print("  ⚠ No scene frames received in 5 attempts")

# Step 4: Test continuous data stream
print("\nStep 4: Testing continuous data stream (5 seconds)...")
start_time = time.time()
gaze_count = 0
frame_count = 0

while time.time() - start_time < 5:
    try:
        # Try gaze
        gaze = device.receive_gaze_datum(timeout_seconds=0.01)
        if gaze:
            gaze_count += 1

        # Try frame (less frequently)
        if int(time.time() - start_time) % 1 == 0:
            frame = device.receive_scene_video_frame(timeout_seconds=0.01)
            if frame:
                frame_count += 1
    except:
        pass

print(f"  Received {gaze_count} gaze samples and {frame_count} frames in 5 seconds")

# Summary
print("\n" + "="*70)
print("SUMMARY")
print("="*70)
if gaze_received or frame_received:
    print("✅ Device is connected and sending data!")
    print(f"   Gaze data: {'Yes' if gaze_received else 'No'}")
    print(f"   Scene frames: {'Yes' if frame_received else 'No'}")
    print(f"   Data rate: {gaze_count/5:.1f} Hz gaze, {frame_count/5:.1f} Hz frames")
else:
    print("⚠ Device found but no data received")
    print("  Possible issues:")
    print("  - Device may need to be powered on/activated")
    print("  - Device may be in a different mode")
    print("  - Connection may be unstable")

# Cleanup
device.close()
print("\nDevice closed.")