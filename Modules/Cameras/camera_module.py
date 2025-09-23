#!/usr/bin/env python3
import os
import cv2
import logging
import datetime
import argparse
import time
import signal
import sys
import json
import threading
import select
from picamera2 import Picamera2

# Logging setup - force to stderr for slave mode compatibility
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,  # Force logging to stderr
)
logger = logging.getLogger("CameraSystem")


class CameraHandler:
    def __init__(self, cam_info, cam_num, args):
        self.logger = logging.getLogger(f"Camera{cam_num}")
        self.cam_num = cam_num
        self.output_dir = args.output
        self.recording = False
        self.args = args

        os.makedirs(self.output_dir, exist_ok=True)

        self.logger.info("Initializing camera %d", cam_num)
        self.picam2 = Picamera2(cam_num)

        # Configure recording stream (full resolution, adjustable fps)
        config = self.picam2.create_video_configuration(
            main={
                "size": (args.width, args.height),
                "format": "RGB888",
            },
            controls={
                "FrameDurationLimits": (int(1e6 / args.fps), int(1e6 / args.fps)),
            },
        )
        self.picam2.configure(config)
        self.picam2.start()
        self.logger.info("Camera %d initialized", cam_num)

        self.recorder = None
        self.last_frame_time = time.time()
        self.frame_count = 0
        self.fps = 0.0

    def start_recording(self):
        if self.recording:
            return
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(self.output_dir, f"cam{self.cam_num}_{ts}.h264")
        self.logger.info("Recording to %s", filename)
        self.picam2.start_recording(filename)
        self.recording = True
        self.recorder = filename

    def stop_recording(self):
        if not self.recording:
            return
        self.picam2.stop_recording()
        self.logger.info("Stopped recording: %s", self.recorder)
        self.recording = False
        self.recorder = None

    def get_frame(self):
        frame = self.picam2.capture_array("main")
        if frame is None:
            return None

        # Resize for preview
        frame = cv2.resize(frame, (self.args.preview_width, self.args.preview_height))

        # FPS calculation
        self.frame_count += 1
        now = time.time()
        if now - self.last_frame_time >= 1.0:
            self.fps = self.frame_count / (now - self.last_frame_time)
            self.frame_count = 0
            self.last_frame_time = now

        # Timestamp + FPS overlay
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        overlay_text = f"Cam {self.cam_num} | {ts} | {self.fps:.1f} FPS"
        cv2.putText(
            frame,
            overlay_text,
            (10, 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 255, 0),
            1,
            cv2.LINE_AA,
        )
        return frame

    def cleanup(self):
        if self.recording:
            self.stop_recording()
        self.picam2.stop()
        self.picam2.close()
        self.logger.info("Cleanup completed")


