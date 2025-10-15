#!/usr/bin/env python3
"""
Example parent process that controls the camera module.

Demonstrates how a parent logger/controller can:
1. Launch the camera module as a child process
2. Send commands via stdin
3. Receive status updates via stdout
4. Gracefully shutdown

Usage:
    python example_parent_control.py
"""

import json
import subprocess
import sys
import time
from pathlib import Path


def main():
    print("=" * 60)
    print("PARENT PROCESS - Camera Module Controller")
    print("=" * 60)
    print()

    # Launch camera module in GUI mode with command support
    # Note: --enable-commands enables JSON command interface
    # Or let it auto-detect by using stdin pipe (which we do here)
    cmd = [
        sys.executable,  # Use same Python interpreter
        "main_camera.py",
        "--mode", "gui",
        "--enable-commands",  # Explicit enable (or omit for auto-detection)
        "--console",  # Show logs in console for debugging
    ]

    print(f"Launching camera module: {' '.join(cmd)}")
    print()

    # Start camera process with stdin/stdout pipes
    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,  # Line buffered
    )

    print(f"Camera module started (PID: {process.pid})")
    print()

    try:
        # Give it time to initialize cameras
        print("Waiting for camera initialization...")
        time.sleep(5)

        # Send command: Get status
        print("\n[Parent → Camera] Sending get_status command")
        send_command(process, {"command": "get_status"})

        # Read response
        response = read_response(process)
        if response:
            print(f"[Camera → Parent] Status: {json.dumps(response, indent=2)}")

        # Send command: Start recording
        print("\n[Parent → Camera] Sending start_recording command")
        send_command(process, {"command": "start_recording"})

        # Read response
        response = read_response(process)
        if response:
            print(f"[Camera → Parent] Response: {json.dumps(response, indent=2)}")

        # Let it record for 5 seconds
        print("\nRecording for 5 seconds...")
        time.sleep(5)

        # Send command: Stop recording
        print("\n[Parent → Camera] Sending stop_recording command")
        send_command(process, {"command": "stop_recording"})

        # Read response
        response = read_response(process)
        if response:
            print(f"[Camera → Parent] Response: {json.dumps(response, indent=2)}")

        # Send command: Take snapshot
        print("\n[Parent → Camera] Sending take_snapshot command")
        send_command(process, {"command": "take_snapshot"})

        # Read response
        response = read_response(process)
        if response:
            print(f"[Camera → Parent] Response: {json.dumps(response, indent=2)}")

        # Send command: Quit
        print("\n[Parent → Camera] Sending quit command")
        send_command(process, {"command": "quit"})

        # Read response
        response = read_response(process)
        if response:
            print(f"[Camera → Parent] Response: {json.dumps(response, indent=2)}")

        # Wait for process to exit
        print("\nWaiting for camera module to shutdown...")
        process.wait(timeout=10)

    except KeyboardInterrupt:
        print("\n\nParent interrupted, shutting down camera module...")
        send_command(process, {"command": "quit"})
        process.wait(timeout=5)

    except Exception as e:
        print(f"\nError: {e}")
        process.terminate()
        process.wait(timeout=5)

    finally:
        if process.poll() is None:
            print("Force killing camera module...")
            process.kill()

    print("\n" + "=" * 60)
    print("Parent process finished")
    print("=" * 60)


def send_command(process, command_dict):
    """Send JSON command to camera module."""
    command_json = json.dumps(command_dict) + "\n"
    process.stdin.write(command_json)
    process.stdin.flush()


def read_response(process, timeout=2.0):
    """Read JSON response from camera module."""
    import select

    # Use select to read with timeout
    start_time = time.time()
    while time.time() - start_time < timeout:
        # Check if data available
        ready, _, _ = select.select([process.stdout], [], [], 0.1)
        if ready:
            line = process.stdout.readline().strip()
            if line:
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    print(f"[Warning] Invalid JSON: {line}")
                    continue
    return None


if __name__ == "__main__":
    main()
