#!/usr/bin/env python3
"""
Unified Master Controller for Camera and Eye Tracker Modules

This master controller manages both camera and eye tracker modules,
handling graceful startup/shutdown even when devices are not available.
"""

import subprocess
import json
import time
import threading
import signal
import sys
import os
from queue import Queue, Empty
from datetime import datetime
import argparse
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("UnifiedMaster")


class ModuleController:
    """Controller for a single module (camera or eye tracker)"""

    def __init__(self, name, module_path, args=None):
        self.name = name
        self.module_path = module_path
        self.args = args or []
        self.proc = None
        self.status_queue = Queue()
        self.reader_thread = None
        self.running = False
        self.initialized = False
        self.device_found = False
        self.logger = logging.getLogger(f"Module.{name}")

    def start(self, timeout=10):
        """Start the module subprocess"""
        # Build command - use full path to uv
        uv_path = "/home/rs-pi-2/.local/bin/uv"
        cmd = [uv_path, "run", self.module_path, "--slave"]
        cmd.extend(self.args)

        self.logger.info("Starting module: %s", " ".join(cmd))

        try:
            # Get the base directory for the module
            module_dir = os.path.dirname(os.path.abspath(self.module_path))

            self.proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                cwd="/home/rs-pi-2/Development/RPi_Logger"  # Always run from main directory
            )

            self.running = True

            # Start reader thread
            self.reader_thread = threading.Thread(
                target=self._read_output,
                daemon=True,
                name=f"{self.name}_reader"
            )
            self.reader_thread.start()

            # Wait for initialization or error
            start_time = time.time()
            while time.time() - start_time < timeout:
                try:
                    msg = self.status_queue.get(timeout=0.5)

                    if msg.get("status") == "initialized":
                        self.initialized = True
                        self.device_found = True
                        self.logger.info("Module initialized successfully: %s", msg.get("data", {}))
                        return True

                    elif msg.get("status") == "device_not_found":
                        self.logger.warning("Device not found for %s: %s",
                                          self.name, msg.get("data", {}).get("message", ""))
                        self.initialized = False
                        self.device_found = False
                        # Module will exit gracefully
                        return False

                    elif msg.get("status") == "error":
                        self.logger.error("Module error: %s", msg.get("data", {}).get("message", ""))
                        self.initialized = False
                        return False

                    elif msg.get("status") == "searching":
                        self.logger.info("Module searching for device: %s", msg.get("data", {}))

                    # Put message back for other consumers
                    self.status_queue.put(msg)

                except Empty:
                    # Check if process has exited
                    if self.proc.poll() is not None:
                        self.logger.warning("Module exited during initialization (exit code: %d)",
                                          self.proc.returncode)
                        self.running = False
                        return False

            self.logger.warning("Module initialization timeout")
            return False

        except Exception as e:
            self.logger.error("Failed to start module: %s", e)
            self.running = False
            return False

    def _read_output(self):
        """Read output from module subprocess"""
        while self.running and self.proc and self.proc.poll() is None:
            try:
                line = self.proc.stdout.readline()
                if line:
                    try:
                        message = json.loads(line.strip())
                        self.status_queue.put(message)
                        self.logger.debug("Received: %s", message)
                    except json.JSONDecodeError:
                        self.logger.warning("Invalid JSON: %s", line.strip())
            except Exception as e:
                if self.running:  # Only log if we're still supposed to be running
                    self.logger.error("Error reading output: %s", e)
                break

        self.logger.debug("Reader thread exiting")

    def send_command(self, command, **params):
        """Send command to module"""
        if not self.proc or self.proc.poll() is not None:
            return {"error": "Module not running"}

        if not self.initialized and command != "quit":
            return {"error": "Module not initialized"}

        cmd_data = {"command": command, **params}
        try:
            self.proc.stdin.write(json.dumps(cmd_data) + "\n")
            self.proc.stdin.flush()
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    def get_status_messages(self, timeout=0.1):
        """Get all pending status messages"""
        messages = []
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                message = self.status_queue.get(timeout=min(remaining, 0.01))
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

    def shutdown(self, timeout=5.0):
        """Shutdown module gracefully"""
        self.running = False

        if not self.proc:
            return

        if self.proc.poll() is not None:
            self.logger.debug("Module already terminated")
            return

        # Send quit command if initialized
        if self.initialized:
            self.logger.info("Sending quit command to %s", self.name)
            self.send_command("quit")

            # Wait for graceful shutdown
            try:
                self.proc.wait(timeout=timeout)
                self.logger.info("Module shut down gracefully")
                return
            except subprocess.TimeoutExpired:
                self.logger.warning("Module didn't respond to quit command")

        # Try SIGTERM
        self.logger.info("Sending SIGTERM to %s", self.name)
        self.proc.terminate()
        try:
            self.proc.wait(timeout=2.0)
            self.logger.info("Module terminated")
        except subprocess.TimeoutExpired:
            # Force kill
            self.logger.warning("Force killing %s", self.name)
            self.proc.kill()
            self.proc.wait()

    def is_running(self):
        """Check if module is still running"""
        return self.proc and self.proc.poll() is None


