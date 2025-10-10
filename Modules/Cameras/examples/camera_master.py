#!/usr/bin/env python3
"""
EXAMPLE: Master program for controlling main_camera.py in slave mode

This is a demonstration/example program showing how to control the camera
system programmatically. It demonstrates subprocess communication via stdin/stdout
with JSON commands.

Usage:
    uv run examples/camera_master.py              # Demo session
    uv run examples/camera_master.py interactive  # Interactive session
"""

import subprocess
import json
import time
import threading
import signal
import sys
from queue import Queue, Empty


class CameraMaster:
    def __init__(self):
        self.camera_proc = None
        self.running = False
        self.status_queue = Queue()
        self.response_queue = Queue()

        # Setup signal handlers
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        print(f"\nReceived signal {signum}, shutting down...")
        self.shutdown()
        sys.exit(0)

    def start_camera_system(self, **camera_args):
        """Start the camera system as a subprocess"""
        cmd = ["uv", "run", "../main_camera.py", "--mode", "slave"]

        # Add camera arguments
        for key, value in camera_args.items():
            cmd.extend([f"--{key.replace('_', '-')}", str(value)])

        print(f"Starting camera system: {' '.join(cmd)}")

        self.camera_proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1  # Line buffered
        )

        self.running = True

        # Start output reader thread
        self.output_thread = threading.Thread(target=self._read_output, daemon=True)
        self.output_thread.start()

        return True

    def _read_output(self):
        """Read output from camera subprocess"""
        while self.running and self.camera_proc and self.camera_proc.poll() is None:
            try:
                line = self.camera_proc.stdout.readline()
                if line:
                    try:
                        message = json.loads(line.strip())
                        self.status_queue.put(message)
                    except json.JSONDecodeError:
                        print(f"Invalid JSON from camera: {line.strip()}")
            except Exception as e:
                print(f"Error reading camera output: {e}")
                break

    def send_command(self, command, **params):
        """Send command to camera system"""
        if not self.camera_proc or self.camera_proc.poll() is not None:
            return {"error": "Camera system not running"}

        cmd_data = {"command": command, **params}
        try:
            self.camera_proc.stdin.write(json.dumps(cmd_data) + "\n")
            self.camera_proc.stdin.flush()
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    def get_status_messages(self, timeout=0.1):
        """Get all pending status messages"""
        messages = []
        while True:
            try:
                message = self.status_queue.get(timeout=timeout)
                messages.append(message)
            except Empty:
                break
        return messages

    def wait_for_status(self, status_type, timeout=5.0):
        """Wait for specific status message"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                message = self.status_queue.get(timeout=0.1)
                if message.get("status") == status_type:
                    return message
                # Put it back if it's not what we're looking for
                self.status_queue.put(message)
            except Empty:
                continue
        return None

    def shutdown(self):
        """Shutdown camera system gracefully"""
        self.running = False

        if self.camera_proc and self.camera_proc.poll() is None:
            print("Sending quit command to camera system...")
            self.send_command("quit")

            # Wait for graceful shutdown
            try:
                self.camera_proc.wait(timeout=5.0)
                print("Camera system shut down gracefully")
            except subprocess.TimeoutExpired:
                print("Camera system didn't respond, terminating...")
                self.camera_proc.terminate()
                try:
                    self.camera_proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    print("Force killing camera system...")
                    self.camera_proc.kill()

    def is_running(self):
        """Check if camera system is still running"""
        return self.camera_proc and self.camera_proc.poll() is None


def demo_session():
    """Demonstrate camera control"""
    master = CameraMaster()

    try:
        # Start camera system with custom settings
        print("=== Starting Camera System ===")
        master.start_camera_system(
            width=1280,
            height=720,
            fps=25,
            output="master_recordings"
        )

        # Wait for initialization
        print("Waiting for camera initialization...")
        init_msg = master.wait_for_status("initialized", timeout=10.0)
        if init_msg:
            print(f"✓ Camera system initialized: {init_msg['data']}")
        else:
            print("✗ Camera initialization timeout")
            return

        # Get initial status
        print("\n=== Getting Status ===")
        master.send_command("get_status")
        status_msg = master.wait_for_status("status_report", timeout=2.0)
        if status_msg:
            print(f"Status: {json.dumps(status_msg['data'], indent=2)}")

        # Start recording
        print("\n=== Starting Recording ===")
        master.send_command("start_recording")
        record_msg = master.wait_for_status("recording_started", timeout=2.0)
        if record_msg:
            print("✓ Recording started")

        # Let it record for a few seconds
        print("Recording for 5 seconds...")
        time.sleep(5)

        # Take a snapshot
        print("\n=== Taking Snapshot ===")
        master.send_command("take_snapshot")
        snapshot_msg = master.wait_for_status("snapshot_taken", timeout=2.0)
        if snapshot_msg:
            print(f"✓ Snapshot saved: {snapshot_msg['data']['files']}")

        # Stop recording
        print("\n=== Stopping Recording ===")
        master.send_command("stop_recording")
        stop_msg = master.wait_for_status("recording_stopped", timeout=2.0)
        if stop_msg:
            print("✓ Recording stopped")

        # Get final status
        print("\n=== Final Status ===")
        master.send_command("get_status")
        final_status = master.wait_for_status("status_report", timeout=2.0)
        if final_status:
            print(f"Final status: {json.dumps(final_status['data'], indent=2)}")

        # Show any other messages
        other_messages = master.get_status_messages()
        if other_messages:
            print(f"\nOther messages: {len(other_messages)}")
            for msg in other_messages:
                print(f"  {msg['status']}: {msg.get('data', {})}")

    except KeyboardInterrupt:
        print("\nDemo interrupted by user")

    finally:
        print("\n=== Shutting Down ===")
        master.shutdown()


def interactive_session():
    """Interactive command session"""
    master = CameraMaster()

    try:
        print("=== Interactive Camera Master ===")
        print("Starting camera system...")

        master.start_camera_system()

        # Wait for initialization
        init_msg = master.wait_for_status("initialized", timeout=10.0)
        if not init_msg:
            print("Failed to initialize camera system")
            return

        print("Camera system ready!")
        print("\nCommands: start, stop, snapshot, status, quit")

        while master.is_running():
            try:
                cmd = input("\n> ").strip().lower()

                if cmd == "quit":
                    break
                elif cmd == "start":
                    master.send_command("start_recording")
                elif cmd == "stop":
                    master.send_command("stop_recording")
                elif cmd == "snapshot":
                    master.send_command("take_snapshot")
                elif cmd == "status":
                    master.send_command("get_status")
                elif cmd == "":
                    continue
                else:
                    print(f"Unknown command: {cmd}")
                    continue

                # Show response
                time.sleep(0.1)  # Brief wait for response
                messages = master.get_status_messages()
                for msg in messages:
                    print(f"  {msg['status']}: {msg.get('data', {})}")

            except KeyboardInterrupt:
                break
            except EOFError:
                break

    finally:
        master.shutdown()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "interactive":
        interactive_session()
    else:
        demo_session()
