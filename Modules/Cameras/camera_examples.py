#!/usr/bin/env python3
"""
Camera Module Usage Examples

This file demonstrates various ways to use the camera module for different scenarios.
Run individual functions to test specific functionality.

Examples included:
- Basic recording with preview
- Headless recording
- Time-lapse photography
- Motion detection setup
- IPC control integration
- Custom recording configurations

Usage:
    python camera_examples.py
"""

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

# Add module to path
sys.path.insert(0, Path(__file__).parent)

from camera_module import CameraModule


async def example_basic_recording():
    """Example 1: Basic recording with preview (default behavior)."""
    print("=" * 50)
    print("Example 1: Basic Recording with Preview")
    print("=" * 50)
    print("This will start recording with a live preview window.")
    print("Press 'q' in the preview window to stop, or 's' to take snapshots.")

    camera = CameraModule(
        resolution=(1920, 1080),
        fps=30,
        save_location="./examples_output"
    )

    try:
        await camera.initialize_camera()
        await camera.start_camera()

        # Start recording
        recording_path = await camera.start_recording("basic_example.h264")
        print(f"Recording started: {recording_path}")

        # Run for 10 seconds or until user quits
        await camera.run_preview_loop(duration=10)

        await camera.stop_recording()
        print("Recording completed!")

    finally:
        await camera.cleanup()


async def example_headless_recording():
    """Example 2: Headless recording (no preview window)."""
    print("=" * 50)
    print("Example 2: Headless Recording")
    print("=" * 50)
    print("This will record video without showing a preview window.")

    camera = CameraModule(
        resolution=(1280, 720),
        fps=30,
        save_location="./examples_output",
        show_preview=False
    )

    try:
        await camera.initialize_camera()
        await camera.start_camera()

        # Start recording
        recording_path = await camera.start_recording("headless_example.h264")
        print(f"Recording started: {recording_path}")

        # Record for 5 seconds
        print("Recording for 5 seconds...")
        await asyncio.sleep(5)

        await camera.stop_recording()
        print("Headless recording completed!")

    finally:
        await camera.cleanup()


async def example_timelapse():
    """Example 3: Time-lapse photography."""
    print("=" * 50)
    print("Example 3: Time-lapse Photography")
    print("=" * 50)
    print("Taking photos every 2 seconds for 10 seconds (5 photos total).")

    camera = CameraModule(
        resolution=(1920, 1080),
        save_location="./examples_output",
        show_preview=False
    )

    try:
        await camera.initialize_camera()
        await camera.start_camera()

        # Take photos at intervals
        for i in range(5):
            print(f"Taking photo {i+1}/5...")
            image_path = await camera.capture_image(f"timelapse_{i:03d}.jpg")
            print(f"Saved: {image_path}")

            if i < 4:  # Don't wait after the last photo
                await asyncio.sleep(2)

        print("Time-lapse completed!")

    finally:
        await camera.cleanup()


async def example_high_quality_recording():
    """Example 4: High quality 4K recording."""
    print("=" * 50)
    print("Example 4: High Quality 4K Recording")
    print("=" * 50)
    print("Recording in 4K resolution at 24fps (cinematic quality).")

    camera = CameraModule(
        resolution=(3840, 2160),  # 4K
        fps=24,                   # Cinematic frame rate
        save_location="./examples_output",
        show_preview=True  # Preview will be downscaled for performance
    )

    try:
        await camera.initialize_camera()
        await camera.start_camera()

        recording_path = await camera.start_recording("4k_example.h264")
        print(f"4K recording started: {recording_path}")
        print("Recording for 8 seconds...")

        # Run with preview for 8 seconds
        await camera.run_preview_loop(duration=8)

        await camera.stop_recording()
        print("4K recording completed!")

    finally:
        await camera.cleanup()


def example_ipc_control():
    """Example 5: IPC control (subprocess communication)."""
    print("=" * 50)
    print("Example 5: IPC Control")
    print("=" * 50)
    print("Controlling camera via IPC commands (useful for integration).")

    # Start camera in IPC mode
    proc = subprocess.Popen([
        sys.executable, "camera_module.py",
        "--ipc",
        "--save-location", "./examples_output"
    ], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
       stderr=subprocess.PIPE, text=True)

    try:
        # Send commands
        commands = [
            {"action": "get_status"},
            {"action": "start_recording", "params": {"filename": "ipc_example.h264"}},
            {"action": "capture_image", "params": {"filename": "ipc_snapshot.jpg"}},
            {"action": "stop_recording"},
            {"action": "shutdown"}
        ]

        for cmd in commands:
            print(f"Sending command: {cmd['action']}")
            proc.stdin.write(json.dumps(cmd) + '\n')
            proc.stdin.flush()

            # Read response
            response_line = proc.stdout.readline()
            if response_line:
                response = json.loads(response_line.strip())
                print(f"Response: {response}")

            time.sleep(1)  # Small delay between commands

        # Wait for process to finish
        proc.wait(timeout=10)
        print("IPC control example completed!")

    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        print("IPC process timed out and was terminated.")
    except Exception as e:
        proc.kill()
        proc.wait()
        print(f"IPC example error: {e}")


