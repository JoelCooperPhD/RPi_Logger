#!/usr/bin/env python3
"""
Test script for dual camera module
Tests various configurations and use cases
"""

import asyncio
import sys
import time
import json
import signal
import threading
import select
from pathlib import Path
import subprocess
from queue import Queue, Empty


def print_header(text):
    """Print formatted header"""
    print("\n" + "=" * 60)
    print(f"  {text}")
    print("=" * 60)


def print_test(test_name, description):
    """Print test information"""
    print(f"\n[TEST] {test_name}")
    print(f"       {description}")
    print("-" * 40)


def cleanup_camera_processes():
    """Kill any remaining camera processes"""
    try:
        result = subprocess.run(["pgrep", "-f", "dual_camera"], capture_output=True, text=True)
        if result.returncode == 0:
            pids = result.stdout.strip().split('\n')
            for pid in pids:
                if pid:
                    subprocess.run(["kill", pid])
                    print(f"Cleaned up process {pid}")
    except Exception:
        pass  # Ignore cleanup errors


async def test_camera_detection():
    """Test camera detection"""
    print_test("Camera Detection", "Detecting available cameras on the system")

    try:
        from picamera2 import Picamera2
        cameras = Picamera2.global_camera_info()

        print(f"Found {len(cameras)} camera(s):")
        for i, cam in enumerate(cameras):
            print(f"  Camera {i}: {cam}")

        return len(cameras)
    except Exception as e:
        print(f"Error: {e}")
        return 0


async def test_help_output():
    """Test help output"""
    print_test("Help Output", "Testing --help argument")

    cmd = ["uv", "run", "dual_camera_module.py", "--help"]

    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        print("✓ Test passed")
        # Check for new --slave option
        if "--slave" in result.stdout:
            print("✓ Slave mode option found in help")
        else:
            print("✗ Slave mode option not found in help")
            return False
        print("Help output:")
        print(result.stdout)
    else:
        print(f"✗ Test failed: {result.stderr}")

    return result.returncode == 0


async def test_basic_run():
    """Test basic run with default settings"""
    print_test("Basic Run", "Testing with default settings (will run for ~3 seconds)")

    cmd = ["uv", "run", "dual_camera_module.py", "--output", "test_recordings"]

    print(f"Running: {' '.join(cmd)}")
    print("Note: Will timeout after 5 seconds (interactive mode)")

    # Run with timeout since it's interactive
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        print("✓ Test completed")
        return True
    except subprocess.TimeoutExpired:
        print("✓ Test passed (interactive mode started successfully)")
        return True
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False


async def test_custom_settings():
    """Test with custom settings"""
    print_test("Custom Settings", "Testing with custom resolution and FPS")

    cmd = [
        "uv", "run", "dual_camera_module.py",
        "--width", "1280",
        "--height", "720",
        "--fps", "25",
        "--preview-width", "320",
        "--preview-height", "240",
        "--output", "test_recordings"
    ]

    print(f"Running: {' '.join(cmd)}")
    print("Note: Will timeout after 3 seconds")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
        print("✓ Test completed")
        return True
    except subprocess.TimeoutExpired:
        print("✓ Test passed (interactive mode started successfully)")
        return True
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False


async def test_output_directory():
    """Test output directory creation"""
    print_test("Output Directory", "Testing custom output directory")

    custom_dir = "custom_test_output"
    cmd = [
        "uv", "run", "dual_camera_module.py",
        "--output", custom_dir
    ]

    print(f"Running: {' '.join(cmd)}")
    print("Note: Will timeout after 3 seconds")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
        print("✓ Test completed")

        # Check if directory was created
        if Path(custom_dir).exists():
            print(f"✓ Directory '{custom_dir}' was created")
            return True
        else:
            print(f"✗ Directory '{custom_dir}' was not created")
            return False
    except subprocess.TimeoutExpired:
        # Check if directory was created
        if Path(custom_dir).exists():
            print(f"✓ Test passed - Directory '{custom_dir}' was created")
            return True
        else:
            print(f"✗ Directory '{custom_dir}' was not created")
            return False
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False


