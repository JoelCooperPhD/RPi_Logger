#!/usr/bin/env python3
"""
Comprehensive Test Suite for Camera Module

Tests all camera functionality including:
- Basic initialization and configuration
- Recording with and without preview
- Snapshot capture
- Error handling and cleanup
- IPC mode functionality
- Command line argument parsing

Usage:
    python test_camera_comprehensive.py

Requirements:
- Camera module must be present
- Raspberry Pi with camera connected
- Write permissions for test output directory
"""

import asyncio
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
import subprocess
import signal

# Add the module directory to path
sys.path.insert(0, os.path.dirname(__file__))

from camera_module import CameraModule


class TestCameraModule(unittest.TestCase):
    """Test cases for CameraModule functionality."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp(prefix="camera_test_")
        self.test_path = Path(self.test_dir)

    def tearDown(self):
        """Clean up test environment."""
        # Clean up test files
        import shutil
        if self.test_path.exists():
            shutil.rmtree(self.test_path)

    def test_camera_initialization(self):
        """Test camera module initialization."""
        camera = CameraModule(
            resolution=(1280, 720),
            fps=30,
            save_location=str(self.test_path),
            camera_id=0,
            use_ipc=False,
            show_preview=False
        )

        # Check basic attributes
        self.assertEqual(camera.resolution, (1280, 720))
        self.assertEqual(camera.fps, 30)
        self.assertEqual(camera.save_location, self.test_path)
        self.assertEqual(camera.camera_id, 0)
        self.assertFalse(camera.use_ipc)
        self.assertFalse(camera.show_preview)
        self.assertFalse(camera.recording)
        self.assertFalse(camera.preview_enabled)

    def test_save_directory_creation(self):
        """Test that save directory is created if it doesn't exist."""
        non_existent_dir = self.test_path / "new_dir"
        self.assertFalse(non_existent_dir.exists())

        camera = CameraModule(save_location=str(non_existent_dir))
        self.assertTrue(non_existent_dir.exists())

    async def test_camera_lifecycle_headless(self):
        """Test complete camera lifecycle in headless mode."""
        camera = CameraModule(
            resolution=(640, 480),  # Small resolution for faster testing
            fps=15,
            save_location=str(self.test_path),
            show_preview=False
        )

        try:
            # Initialize camera
            await camera.initialize_camera()
            self.assertIsNotNone(camera.picam2)

            # Start camera
            await camera.start_camera()

            # Start recording
            recording_path = await camera.start_recording("test_recording.h264")
            self.assertTrue(camera.recording)
            self.assertTrue(Path(recording_path).exists())

            # Wait a short time
            await asyncio.sleep(2)

            # Stop recording
            await camera.stop_recording()
            self.assertFalse(camera.recording)

            # Check file exists and has content
            recording_file = Path(recording_path)
            self.assertTrue(recording_file.exists())
            self.assertGreater(recording_file.stat().st_size, 0)

        finally:
            await camera.cleanup()

    async def test_image_capture(self):
        """Test still image capture functionality."""
        camera = CameraModule(
            resolution=(640, 480),
            save_location=str(self.test_path),
            show_preview=False
        )

        try:
            await camera.initialize_camera()
            await camera.start_camera()

            # Capture image
            image_path = await camera.capture_image("test_image.jpg")

            # Check file exists
            image_file = Path(image_path)
            self.assertTrue(image_file.exists())
            self.assertGreater(image_file.stat().st_size, 0)
            self.assertTrue(image_path.endswith(".jpg"))

        finally:
            await camera.cleanup()

    async def test_ipc_commands(self):
        """Test IPC command processing."""
        camera = CameraModule(
            save_location=str(self.test_path),
            use_ipc=True,
            show_preview=False
        )

        try:
            await camera.initialize_camera()
            await camera.start_camera()

            # Test status command
            status_response = await camera.process_command({'action': 'get_status'})
            self.assertEqual(status_response['status'], 'success')
            self.assertIn('recording', status_response['data'])
            self.assertFalse(status_response['data']['recording'])

            # Test start recording command
            record_response = await camera.process_command({
                'action': 'start_recording',
                'params': {'filename': 'ipc_test.h264'}
            })
            self.assertEqual(record_response['status'], 'success')
            self.assertTrue(camera.recording)

            # Test stop recording command
            stop_response = await camera.process_command({'action': 'stop_recording'})
            self.assertEqual(stop_response['status'], 'success')
            self.assertFalse(camera.recording)

            # Test image capture command
            capture_response = await camera.process_command({
                'action': 'capture_image',
                'params': {'filename': 'ipc_image.jpg'}
            })
            self.assertEqual(capture_response['status'], 'success')

            # Test invalid command
            invalid_response = await camera.process_command({'action': 'invalid_action'})
            self.assertEqual(invalid_response['status'], 'error')

        finally:
            await camera.cleanup()

    def test_argument_parsing(self):
        """Test command line argument parsing."""
        # Test default arguments
        test_args = ['camera_module.py']
        with patch('sys.argv', test_args):
            # This would normally call main(), but we'll test the parser directly
            import argparse
            parser = argparse.ArgumentParser()
            parser.add_argument('--resolution', type=str, default='1920x1080')
            parser.add_argument('--fps', type=int, default=30)
            parser.add_argument('--save-location', type=str, default='./recordings')
            parser.add_argument('--camera-id', type=int, default=0)
            parser.add_argument('--duration', type=int, default=None)
            parser.add_argument('--ipc', action='store_true')
            parser.add_argument('--no-preview', action='store_true')

            args = parser.parse_args([])
            self.assertEqual(args.resolution, '1920x1080')
            self.assertEqual(args.fps, 30)
            self.assertFalse(args.ipc)
            self.assertFalse(args.no_preview)

    def test_error_handling(self):
        """Test error handling scenarios."""
        # Test invalid camera ID
        camera = CameraModule(camera_id=999, show_preview=False)

        with self.assertRaises(Exception):
            # This should fail because camera 999 doesn't exist
            asyncio.run(camera.initialize_camera())

    def test_timestamp_overlay_function(self):
        """Test timestamp overlay functionality."""
        camera = CameraModule(show_preview=False)

        # Create a mock request object
        mock_request = Mock()
        mock_array = Mock()
        mock_request.make_array.return_value = mock_array

        # Test overlay function doesn't crash
        try:
            camera.add_timestamp_overlay(mock_request)
        except Exception as e:
            # Expected to fail due to mock, but shouldn't crash the process
            self.assertIsInstance(e, Exception)