async def example_motion_detection_setup():
    """Example 6: Motion detection setup (framework for custom processing)."""
    print("=" * 50)
    print("Example 6: Motion Detection Setup")
    print("=" * 50)
    print("Setting up framework for motion detection (capture frames for analysis).")

    camera = CameraModule(
        resolution=(640, 480),  # Lower resolution for faster processing
        fps=15,                 # Lower FPS for motion detection
        save_location="./examples_output",
        show_preview=True
    )

    try:
        await camera.initialize_camera()
        await camera.start_camera()

        print("Capturing frames for motion detection analysis...")
        print("In a real application, you would analyze these frames for motion.")

        frame_count = 0
        start_time = asyncio.get_event_loop().time()

        while frame_count < 50:  # Capture 50 frames
            try:
                # Capture frame for analysis
                frame = camera.picam2.capture_array("main")
                frame_count += 1

                # In a real application, you would:
                # 1. Compare with previous frame
                # 2. Detect motion using cv2.absdiff() or similar
                # 3. Start recording if motion detected
                # 4. Save motion events

                if frame_count % 10 == 0:
                    print(f"Processed {frame_count} frames...")

                await asyncio.sleep(0.1)  # Process 10 FPS

            except Exception as e:
                print(f"Frame processing error: {e}")
                break

        elapsed = asyncio.get_event_loop().time() - start_time
        print(f"Motion detection setup completed! Processed {frame_count} frames in {elapsed:.1f}s")

    finally:
        await camera.cleanup()


async def run_all_examples():
    """Run all examples in sequence."""
    print("Running all camera module examples...")
    print("Make sure you have sufficient disk space and camera is connected.")

    # Create output directory
    Path("./examples_output").mkdir(exist_ok=True)

    examples = [
        ("Basic Recording", example_basic_recording),
        ("Headless Recording", example_headless_recording),
        ("Time-lapse", example_timelapse),
        ("High Quality 4K", example_high_quality_recording),
        ("Motion Detection Setup", example_motion_detection_setup),
    ]

    for name, func in examples:
        try:
            print(f"\n🎥 Starting: {name}")
            await func()
            print(f"✅ Completed: {name}")
        except KeyboardInterrupt:
            print(f"\n⏹️  User interrupted: {name}")
            break
        except Exception as e:
            print(f"❌ Error in {name}: {e}")

        print("\nPress Enter to continue to next example (or Ctrl+C to quit)...")
        try:
            input()
        except KeyboardInterrupt:
            print("\nExiting examples...")
            break

    # Run IPC example separately (doesn't use async)
    print("\n🎥 Starting: IPC Control")
    try:
        example_ipc_control()
        print("✅ Completed: IPC Control")
    except Exception as e:
        print(f"❌ Error in IPC Control: {e}")


def main():
    """Main entry point for examples."""
    print("Camera Module Examples")
    print("=" * 60)
    print("Choose an example to run:")
    print("1. Basic Recording with Preview")
    print("2. Headless Recording")
    print("3. Time-lapse Photography")
    print("4. High Quality 4K Recording")
    print("5. IPC Control")
    print("6. Motion Detection Setup")
    print("7. Run All Examples")
    print("0. Exit")

    while True:
        try:
            choice = input("\nEnter your choice (0-7): ").strip()

            if choice == "0":
                print("Goodbye!")
                break
            elif choice == "1":
                asyncio.run(example_basic_recording())
            elif choice == "2":
                asyncio.run(example_headless_recording())
            elif choice == "3":
                asyncio.run(example_timelapse())
            elif choice == "4":
                asyncio.run(example_high_quality_recording())
            elif choice == "5":
                example_ipc_control()
            elif choice == "6":
                asyncio.run(example_motion_detection_setup())
            elif choice == "7":
                asyncio.run(run_all_examples())
            else:
                print("Invalid choice. Please enter 0-7.")

        except KeyboardInterrupt:
            print("\n\nExiting...")
            break
        except Exception as e:
            print(f"Error running example: {e}")


if __name__ == "__main__":
    main()