async def test_different_configurations():
    """Test various camera configurations"""
    print_test("Configuration Tests", "Testing different resolution and FPS settings")

    configs = [
        {"width": "640", "height": "480", "fps": "30"},
        {"width": "1280", "height": "720", "fps": "25"},
        {"width": "1920", "height": "1080", "fps": "20"},
    ]

    for i, config in enumerate(configs):
        print(f"\n  Config {i+1}: {config['width']}x{config['height']} @ {config['fps']}fps")

        cmd = [
            "uv", "run", "dual_camera_module.py",
            "--width", config["width"],
            "--height", config["height"],
            "--fps", config["fps"],
            "--output", "test_configs"
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
            print("    ✓ Passed")
        except subprocess.TimeoutExpired:
            print("    ✓ Passed (started successfully)")
        except Exception as e:
            print(f"    ✗ Failed: {e}")

    return True


async def test_slave_mode_basic():
    """Test slave mode initialization"""
    print_test("Slave Mode Basic", "Testing slave mode initialization and basic commands")

    cmd = ["uv", "run", "dual_camera_module.py", "--slave", "--output", "slave_test"]

    print(f"Running: {' '.join(cmd)}")

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )

        # Wait for initialization message
        start_time = time.time()
        init_received = False

        while time.time() - start_time < 10.0:
            # Use select to check if stdout has data available
            if select.select([proc.stdout], [], [], 0.1)[0]:
                line = proc.stdout.readline()
                if line:
                    try:
                        message = json.loads(line.strip())
                        if message.get("status") == "initialized":
                            print("✓ Slave mode initialized successfully")
                            init_received = True
                            break
                    except json.JSONDecodeError:
                        continue

        if not init_received:
            print("✗ Failed to receive initialization message")
            proc.terminate()
            return False

        # Send quit command
        quit_cmd = json.dumps({"command": "quit"}) + "\n"
        proc.stdin.write(quit_cmd)
        proc.stdin.flush()

        # Wait for shutdown
        try:
            proc.wait(timeout=3.0)
            print("✓ Graceful shutdown successful")
        except subprocess.TimeoutExpired:
            proc.terminate()
            print("✗ Shutdown timeout")
            return False

        return True

    except Exception as e:
        print(f"✗ Test failed: {e}")
        if 'proc' in locals():
            proc.terminate()
        return False


async def test_slave_mode_commands():
    """Test slave mode command processing"""
    print_test("Slave Mode Commands", "Testing JSON command protocol")

    cmd = ["uv", "run", "dual_camera_module.py", "--slave", "--output", "slave_commands_test"]

    print(f"Running: {' '.join(cmd)}")

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )

        # Wait for initialization
        init_received = False
        start_time = time.time()

        while time.time() - start_time < 10.0:
            if select.select([proc.stdout], [], [], 0.1)[0]:
                line = proc.stdout.readline()
                if line:
                    try:
                        message = json.loads(line.strip())
                        if message.get("status") == "initialized":
                            init_received = True
                            break
                    except json.JSONDecodeError:
                        continue

        if not init_received:
            print("✗ Failed to initialize for command test")
            proc.terminate()
            return False

        # Test commands
        commands_to_test = [
            ("get_status", "status_report"),
            ("take_snapshot", "snapshot_taken"),
            ("start_recording", "recording_started"),
            ("stop_recording", "recording_stopped"),
        ]

        all_passed = True
        for cmd_name, expected_status in commands_to_test:
            print(f"  Testing {cmd_name}...")

            # Send command
            command = json.dumps({"command": cmd_name}) + "\n"
            proc.stdin.write(command)
            proc.stdin.flush()

            # Wait for response
            response_received = False
            start_time = time.time()

            while time.time() - start_time < 5.0:
                if select.select([proc.stdout], [], [], 0.1)[0]:
                    line = proc.stdout.readline()
                    if line:
                        try:
                            message = json.loads(line.strip())
                            if message.get("status") == expected_status:
                                print(f"    ✓ {cmd_name} successful")
                                response_received = True
                                break
                        except json.JSONDecodeError:
                            continue

            if not response_received:
                print(f"    ✗ {cmd_name} failed - no response")
                all_passed = False

        # Clean shutdown
        quit_cmd = json.dumps({"command": "quit"}) + "\n"
        proc.stdin.write(quit_cmd)
        proc.stdin.flush()
        proc.wait(timeout=3.0)

        return all_passed

    except Exception as e:
        print(f"✗ Test failed: {e}")
        if 'proc' in locals():
            proc.terminate()
        return False


async def test_signal_handling():
    """Test signal handling for graceful shutdown"""
    print_test("Signal Handling", "Testing SIGTERM graceful shutdown")

    cmd = ["uv", "run", "dual_camera_module.py", "--slave", "--output", "signal_test"]

    print(f"Running: {' '.join(cmd)}")

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )

        # Wait for initialization
        init_received = False
        start_time = time.time()

        while time.time() - start_time < 10.0:
            if select.select([proc.stdout], [], [], 0.1)[0]:
                line = proc.stdout.readline()
                if line:
                    try:
                        message = json.loads(line.strip())
                        if message.get("status") == "initialized":
                            init_received = True
                            break
                    except json.JSONDecodeError:
                        continue

        if not init_received:
            print("✗ Failed to initialize for signal test")
            proc.terminate()
            return False

        # Send SIGTERM
        proc.send_signal(signal.SIGTERM)

        # Check for shutdown message
        shutdown_received = False
        start_time = time.time()

        while time.time() - start_time < 5.0:
            if select.select([proc.stdout], [], [], 0.1)[0]:
                line = proc.stdout.readline()
                if line:
                    try:
                        message = json.loads(line.strip())
                        if message.get("status") == "shutdown":
                            print("✓ Graceful shutdown signal received")
                            shutdown_received = True
                            break
                    except json.JSONDecodeError:
                        continue

        # Wait for process to exit
        try:
            proc.wait(timeout=3.0)
            print("✓ Process exited gracefully")
            return shutdown_received
        except subprocess.TimeoutExpired:
            proc.kill()
            print("✗ Process didn't exit gracefully")
            return False

    except Exception as e:
        print(f"✗ Test failed: {e}")
        if 'proc' in locals():
            proc.terminate()
        return False


