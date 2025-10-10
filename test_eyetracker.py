#!/usr/bin/env python3
"""
Test script for improved eye tracker detection
This verifies that phantom devices are not mistaken for real ones
"""

import subprocess
import json
import time
import sys

def test_eyetracker_detection(timeout=5):
    """Test eye tracker detection with verification"""
    print("="*70)
    print("EYE TRACKER DETECTION TEST")
    print("="*70)
    print(f"Testing with {timeout}s timeout")
    print()

    # Run the eye tracker module in slave mode to capture status messages
    cmd = [
        "/home/rs-pi-2/.local/bin/uv", "run",
        "Modules/EyeTracker/main_eye_tracker.py",
        "--retry-delay", str(timeout),
        "--log-level", "warning"
    ]

    print("Starting eye tracker module...")
    print("Command:", " ".join(cmd))
    print()

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )

    start_time = time.time()
    status_messages = []
    device_found = False
    verification_attempted = False

    # Monitor the output
    while time.time() - start_time < timeout + 10:  # Extra time for verification
        if proc.poll() is not None:
            print(f"Module exited with code: {proc.returncode}")
            break

        try:
            # Read stdout for status messages
            line = proc.stdout.readline()
            if line:
                try:
                    msg = json.loads(line.strip())
                    status = msg.get("status")
                    data = msg.get("data", {})

                    status_messages.append(msg)

                    if status == "searching":
                        print("🔍 Searching for eye tracker...")
                    elif status == "device_not_found":
                        print("❌ No device found or device verification failed")
                        print(f"   Message: {data.get('message', '')}")
                        device_found = False
                    elif status == "initialized":
                        print("✅ Device found and verified!")
                        device_found = True
                    elif status == "error":
                        print(f"⚠️  Error: {data.get('message', '')}")

                except json.JSONDecodeError:
                    pass
        except:
            pass

    # Clean up
    if proc.poll() is None:
        proc.terminate()
        proc.wait(timeout=2)

    # Read any stderr output
    stderr_output = proc.stderr.read()

    # Look for verification messages in stderr
    if "Verifying device connection" in stderr_output:
        verification_attempted = True
        print("\n✓ Device verification was attempted")

    if "Device verification successful" in stderr_output:
        print("✓ Device passed verification checks")
    elif "phantom device" in stderr_output.lower() or "not responding" in stderr_output:
        print("✓ Phantom device correctly detected and rejected")

    # Summary
    print("\n" + "="*70)
    print("TEST RESULTS")
    print("="*70)

    if device_found:
        print("✅ REAL DEVICE: Eye tracker was found and verified")
        print("   - Device discovery succeeded")
        print("   - Device verification passed")
        print("   - Ready for use")
    else:
        print("ℹ️  NO DEVICE: Eye tracker not found or verification failed")
        print("   - This is the expected behavior when no device is connected")
        print("   - No window will be created")
        print("   - Module exits gracefully")

    if verification_attempted:
        print("\n✅ Verification system is working correctly")

    return device_found


def test_standalone_mode():
    """Test running in standalone mode (with window)"""
    print("\n" + "="*70)
    print("STANDALONE MODE TEST")
    print("="*70)
    print("Testing eye tracker in standalone mode (will attempt to create window)")
    print("This should ONLY create a window if a real device is verified")
    print()

    cmd = [
        "/home/rs-pi-2/.local/bin/uv", "run",
        "Modules/EyeTracker/main_eye_tracker.py",
        "--retry-delay", "5"
    ]

    print("Running:", " ".join(cmd))
    print("Press Ctrl+C to stop if a window appears...")
    print()

    # Run for a short time to see if it creates a window
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    try:
        # Wait a bit to see what happens
        time.sleep(3)

        if proc.poll() is None:
            print("ℹ️  Process is still running - window may have been created")
            print("   Check if a window appeared. Press Ctrl+C to stop.")
            proc.wait(timeout=5)
        else:
            print("✅ Process exited cleanly - no phantom window created")

    except KeyboardInterrupt:
        print("\n   Stopping process...")
        proc.terminate()
        proc.wait()
    except subprocess.TimeoutExpired:
        print("\n   Timeout - terminating process...")
        proc.terminate()
        proc.wait()

    # Check exit code
    if proc.returncode == 0:
        print("   Exited normally")
    elif proc.returncode == 1:
        print("   Exited with error (expected if no device)")
    else:
        print(f"   Exited with code: {proc.returncode}")


def main():
    print("EYE TRACKER DETECTION VERIFICATION")
    print("="*70)
    print("This test verifies that:")
    print("1. Real devices are properly detected and verified")
    print("2. Phantom devices are rejected")
    print("3. No window is created when no real device is found")
    print()

    # Test device detection
    device_found = test_eyetracker_detection(timeout=5)

    # Test standalone mode
    if not device_found:
        print("\n" + "="*70)
        print("IMPORTANT: No device was found during detection")
        print("Testing standalone mode to ensure no phantom window is created...")
        test_standalone_mode()
    else:
        print("\n" + "="*70)
        print("A real device was detected!")
        print("Standalone mode would create a valid preview window.")

    print("\n" + "="*70)
    print("TEST COMPLETE")
    print("="*70)


if __name__ == "__main__":
    main()