class UnifiedMaster:
    """Main controller for all modules"""

    def __init__(self, camera_args=None, tracker_args=None):
        self.modules = {}
        self.recording = False
        self.running = False
        self.camera_args = camera_args or []
        self.tracker_args = tracker_args or []

        # Setup signal handlers
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info("Received signal %d, shutting down...", signum)
        self.shutdown_all()
        sys.exit(0)

    def start_modules(self):
        """Start all available modules"""
        modules_config = [
            ("camera", "Modules/Cameras/camera_module.py", self.camera_args),
            ("eyetracker", "Modules/EyeTracker/fixation_recorder.py", self.tracker_args)
        ]

        started = []
        failed = []

        for name, path, args in modules_config:
            print(f"\n{'='*50}")
            print(f"Starting {name} module...")
            print(f"{'='*50}")

            module = ModuleController(name, path, args)
            self.modules[name] = module

            if module.start(timeout=15):  # Give more time for device detection
                started.append(name)
                print(f"✓ {name} module started successfully")
            else:
                if not module.device_found:
                    print(f"ℹ {name} module: No device found (graceful exit)")
                else:
                    print(f"✗ {name} module failed to start")
                failed.append(name)

        print(f"\n{'='*50}")
        print("STARTUP SUMMARY")
        print(f"{'='*50}")
        print(f"Started modules: {', '.join(started) if started else 'None'}")
        print(f"Unavailable modules: {', '.join(failed) if failed else 'None'}")

        return len(started) > 0

    def send_to_all(self, command, **params):
        """Send command to all active modules"""
        results = {}
        for name, module in self.modules.items():
            if module.initialized:
                results[name] = module.send_command(command, **params)
            else:
                results[name] = {"skipped": "Not initialized"}
        return results

    def start_recording(self):
        """Start recording on all active modules"""
        if self.recording:
            print("Already recording")
            return False

        print("\nStarting recording on all active modules...")
        results = self.send_to_all("start_recording")

        success_count = 0
        for name, result in results.items():
            if result.get("success"):
                success_count += 1
                print(f"  ✓ {name}: Recording started")
            elif result.get("skipped"):
                print(f"  - {name}: Skipped (not available)")
            else:
                print(f"  ✗ {name}: Failed - {result.get('error', 'Unknown error')}")

        if success_count > 0:
            self.recording = True
            print(f"Recording started on {success_count} module(s)")
            return True
        else:
            print("No modules available for recording")
            return False

    def stop_recording(self):
        """Stop recording on all active modules"""
        if not self.recording:
            print("Not currently recording")
            return False

        print("\nStopping recording on all active modules...")
        results = self.send_to_all("stop_recording")

        for name, result in results.items():
            if result.get("success"):
                print(f"  ✓ {name}: Recording stopped")
            elif result.get("skipped"):
                print(f"  - {name}: Skipped")
            else:
                print(f"  ✗ {name}: Failed - {result.get('error', 'Unknown error')}")

        self.recording = False
        return True

    def take_snapshot(self):
        """Take snapshot on all active modules"""
        print("\nTaking snapshot on all active modules...")
        results = self.send_to_all("take_snapshot")

        for name, result in results.items():
            if result.get("success"):
                # Wait for response
                module = self.modules[name]
                snapshot_msg = module.wait_for_status("snapshot_taken", timeout=2.0)
                if snapshot_msg:
                    files = snapshot_msg.get("data", {}).get("files", [])
                    if files:
                        print(f"  ✓ {name}: Saved {len(files)} file(s)")
                    else:
                        file = snapshot_msg.get("data", {}).get("file")
                        if file:
                            print(f"  ✓ {name}: Saved {file}")
            elif result.get("skipped"):
                print(f"  - {name}: Skipped")

    def get_status(self):
        """Get status from all modules"""
        print("\n" + "="*50)
        print("MODULE STATUS")
        print("="*50)

        results = self.send_to_all("get_status")

        for name, module in self.modules.items():
            print(f"\n{name.upper()}:")

            if not module.is_running():
                print("  Status: Not running")
                continue

            if not module.initialized:
                print("  Status: Not initialized (no device)")
                continue

            # Get status response
            status_msg = module.wait_for_status("status_report", timeout=1.0)
            if status_msg:
                data = status_msg.get("data", {})
                print(f"  Status: Active")
                print(f"  Recording: {data.get('recording', False)}")

                # Module-specific info
                if name == "camera":
                    cameras = data.get("cameras", [])
                    for cam in cameras:
                        print(f"  Camera {cam['cam_num']}: {cam['fps']:.1f} FPS")
                elif name == "eyetracker":
                    print(f"  Frame count: {data.get('frame_count', 0)}")
                    if data.get('output_file'):
                        print(f"  Output: {data['output_file']}")

    def shutdown_all(self):
        """Shutdown all modules gracefully"""
        if not self.modules:
            return

        print("\n" + "="*50)
        print("SHUTTING DOWN ALL MODULES")
        print("="*50)

        for name, module in self.modules.items():
            print(f"Shutting down {name}...")
            module.shutdown()

        self.modules.clear()
        print("All modules stopped")

    def interactive_mode(self):
        """Run interactive command mode"""
        self.running = True

        print("\n" + "="*70)
        print("UNIFIED MASTER CONTROLLER")
        print("="*70)
        print("\nCommands:")
        print("  start    - Start recording")
        print("  stop     - Stop recording")
        print("  snap     - Take snapshot")
        print("  status   - Show module status")
        print("  quit     - Exit program")
        print("")

        while self.running:
            try:
                # Display prompt
                prompt = "[REC] > " if self.recording else "> "
                cmd = input(prompt).strip().lower()

                if cmd in ["quit", "q", "exit"]:
                    self.running = False
                elif cmd in ["start", "record", "r"]:
                    self.start_recording()
                elif cmd in ["stop", "s"]:
                    self.stop_recording()
                elif cmd in ["snap", "snapshot", "p"]:
                    self.take_snapshot()
                elif cmd in ["status", "stat"]:
                    self.get_status()
                elif cmd == "":
                    continue
                else:
                    print(f"Unknown command: {cmd}")

                # Process any pending status messages
                for name, module in self.modules.items():
                    messages = module.get_status_messages(timeout=0.01)
                    for msg in messages:
                        if msg.get("status") not in ["initialized", "status_report"]:
                            print(f"  [{name}] {msg.get('status')}: {msg.get('data', {})}")

            except KeyboardInterrupt:
                print("\nInterrupted")
                self.running = False
            except EOFError:
                print()
                self.running = False

    def demo_mode(self):
        """Run automated demo"""
        print("\n" + "="*70)
        print("DEMO MODE - UNIFIED MASTER CONTROLLER")
        print("="*70)

        # Get initial status
        print("\n1. Getting initial status...")
        self.get_status()
        time.sleep(2)

        # Start recording
        print("\n2. Starting recording...")
        if self.start_recording():
            time.sleep(5)

            # Take snapshot
            print("\n3. Taking snapshot...")
            self.take_snapshot()
            time.sleep(2)

            # Stop recording
            print("\n4. Stopping recording...")
            self.stop_recording()
            time.sleep(2)

        # Final status
        print("\n5. Final status...")
        self.get_status()


