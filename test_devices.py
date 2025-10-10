#!/usr/bin/env python3
"""
Test script to verify graceful device detection and timeout handling
"""

import subprocess
import time
import sys
import json

def test_module(name, module_path, timeout=5):
    """Test a single module's device detection"""
    print(f"\n{'='*50}")
    print(f"Testing {name} module (timeout: {timeout}s)")
    print(f"{'='*50}")

    cmd = ["/home/rs-pi-2/.local/bin/uv", "run", module_path]

    if "Camera" in name:
        cmd.extend([
            "--mode",
            "slave",
            "--discovery-timeout",
            str(timeout),
            "--discovery-retry",
            str(max(1, timeout // 2 or 1)),
            "--log-level",
            "warning",
        ])
    else:
        cmd.extend([
            "--retry-delay",
            str(timeout),
            "--reconnect-interval",
            str(timeout),
            "--log-level",
            "warning",
        ])

    print(f"Command: {' '.join(cmd)}")
    print("Starting module...")

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )

    # Send a test command and watch for responses
    start_time = time.time()
    device_found = False
    error_occurred = False

    while time.time() - start_time < timeout + 5:  # Give extra time for module to exit
        # Check if process has exited
        if proc.poll() is not None:
            print(f"Module exited with code: {proc.returncode}")
            break

        # Try to read output
        try:
            line = proc.stdout.readline()
            if line:
                try:
                    msg = json.loads(line.strip())
                    status = msg.get("status")
                    data = msg.get("data", {})

                    print(f"  Status: {status}")
                    if data:
                        print(f"    Data: {data}")

                    if status == "initialized":
                        device_found = True
                        print("  ✓ Device found and initialized!")
                    elif status == "device_not_found":
                        print("  ℹ No device found (graceful exit)")
                    elif status == "error":
                        error_occurred = True
                        print(f"  ✗ Error: {data.get('message', 'Unknown')}")
                    elif status == "searching":
                        print(f"  🔍 Searching for device...")

                except json.JSONDecodeError:
                    print(f"  Raw output: {line.strip()}")
        except:
            pass

    # Cleanup
    if proc.poll() is None:
        print("Sending quit command...")
        try:
            proc.stdin.write(json.dumps({"command": "quit"}) + "\n")
            proc.stdin.flush()
            proc.wait(timeout=2)
        except:
            proc.terminate()
            proc.wait()

    # Read any stderr
    stderr_output = proc.stderr.read()
    if stderr_output and "ERROR" in stderr_output:
        print("Errors from stderr:")
        for line in stderr_output.split('\n'):
            if line.strip():
                print(f"  {line}")

    return device_found, error_occurred


def main():
    print("DEVICE DETECTION TEST")
    print("=" * 70)
    print("This will test device detection and graceful timeout handling")
    print("for both camera and eye tracker modules.")
    print()

    modules = [
        ("Camera", "Modules/Cameras/main_camera.py", 3),
        ("Eye Tracker", "Modules/EyeTracker/main_eye_tracker.py", 5)
    ]

    results = []

    for name, path, timeout in modules:
        device_found, error = test_module(name, path, timeout)
        results.append((name, device_found, error))
        time.sleep(1)  # Brief pause between tests

    # Summary
    print(f"\n{'='*70}")
    print("TEST SUMMARY")
    print(f"{'='*70}")

    for name, found, error in results:
        if found:
            print(f"✓ {name}: Device found and initialized")
        elif error:
            print(f"✗ {name}: Error during initialization")
        else:
            print(f"ℹ {name}: No device found (graceful exit)")

    print("\nTest complete!")


if __name__ == "__main__":
    main()