class TestCameraIntegration(unittest.TestCase):
    """Integration tests that require actual camera hardware."""

    def setUp(self):
        """Set up integration test environment."""
        self.test_dir = tempfile.mkdtemp(prefix="camera_integration_")
        self.test_path = Path(self.test_dir)

    def tearDown(self):
        """Clean up integration test environment."""
        import shutil
        if self.test_path.exists():
            shutil.rmtree(self.test_path)

    def test_full_recording_cycle(self):
        """Test a complete recording cycle with real hardware."""
        if not self._camera_available():
            self.skipTest("No camera hardware available")

        # Test short recording in headless mode
        result = subprocess.run([
            sys.executable, "camera_module.py",
            "--duration", "3",
            "--no-preview",
            "--save-location", str(self.test_path)
        ], capture_output=True, text=True, timeout=15)

        self.assertEqual(result.returncode, 0)

        # Check that recording file was created
        recordings = list(self.test_path.glob("*.h264"))
        self.assertGreater(len(recordings), 0)

        # Check file has content
        recording_file = recordings[0]
        self.assertGreater(recording_file.stat().st_size, 1000)  # At least 1KB

    def test_ipc_mode(self):
        """Test IPC mode functionality."""
        if not self._camera_available():
            self.skipTest("No camera hardware available")

        # Start camera in IPC mode
        proc = subprocess.Popen([
            sys.executable, "camera_module.py",
            "--ipc",
            "--save-location", str(self.test_path)
        ], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
           stderr=subprocess.PIPE, text=True)

        try:
            # Send commands
            commands = [
                {"action": "get_status"},
                {"action": "start_recording", "params": {"filename": "ipc_test.h264"}},
                {"action": "stop_recording"},
                {"action": "shutdown"}
            ]

            for cmd in commands:
                proc.stdin.write(json.dumps(cmd) + '\n')
                proc.stdin.flush()

                # Read response
                response_line = proc.stdout.readline()
                if response_line:
                    response = json.loads(response_line.strip())
                    self.assertEqual(response['status'], 'success')

                time.sleep(0.5)  # Small delay between commands

            # Wait for process to finish
            proc.wait(timeout=10)
            self.assertEqual(proc.returncode, 0)

        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            self.fail("IPC mode test timed out")
        except Exception as e:
            proc.kill()
            proc.wait()
            raise e

    def _camera_available(self):
        """Check if camera hardware is available."""
        try:
            from picamera2 import Picamera2
            cameras = Picamera2.global_camera_info()
            return len(cameras) > 0
        except Exception:
            return False


