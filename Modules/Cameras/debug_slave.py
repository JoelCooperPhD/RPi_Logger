#!/usr/bin/env python3
"""
Debug script to test slave mode communication directly
"""

import subprocess
import json
import time

def debug_slave_communication():
    """Test slave mode communication step by step"""

    print("=== DEBUG: Slave Mode Communication ===")

    cmd = ["uv", "run", "dual_camera_module.py", "--slave", "--output", "debug_output"]

    print(f"Starting: {' '.join(cmd)}")

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )

    print("Waiting for output...")

    # Read with timeout
    start_time = time.time()
    timeout = 10.0

    while time.time() - start_time < timeout:
        if proc.poll() is not None:
            print(f"Process exited with code: {proc.returncode}")
            break

        # Check if stdout has data
        try:
            # Use select-like behavior with timeout
            import select
            ready, _, _ = select.select([proc.stdout], [], [], 0.1)
            if ready:
                line = proc.stdout.readline()
                if line:
                    print(f"STDOUT: {line.strip()}")
                    try:
                        message = json.loads(line.strip())
                        print(f"JSON: {message}")
                        if message.get("status") == "initialized":
                            print("✓ Initialization message received!")

                            # Send quit command
                            quit_cmd = {"command": "quit"}
                            proc.stdin.write(json.dumps(quit_cmd) + "\n")
                            proc.stdin.flush()
                            print(f"Sent: {quit_cmd}")
                            break
                    except json.JSONDecodeError as e:
                        print(f"JSON decode error: {e}")
        except Exception as e:
            print(f"Error reading: {e}")

        time.sleep(0.1)

    # Wait for process to finish
    try:
        proc.wait(timeout=3.0)
        print("Process finished normally")
    except subprocess.TimeoutExpired:
        print("Process timeout, terminating...")
        proc.terminate()

    # Read any remaining output
    stdout, stderr = proc.communicate(timeout=2.0)
    if stdout:
        print(f"Remaining stdout: {stdout}")
    if stderr:
        print(f"Stderr: {stderr}")


if __name__ == "__main__":
    debug_slave_communication()