def main():
    parser = argparse.ArgumentParser(description="Unified Master Controller")
    parser.add_argument("--demo", action="store_true", help="Run demo mode")
    parser.add_argument("--camera-timeout", type=int, default=5,
                       help="Camera discovery timeout (seconds)")
    parser.add_argument("--tracker-timeout", type=int, default=10,
                       help="Eye tracker discovery timeout (seconds)")
    parser.add_argument("--camera-fps", type=int, default=25,
                       help="Camera recording FPS")
    parser.add_argument("--camera-width", type=int, default=1280,
                       help="Camera recording width")
    parser.add_argument("--camera-height", type=int, default=720,
                       help="Camera recording height")
    parser.add_argument("--allow-partial", action="store_true",
                       help="Allow running with single camera")

    args = parser.parse_args()

    # Build module arguments
    camera_args = [
        "--timeout", str(args.camera_timeout),
        "--fps", str(args.camera_fps),
        "--width", str(args.camera_width),
        "--height", str(args.camera_height),
        "--output", "unified_recordings/camera"
    ]
    if args.allow_partial:
        camera_args.append("--allow-partial")

    tracker_args = [
        "--timeout", str(args.tracker_timeout),
        "--output", "unified_recordings/eyetracker"
    ]

    # Create master controller
    master = UnifiedMaster(camera_args, tracker_args)

    try:
        # Start modules
        if not master.start_modules():
            print("\nNo modules could be started. Exiting...")
            sys.exit(1)

        # Give modules a moment to stabilize
        time.sleep(1)

        # Run in selected mode
        if args.demo:
            master.demo_mode()
        else:
            master.interactive_mode()

    except KeyboardInterrupt:
        print("\n\nInterrupted by user")

    finally:
        master.shutdown_all()
        print("\nGoodbye!")


if __name__ == "__main__":
    main()