#!/usr/bin/env python3
"""
Test script demonstrating how to use camera_module.py as a subprocess with IPC.
This shows how a parent process would communicate with the camera module.
"""

import asyncio
import json
import subprocess
import sys
from pathlib import Path


class CameraIPCController:
    """Controller for camera module running as subprocess."""

    def __init__(self, resolution="1920x1080", fps=30, save_location="./recordings"):
        self.resolution = resolution
        self.fps = fps
        self.save_location = save_location
        self.process = None
        self.reader = None
        self.writer = None

    async def start(self):
        """Start the camera module subprocess."""
        cmd = [
            sys.executable,
            "camera_module.py",
            "--resolution", self.resolution,
            "--fps", str(self.fps),
            "--save-location", self.save_location,
            "--ipc"  # Enable IPC mode
        ]

        # Start subprocess
        self.process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        print(f"Started camera subprocess (PID: {self.process.pid})")

    async def send_command(self, action, params=None):
        """
        Send command to camera module and get response.

        Args:
            action: Command action string
            params: Optional parameters dictionary

        Returns:
            Response dictionary from camera module
        """
        if not self.process:
            raise RuntimeError("Camera subprocess not started")

        command = {"action": action}
        if params:
            command["params"] = params

        # Send command
        command_json = json.dumps(command) + '\n'
        self.process.stdin.write(command_json.encode())
        await self.process.stdin.drain()

        # Read response
        response_line = await self.process.stdout.readline()
        if response_line:
            return json.loads(response_line.decode())
        return None

    async def stop(self):
        """Stop the camera module subprocess."""
        if self.process:
            # Send shutdown command
            await self.send_command("shutdown")

            # Wait for process to exit
            await self.process.wait()
            print(f"Camera subprocess stopped")


async def main():
    """Demo of using camera module via IPC."""
    print("Camera IPC Test - Parent Process")
    print("-" * 40)

    # Create controller
    controller = CameraIPCController(
        resolution="1920x1080",
        fps=30,
        save_location="./test_recordings"
    )

    try:
        # Start camera subprocess
        await controller.start()
        await asyncio.sleep(2)  # Let camera initialize

        # Get status
        print("\n1. Getting camera status...")
        response = await controller.send_command("get_status")
        if response['status'] == 'success':
            print(f"   Camera status: {response['data']}")

        # Start recording
        print("\n2. Starting recording...")
        response = await controller.send_command("start_recording", {"filename": "test_ipc.h264"})
        if response['status'] == 'success':
            print(f"   Recording to: {response['data']['path']}")

        # Record for 5 seconds
        print("\n3. Recording for 5 seconds...")
        await asyncio.sleep(5)

        # Capture an image while recording
        print("\n4. Capturing still image...")
        response = await controller.send_command("capture_image", {"filename": "test_capture.jpg"})
        if response['status'] == 'success':
            print(f"   Image saved to: {response['data']['path']}")

        # Adjust camera controls
        print("\n5. Adjusting camera controls...")
        response = await controller.send_command("set_controls", {
            "Brightness": 0.1,
            "Contrast": 1.2
        })
        if response['status'] == 'success':
            print("   Controls updated")

        # Continue recording for 3 more seconds
        await asyncio.sleep(3)

        # Stop recording
        print("\n6. Stopping recording...")
        response = await controller.send_command("stop_recording")
        if response['status'] == 'success':
            print("   Recording stopped")

        # Final status check
        print("\n7. Final status check...")
        response = await controller.send_command("get_status")
        if response['status'] == 'success':
            print(f"   Final status: {response['data']}")

    except Exception as e:
        print(f"\nError: {e}")

    finally:
        # Stop camera subprocess
        print("\n8. Shutting down camera...")
        await controller.stop()
        print("\nTest completed!")


if __name__ == "__main__":
    asyncio.run(main())