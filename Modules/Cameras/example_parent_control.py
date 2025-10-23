
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

    cmd = [
        sys.executable,  # Use same Python interpreter
        "main_camera.py",
        "--mode", "gui",
        "--enable-commands",  # Explicit enable (or omit for auto-detection)
        "--console",  # Show logs in console for debugging
    ]

    print(f"Launching camera module: {' '.join(cmd)}")
    print()

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
        print("Waiting for camera initialization...")
        time.sleep(5)

        print("\n[Parent → Camera] Sending get_status command")
        send_command(process, {"command": "get_status"})

        response = read_response(process)
        if response:
            print(f"[Camera → Parent] Status: {json.dumps(response, indent=2)}")

        print("\n[Parent → Camera] Sending start_recording command")
        send_command(process, {"command": "start_recording"})

        response = read_response(process)
        if response:
            print(f"[Camera → Parent] Response: {json.dumps(response, indent=2)}")

        print("\nRecording for 5 seconds...")
        time.sleep(5)

        print("\n[Parent → Camera] Sending stop_recording command")
        send_command(process, {"command": "stop_recording"})

        response = read_response(process)
        if response:
            print(f"[Camera → Parent] Response: {json.dumps(response, indent=2)}")

        print("\n[Parent → Camera] Sending take_snapshot command")
        send_command(process, {"command": "take_snapshot"})

        response = read_response(process)
        if response:
            print(f"[Camera → Parent] Response: {json.dumps(response, indent=2)}")

        print("\n[Parent → Camera] Sending quit command")
        send_command(process, {"command": "quit"})

        response = read_response(process)
        if response:
            print(f"[Camera → Parent] Response: {json.dumps(response, indent=2)}")

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
    command_json = json.dumps(command_dict) + "\n"
    process.stdin.write(command_json)
    process.stdin.flush()


def read_response(process, timeout=2.0):
    import select

    start_time = time.time()
    while time.time() - start_time < timeout:
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