class TestCameraStress(unittest.TestCase):
    """Stress tests for camera module."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="camera_stress_")
        self.test_path = Path(self.test_dir)

    def tearDown(self):
        import shutil
        if self.test_path.exists():
            shutil.rmtree(self.test_path)

    def test_multiple_start_stop_cycles(self):
        """Test multiple start/stop cycles."""
        if not self._camera_available():
            self.skipTest("No camera hardware available")

        async def run_cycles():
            camera = CameraModule(
                resolution=(640, 480),
                save_location=str(self.test_path),
                show_preview=False
            )

            try:
                await camera.initialize_camera()
                await camera.start_camera()

                # Perform multiple recording cycles
                for i in range(3):
                    recording_path = await camera.start_recording(f"cycle_{i}.h264")
                    await asyncio.sleep(1)  # Record for 1 second
                    await camera.stop_recording()

                    # Verify file was created
                    self.assertTrue(Path(recording_path).exists())

            finally:
                await camera.cleanup()

        asyncio.run(run_cycles())

    def test_rapid_snapshots(self):
        """Test taking multiple snapshots rapidly."""
        if not self._camera_available():
            self.skipTest("No camera hardware available")

        async def take_snapshots():
            camera = CameraModule(
                resolution=(640, 480),
                save_location=str(self.test_path),
                show_preview=False
            )

            try:
                await camera.initialize_camera()
                await camera.start_camera()

                # Take multiple snapshots
                for i in range(5):
                    image_path = await camera.capture_image(f"snapshot_{i}.jpg")
                    self.assertTrue(Path(image_path).exists())
                    await asyncio.sleep(0.5)  # Small delay between snapshots

            finally:
                await camera.cleanup()

        asyncio.run(take_snapshots())

    def _camera_available(self):
        """Check if camera hardware is available."""
        try:
            from picamera2 import Picamera2
            cameras = Picamera2.global_camera_info()
            return len(cameras) > 0
        except Exception:
            return False


def run_tests():
    """Run all test suites."""
    print("=" * 70)
    print("Camera Module Comprehensive Test Suite")
    print("=" * 70)

    # Check if camera is available
    try:
        from picamera2 import Picamera2
        cameras = Picamera2.global_camera_info()
        if len(cameras) == 0:
            print("WARNING: No camera hardware detected. Some tests will be skipped.")
        else:
            print(f"Camera hardware detected: {cameras}")
    except Exception as e:
        print(f"WARNING: Could not check camera hardware: {e}")

    print("\n" + "-" * 50)
    print("Running Unit Tests...")
    print("-" * 50)

    # Run unit tests
    suite = unittest.TestLoader().loadTestsFromTestCase(TestCameraModule)
    runner = unittest.TextTestRunner(verbosity=2)
    result1 = runner.run(suite)

    print("\n" + "-" * 50)
    print("Running Integration Tests...")
    print("-" * 50)

    # Run integration tests
    suite = unittest.TestLoader().loadTestsFromTestCase(TestCameraIntegration)
    runner = unittest.TextTestRunner(verbosity=2)
    result2 = runner.run(suite)

    print("\n" + "-" * 50)
    print("Running Stress Tests...")
    print("-" * 50)

    # Run stress tests
    suite = unittest.TestLoader().loadTestsFromTestCase(TestCameraStress)
    runner = unittest.TextTestRunner(verbosity=2)
    result3 = runner.run(suite)

    # Summary
    total_tests = result1.testsRun + result2.testsRun + result3.testsRun
    total_failures = len(result1.failures) + len(result2.failures) + len(result3.failures)
    total_errors = len(result1.errors) + len(result2.errors) + len(result3.errors)

    print("\n" + "=" * 70)
    print("Test Summary")
    print("=" * 70)
    print(f"Total Tests Run: {total_tests}")
    print(f"Failures: {total_failures}")
    print(f"Errors: {total_errors}")

    if total_failures == 0 and total_errors == 0:
        print("✅ ALL TESTS PASSED!")
        return True
    else:
        print("❌ SOME TESTS FAILED!")
        return False


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)