class CameraSystem:
    def __init__(self, args):
        self.logger = logging.getLogger("CameraSystem")
        self.cameras = []
        self.running = False
        self.recording = False
        self.args = args
        self.slave_mode = args.slave
        self.command_thread = None
        self.shutdown_event = threading.Event()
        self.device_timeout = getattr(args, 'timeout', 5)  # Default 5 seconds timeout

        # Setup signal handlers
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        # Device will be initialized in run() method after signal handlers are ready
        if self.slave_mode:
            self.send_status("initializing", {"device": "cameras"})

    def _initialize_cameras(self):
        """Initialize cameras with timeout and graceful handling"""
        self.logger.info("Searching for cameras (timeout: %ds)...", self.device_timeout)

        start_time = time.time()
        cam_infos = []

        # Try to detect cameras with timeout
        while time.time() - start_time < self.device_timeout:
            try:
                cam_infos = Picamera2.global_camera_info()
                if cam_infos:
                    break
            except Exception as e:
                self.logger.debug("Camera detection attempt failed: %s", e)

            # Check if we should abort
            if self.shutdown_event.is_set():
                raise KeyboardInterrupt("Device discovery cancelled")

            time.sleep(0.5)  # Brief pause between attempts

        # Log found cameras
        for i, info in enumerate(cam_infos):
            self.logger.info("Found camera %d: %s", i, info)

        # Check if we have the required cameras
        if not cam_infos:
            error_msg = f"No cameras found within {self.device_timeout} seconds"
            self.logger.error(error_msg)
            if self.slave_mode:
                self.send_status("error", {"message": error_msg})
            raise RuntimeError(error_msg)

        if len(cam_infos) < 2 and not self.args.single_camera:
            warning_msg = f"Only {len(cam_infos)} camera(s) found, expected at least 2"
            self.logger.warning(warning_msg)
            if not self.args.allow_partial:
                if self.slave_mode:
                    self.send_status("error", {"message": warning_msg})
                raise RuntimeError(warning_msg)

        # Initialize available cameras
        self.logger.info("Initializing %d camera(s)...", min(len(cam_infos), 2))
        try:
            for i in range(min(len(cam_infos), 2)):
                self.cameras.append(CameraHandler(cam_infos[i], i, self.args))

            self.logger.info("Successfully initialized %d camera(s)", len(self.cameras))
            if self.slave_mode:
                self.send_status("initialized", {"cameras": len(self.cameras)})

        except Exception as e:
            self.logger.error("Failed to initialize cameras: %s", e)
            if self.slave_mode:
                self.send_status("error", {"message": f"Camera initialization failed: {e}"})
            raise

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.logger.info("Received signal %d, shutting down...", signum)
        self.running = False
        self.shutdown_event.set()
        if self.slave_mode:
            self.send_status("shutdown", {"signal": signum})

    def send_status(self, status_type, data=None):
        """Send status message to master (if in slave mode)"""
        if not self.slave_mode:
            return

        message = {
            "type": "status",
            "status": status_type,
            "timestamp": datetime.datetime.now().isoformat(),
            "data": data or {}
        }
        # Force to stdout for master communication
        sys.stdout.write(json.dumps(message) + "\n")
        sys.stdout.flush()

    def handle_command(self, command_data):
        """Handle command from master"""
        try:
            cmd = command_data.get("command")

            if cmd == "start_recording":
                if not self.recording:
                    for cam in self.cameras:
                        cam.start_recording()
                    self.recording = True
                    self.send_status("recording_started")
                else:
                    self.send_status("error", {"message": "Already recording"})

            elif cmd == "stop_recording":
                if self.recording:
                    for cam in self.cameras:
                        cam.stop_recording()
                    self.recording = False
                    self.send_status("recording_stopped")
                else:
                    self.send_status("error", {"message": "Not recording"})

            elif cmd == "take_snapshot":
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                filenames = []
                for i, cam in enumerate(self.cameras):
                    frame = cam.get_frame()
                    if frame is not None:
                        filename = os.path.join(self.args.output, f"snapshot_cam{i}_{ts}.jpg")
                        cv2.imwrite(filename, frame)
                        filenames.append(filename)
                self.send_status("snapshot_taken", {"files": filenames})

            elif cmd == "get_status":
                status_data = {
                    "recording": self.recording,
                    "cameras": [
                        {
                            "cam_num": cam.cam_num,
                            "recording": cam.recording,
                            "fps": cam.fps,
                            "frame_count": cam.frame_count
                        } for cam in self.cameras
                    ]
                }
                self.send_status("status_report", status_data)

            elif cmd == "quit":
                self.running = False
                self.shutdown_event.set()
                self.send_status("quitting")

            else:
                self.send_status("error", {"message": f"Unknown command: {cmd}"})

        except Exception as e:
            self.send_status("error", {"message": str(e)})

    def command_listener(self):
        """Listen for commands from stdin in slave mode"""
        while self.running and not self.shutdown_event.is_set():
            try:
                # Use select to check if stdin has data available
                if select.select([sys.stdin], [], [], 0.1)[0]:
                    line = sys.stdin.readline().strip()
                    if line:
                        command_data = json.loads(line)
                        self.handle_command(command_data)
            except json.JSONDecodeError as e:
                self.send_status("error", {"message": f"Invalid JSON: {e}"})
            except Exception as e:
                self.send_status("error", {"message": f"Command error: {e}"})
                break

    def preview_loop(self):
        """Interactive preview mode (standalone only)"""
        if not self.cameras:
            self.logger.error("No cameras available for preview")
            return

        self.running = True

        # Create windows for available cameras
        for i, cam in enumerate(self.cameras):
            cv2.namedWindow(f"Camera {i}")

        self.logger.info("Preview mode: 'q' to quit, 's' for snapshot, 'r' to toggle recording")
        while self.running and not self.shutdown_event.is_set():
            frames = [cam.get_frame() for cam in self.cameras]

            # Display frames for available cameras
            for i, frame in enumerate(frames):
                if frame is not None:
                    cv2.imshow(f"Camera {i}", frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                self.running = False
            elif key == ord("r"):
                if not self.recording:
                    for cam in self.cameras:
                        cam.start_recording()
                    self.recording = True
                else:
                    for cam in self.cameras:
                        cam.stop_recording()
                    self.recording = False
            elif key == ord("s"):
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                for i, frame in enumerate(frames):
                    if frame is not None:
                        filename = os.path.join(self.args.output, f"snapshot_cam{i}_{ts}.jpg")
                        cv2.imwrite(filename, frame)
                        self.logger.info("Saved snapshot %s", filename)

        self.logger.info("All preview windows closed")
        cv2.destroyAllWindows()

    def slave_loop(self):
        """Command-driven slave mode (no GUI)"""
        self.running = True

        # Start command listener thread
        self.command_thread = threading.Thread(target=self.command_listener, daemon=True)
        self.command_thread.start()

        self.logger.info("Slave mode: waiting for commands...")

        # Keep cameras active but don't display
        while self.running and not self.shutdown_event.is_set():
            # Just keep cameras running and capture frames to maintain FPS calculation
            for cam in self.cameras:
                cam.get_frame()  # This updates FPS counters

            # Brief sleep to prevent excessive CPU usage
            time.sleep(0.033)  # ~30 FPS update rate

        self.logger.info("Slave mode ended")

    def run(self):
        """Main run method - chooses mode based on configuration"""
        try:
            # Initialize cameras now that signal handlers are set up
            self._initialize_cameras()

            if self.slave_mode:
                self.slave_loop()
            else:
                self.preview_loop()

        except KeyboardInterrupt:
            self.logger.info("Camera system cancelled by user")
            if self.slave_mode:
                self.send_status("error", {"message": "Cancelled by user"})
        except RuntimeError as e:
            # Device not found or initialization failed - already logged
            pass
        except Exception as e:
            self.logger.error("Unexpected error in run: %s", e)
            if self.slave_mode:
                self.send_status("error", {"message": f"Unexpected error: {e}"})

    def cleanup(self):
        self.logger.info("Cleaning up cameras...")
        for cam in self.cameras:
            cam.cleanup()
        self.logger.info("Cleanup completed")


def parse_args():
    parser = argparse.ArgumentParser(description="Multi-camera recorder with preview and overlays")
    parser.add_argument("--width", type=int, default=1920, help="Recording width")
    parser.add_argument("--height", type=int, default=1080, help="Recording height")
    parser.add_argument("--fps", type=int, default=30, help="Recording FPS")
    parser.add_argument("--preview-width", type=int, default=640, help="Preview window width")
    parser.add_argument("--preview-height", type=int, default=360, help="Preview window height")
    parser.add_argument("--output", type=str, default="recordings", help="Output directory")
    parser.add_argument("--slave", action="store_true", help="Run in slave mode (no preview, command-driven)")
    parser.add_argument("--timeout", type=int, default=5, help="Device discovery timeout in seconds (default: 5)")
    parser.add_argument("--single-camera", action="store_true", help="Allow running with single camera")
    parser.add_argument("--allow-partial", action="store_true", help="Allow running with fewer cameras than expected")
    return parser.parse_args()


def main():
    args = parse_args()
    system = None
    try:
        system = CameraSystem(args)
        system.run()
    except Exception as e:
        logger.error("Fatal error: %s", e, exc_info=True)
        if system and system.slave_mode:
            system.send_status("error", {"message": f"Fatal error: {e}"})
    finally:
        if system:
            system.cleanup()


if __name__ == "__main__":
    main()