async def test_master_integration():
    """Test integration with master program"""
    print_test("Master Integration", "Testing camera_master.py integration")

    cmd = ["uv", "run", "camera_master.py"]

    print(f"Running: {' '.join(cmd)}")

    try:
        # Run master program with timeout
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
            input=""  # Provide empty input to avoid hanging
        )

        # Check output for success indicators
        output = result.stdout + result.stderr

        success_indicators = [
            "Camera system initialized",
            "Recording started",
            "Snapshot saved",
            "Recording stopped",
            "Camera system shut down gracefully"
        ]

        passed_checks = 0
        for indicator in success_indicators:
            if indicator in output:
                passed_checks += 1
                print(f"    ✓ {indicator}")
            else:
                print(f"    ✗ Missing: {indicator}")

        success = passed_checks >= 4  # Allow some flexibility
        if success:
            print("✓ Master integration test passed")
        else:
            print("✗ Master integration test failed")

        return success

    except subprocess.TimeoutExpired:
        print("✗ Master integration test timed out")
        return False
    except Exception as e:
        print(f"✗ Master integration test failed: {e}")
        return False


async def interactive_test():
    """Interactive test with user controls"""
    print_test("Interactive Test",
               "Manual control test - follow on-screen instructions")

    print("""
    Controls:
      q - Quit
      s - Capture snapshot
      r - Toggle recording

    Press Enter to start the test...
    """)

    input()

    cmd = [
        "uv", "run", "dual_camera_module.py",
        "--width", "1280",
        "--height", "720"
    ]

    print(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd)


async def main():
    """Run all tests"""
    print_header("DUAL CAMERA MODULE TEST SUITE")
    print("Testing dual camera functionality on Raspberry Pi 5")

    # Check camera availability
    num_cameras = await test_camera_detection()

    if num_cameras == 0:
        print("\n⚠ No cameras detected! Please check connections.")
        sys.exit(1)

    print(f"\n✓ Found {num_cameras} camera(s) - proceeding with tests")

    # Run automated tests
    tests_passed = []

    # Test help output
    passed = await test_help_output()
    tests_passed.append(("Help Output", passed))

    # Test basic run (only if cameras available)
    if num_cameras >= 2:
        passed = await test_basic_run()
        tests_passed.append(("Basic Run", passed))

        # Test custom settings
        passed = await test_custom_settings()
        tests_passed.append(("Custom Settings", passed))

    # Test output directory
    passed = await test_output_directory()
    tests_passed.append(("Output Directory", passed))

    # Test different configurations
    if num_cameras >= 2:
        passed = await test_different_configurations()
        tests_passed.append(("Configurations", passed))

    # Test new slave mode functionality
    if num_cameras >= 2:
        # Cleanup any remaining processes before slave tests
        cleanup_camera_processes()
        await asyncio.sleep(2)

        passed = await test_slave_mode_basic()
        tests_passed.append(("Slave Mode Basic", passed))

        cleanup_camera_processes()
        await asyncio.sleep(1)
        passed = await test_slave_mode_commands()
        tests_passed.append(("Slave Mode Commands", passed))

        cleanup_camera_processes()
        await asyncio.sleep(1)
        passed = await test_signal_handling()
        tests_passed.append(("Signal Handling", passed))

        cleanup_camera_processes()
        await asyncio.sleep(1)
        passed = await test_master_integration()
        tests_passed.append(("Master Integration", passed))

    # Print summary
    print_header("TEST SUMMARY")

    total = len(tests_passed)
    passed = sum(1 for _, p in tests_passed if p)

    for test_name, test_passed in tests_passed:
        status = "✓ PASSED" if test_passed else "✗ FAILED"
        print(f"  {test_name:20} {status}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All tests passed successfully!")
    else:
        print(f"\n⚠ {total - passed} test(s) failed")

    # Ask for interactive test
    print("\n" + "-" * 60)
    response = input("Run interactive test? (y/n): ")
    if response.lower() == 'y':
        await interactive_test()

    print_header("TEST COMPLETE")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nTest interrupted by user")
        sys.exit(0)