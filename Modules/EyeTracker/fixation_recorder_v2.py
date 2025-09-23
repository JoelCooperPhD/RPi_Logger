#!/usr/bin/env python3
import signal
import sys
import os
import cv2
import threading
import time
import subprocess
import argparse
import queue
import logging
import datetime
import json
import select
from pupil_labs.realtime_api.simple import discover_one_device

# Suppress Qt platform plugin warnings
os.environ['QT_LOGGING_RULES'] = 'qt.qpa.plugin=false'

# Logging setup - force to stderr for slave mode compatibility
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,  # Force logging to stderr
)
logger = logging.getLogger("EyeTrackerSystem")


class EyeTrackerRecorder:
    def __init__(self, args):
        self.logger = logging.getLogger("EyeTrackerRecorder")
        self.args = args
        self.slave_mode = args.slave
        self.device = None
        self.current_gaze = None
        self.gaze_lock = threading.Lock()
        self.ffmpeg_process = None
        self.frame_count = 0
        self.frame_queue = queue.Queue(maxsize=30)
        self.writer_thread = None
        self.gaze_thread_obj = None
        self.command_thread = None
        self.should_stop = threading.Event()
        self.shutdown_event = threading.Event()
        self.running = False
        self.recording = False
        self.output_filename = None

        # Setup signal handlers
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        # Create output directory
        os.makedirs(self.args.output, exist_ok=True)

        # Device will be initialized in run() method after signal handlers are ready
        if self.slave_mode:
            self.send_status("initializing", {"device": "pupil_labs_neon"})

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.logger.info("Received signal %d, shutting down...", signum)
        self.should_stop.set()
        self.shutdown_event.set()
        self.running = False
        if self.slave_mode:
            self.send_status("shutdown", {"signal": signum})

    def _initialize_device(self):
        """Initialize Pupil Labs device with timeout handling"""
        try:
            self.logger.info("Searching for Pupil Labs device (timeout: %ds)...", self.args.timeout)

            # Set up signal handler during device discovery
            def timeout_handler(signum, frame):
                self.logger.info("Device discovery interrupted by signal %d", signum)
                raise KeyboardInterrupt("Device discovery interrupted")

            old_sigint = signal.signal(signal.SIGINT, timeout_handler)
            old_sigterm = signal.signal(signal.SIGTERM, timeout_handler)

            try:
                self.device = discover_one_device(max_search_duration_seconds=self.args.timeout)
            finally:
                # Restore original signal handlers
                signal.signal(signal.SIGINT, old_sigint)
                signal.signal(signal.SIGTERM, old_sigterm)

            if self.device is None:
                self.logger.error("No Pupil Labs device found within %d seconds", self.args.timeout)
                if self.slave_mode:
                    self.send_status("error", {"message": f"No device found within {self.args.timeout} seconds"})
                raise RuntimeError(f"No Pupil Labs device found within {self.args.timeout} seconds")

            self.logger.info("Connected to Pupil Labs device")
        except KeyboardInterrupt:
            self.logger.info("Device discovery cancelled by user")
            if self.slave_mode:
                self.send_status("error", {"message": "Device discovery cancelled"})
            raise
        except Exception as e:
            self.logger.error("Failed to initialize device: %s", e)
            if self.slave_mode:
                self.send_status("error", {"message": f"Device initialization failed: {e}"})
            raise

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

    def gaze_thread(self):
        """Background thread for gaze data collection"""
        while not self.should_stop.is_set():
            try:
                if self.device:
                    gaze = self.device.receive_gaze_datum()
                    with self.gaze_lock:
                        self.current_gaze = gaze
            except Exception:
                if not self.should_stop.is_set():
                    self.logger.error("Gaze thread failure")
                break

    def ffmpeg_writer_thread(self):
        """Background thread for video writing"""
        written_frames = 0
        while not self.should_stop.is_set() or not self.frame_queue.empty():
            try:
                frame_data = self.frame_queue.get(timeout=0.05)
                if self.ffmpeg_process and self.ffmpeg_process.poll() is None:
                    try:
                        self.ffmpeg_process.stdin.write(frame_data)
                        written_frames += 1
                    except Exception:
                        break
                self.frame_queue.task_done()
            except queue.Empty:
                continue
            except Exception:
                self.logger.error("Writer thread failure")
                break

    def draw_gaze_overlay(self, frame, gaze_data, frame_width, frame_height, orig_width, orig_height):
        """Draw gaze fixation overlay on frame"""
        if gaze_data:
            if orig_width != frame_width or orig_height != frame_height:
                gaze_x = int((gaze_data.x / orig_width) * frame_width)
                gaze_y = int((gaze_data.y / orig_height) * frame_height)
            else:
                gaze_x = int(gaze_data.x)
                gaze_y = int(gaze_data.y)

            gaze_x = max(0, min(gaze_x, frame_width - 1))
            gaze_y = max(0, min(gaze_y, frame_height - 1))

            color = (0, 0, 255) if gaze_data.worn else (0, 255, 255)
            cv2.circle(frame, (gaze_x, gaze_y), 30, color, 4)

            return gaze_x, gaze_y, gaze_data.worn
        return None, None, False

    def add_text_overlay(self, frame, scene_sample):
        """Add professional text overlay to frame"""
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.7
        font_thickness = 2
        text_color = (255, 255, 255)  # White text
        bg_color = (0, 0, 0)  # Black background
        padding = 10

        # Prepare text
        timestamp_text = f"Time: {scene_sample.timestamp_unix_seconds:.3f}s"
        frame_text = f"Frame: {self.frame_count:06d}"

        # Calculate text sizes
        (ts_width, ts_height), ts_baseline = cv2.getTextSize(timestamp_text, font, font_scale, font_thickness)
        (fr_width, fr_height), fr_baseline = cv2.getTextSize(frame_text, font, font_scale, font_thickness)

        # Draw background rectangles with transparency
        overlay = frame.copy()

        # Background for timestamp (top-left)
        cv2.rectangle(overlay,
                     (5, 5),
                     (ts_width + padding * 2 + 5, ts_height + padding * 2 + 5),
                     bg_color, -1)

        # Background for frame number (below timestamp)
        cv2.rectangle(overlay,
                     (5, ts_height + padding * 3 + 5),
                     (fr_width + padding * 2 + 5, ts_height + fr_height + padding * 4 + 5),
                     bg_color, -1)

        # Apply transparency to background
        alpha = 0.7
        cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)

        # Draw text on top
        cv2.putText(frame, timestamp_text,
                   (padding + 5, ts_height + padding + 5),
                   font, font_scale, text_color, font_thickness, cv2.LINE_AA)

        cv2.putText(frame, frame_text,
                   (padding + 5, ts_height + fr_height + padding * 3 + 5),
                   font, font_scale, text_color, font_thickness, cv2.LINE_AA)

    def start_recording(self):
        """Start video recording"""
        if self.recording:
            return False

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        record_width, record_height = self.args.resolution
        target_fps = self.args.fps
        self.output_filename = os.path.join(
            self.args.output,
            f"gaze_video_{record_width}x{record_height}_{target_fps}fps_{timestamp}.mp4"
        )

        try:
            ffmpeg_cmd = [
                'ffmpeg', '-y',
                '-f', 'rawvideo',
                '-vcodec', 'rawvideo',
                '-s', f'{record_width}x{record_height}',
                '-pix_fmt', 'bgr24',
                '-r', str(target_fps),
                '-i', '-',
                '-c:v', 'libx264',
                '-pix_fmt', 'yuv420p',
                '-preset', self.args.preset,
                '-tune', 'zerolatency',
                '-crf', '23',
                self.output_filename
            ]

            self.ffmpeg_process = subprocess.Popen(
                ffmpeg_cmd,
                stdin=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=record_width * record_height * 3
            )

            self.writer_thread = threading.Thread(target=self.ffmpeg_writer_thread, daemon=True)
            self.writer_thread.start()
            self.recording = True
            self.logger.info("Recording started: %s", self.output_filename)
            return True

        except Exception as e:
            self.logger.error("Failed to start recording: %s", e)
            self.ffmpeg_process = None
            return False

    def stop_recording(self):
        """Stop video recording"""
        if not self.recording:
            return False

        self.recording = False

        if self.writer_thread and self.writer_thread.is_alive():
            self.writer_thread.join(timeout=5)

        if self.ffmpeg_process:
            try:
                self.ffmpeg_process.stdin.close()
                self.ffmpeg_process.wait(timeout=10)
            except Exception:
                pass
            self.ffmpeg_process = None

        self.logger.info("Recording stopped: %s", self.output_filename)
        return True

    def take_snapshot(self):
        """Take a snapshot"""
        try:
            scene_sample = self.device.receive_scene_video_frame()
            frame = scene_sample.bgr_pixels

            # Apply gaze overlay
            orig_height, orig_width = frame.shape[:2]
            record_width, record_height = self.args.resolution

            if orig_width != record_width or orig_height != record_height:
                frame = cv2.resize(frame, (record_width, record_height), interpolation=cv2.INTER_LINEAR)

            with self.gaze_lock:
                gaze_data = self.current_gaze

            self.draw_gaze_overlay(frame, gaze_data, record_width, record_height, orig_width, orig_height)
            self.add_text_overlay(frame, scene_sample)

            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = os.path.join(self.args.output, f"gaze_snapshot_{timestamp}.jpg")
            cv2.imwrite(filename, frame)

            self.logger.info("Snapshot saved: %s", filename)
            return filename

        except Exception as e:
            self.logger.error("Failed to take snapshot: %s", e)
            return None

    def handle_command(self, command_data):
        """Handle command from master"""
        try:
            cmd = command_data.get("command")

            if cmd == "start_recording":
                if self.start_recording():
                    self.send_status("recording_started", {"file": self.output_filename})
                else:
                    self.send_status("error", {"message": "Failed to start recording"})

            elif cmd == "stop_recording":
                if self.stop_recording():
                    self.send_status("recording_stopped", {"file": self.output_filename})
                else:
                    self.send_status("error", {"message": "Not recording"})

            elif cmd == "take_snapshot":
                filename = self.take_snapshot()
                if filename:
                    self.send_status("snapshot_taken", {"file": filename})
                else:
                    self.send_status("error", {"message": "Failed to take snapshot"})

            elif cmd == "get_status":
                status_data = {
                    "recording": self.recording,
                    "frame_count": self.frame_count,
                    "output_file": self.output_filename if self.recording else None,
                    "device_connected": self.device is not None
                }
                self.send_status("status_report", status_data)

            elif cmd == "quit":
                self.running = False
                self.should_stop.set()
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
        self.running = True
        cv2.namedWindow("Eye Tracking Recorder", cv2.WINDOW_NORMAL)

        record_width, record_height = self.args.resolution
        preview_scale = self.args.preview_width / record_width
        preview_height = int(record_height * preview_scale)

        frame_interval = 1.0 / self.args.fps
        next_frame_time = time.time()
        display_interval = 1.0 / 30
        next_display_time = time.time()

        self.logger.info("Preview mode: 'q' to quit, 's' for snapshot, 'r' to toggle recording")

        while self.running and not self.shutdown_event.is_set():
            try:
                current_time = time.time()
                scene_sample = self.device.receive_scene_video_frame()
                frame = scene_sample.bgr_pixels
                orig_height, orig_width = frame.shape[:2]

                if orig_width != record_width or orig_height != record_height:
                    frame = cv2.resize(frame, (record_width, record_height), interpolation=cv2.INTER_LINEAR)

                record_frame = frame.copy()

                with self.gaze_lock:
                    gaze_data = self.current_gaze

                self.draw_gaze_overlay(record_frame, gaze_data, record_width, record_height, orig_width, orig_height)
                self.add_text_overlay(record_frame, scene_sample)

                # Add frame to recording queue if recording
                if current_time >= next_frame_time and self.recording:
                    if self.ffmpeg_process and self.ffmpeg_process.poll() is None:
                        try:
                            self.frame_queue.put_nowait(record_frame.tobytes())
                            next_frame_time = current_time + frame_interval
                        except queue.Full:
                            pass

                # Update display
                if current_time >= next_display_time:
                    preview_frame = cv2.resize(record_frame, (self.args.preview_width, preview_height),
                                              interpolation=cv2.INTER_LINEAR)
                    cv2.imshow("Eye Tracking Recorder", preview_frame)
                    next_display_time = current_time + display_interval

                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    break
                elif key == ord('r'):
                    if not self.recording:
                        self.start_recording()
                    else:
                        self.stop_recording()
                elif key == ord('s'):
                    self.take_snapshot()

                self.frame_count += 1

            except KeyboardInterrupt:
                break
            except Exception as e:
                self.logger.error("Preview loop error: %s", e)
                continue

        cv2.destroyAllWindows()

    def slave_loop(self):
        """Command-driven slave mode (no GUI)"""
        self.running = True

        # Start command listener thread
        self.command_thread = threading.Thread(target=self.command_listener, daemon=True)
        self.command_thread.start()

        self.logger.info("Slave mode: waiting for commands...")

        # Keep device active but don't display
        while self.running and not self.shutdown_event.is_set():
            try:
                # Process frames to keep the device active
                scene_sample = self.device.receive_scene_video_frame()
                frame = scene_sample.bgr_pixels
                orig_height, orig_width = frame.shape[:2]

                record_width, record_height = self.args.resolution
                if orig_width != record_width or orig_height != record_height:
                    frame = cv2.resize(frame, (record_width, record_height), interpolation=cv2.INTER_LINEAR)

                # Add gaze overlay if recording
                if self.recording:
                    with self.gaze_lock:
                        gaze_data = self.current_gaze

                    self.draw_gaze_overlay(frame, gaze_data, record_width, record_height, orig_width, orig_height)
                    self.add_text_overlay(frame, scene_sample)

                    # Add frame to recording queue
                    if self.ffmpeg_process and self.ffmpeg_process.poll() is None:
                        try:
                            self.frame_queue.put_nowait(frame.tobytes())
                        except queue.Full:
                            pass

                    self.frame_count += 1

                # Brief sleep to prevent excessive CPU usage
                time.sleep(0.033)  # ~30 FPS update rate

            except Exception as e:
                if not self.shutdown_event.is_set():
                    self.logger.error("Slave loop error: %s", e)
                continue

        self.logger.info("Slave mode ended")

    def run(self):
        """Main run method - chooses mode based on configuration"""
        # Initialize device now that signal handlers are set up
        self._initialize_device()

        if self.slave_mode:
            self.send_status("initialized", {"device": "pupil_labs_neon"})

        # Start gaze thread
        self.gaze_thread_obj = threading.Thread(target=self.gaze_thread, daemon=True)
        self.gaze_thread_obj.start()

        if self.slave_mode:
            self.slave_loop()
        else:
            self.preview_loop()

    def cleanup(self):
        """Cleanup resources"""
        self.logger.info("Cleaning up...")
        self.should_stop.set()

        if self.recording:
            self.stop_recording()

        if self.writer_thread and self.writer_thread.is_alive():
            self.writer_thread.join(timeout=5)

        if self.device:
            self.device.close()

        cv2.destroyAllWindows()
        self.logger.info("Cleanup completed")


def parse_resolution(res_string):
    try:
        width, height = map(int, res_string.split('x'))
        return width, height
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Invalid resolution format: {res_string}. Use WIDTHxHEIGHT"
        )


def parse_args():
    parser = argparse.ArgumentParser(description='Eye tracking video recorder with gaze overlay')
    parser.add_argument('--resolution', '-r', type=parse_resolution, default=(1600, 1200),
                        help='Recording resolution (default: 1600x1200)')
    parser.add_argument('--fps', '-f', type=int, default=20,
                        help='Recording framerate (default: 20)')
    parser.add_argument('--preview-width', '-p', type=int, default=480,
                        help='Preview window width in pixels (default: 480)')
    parser.add_argument('--timeout', '-t', type=int, default=10,
                        help='Device discovery timeout in seconds (default: 10)')
    parser.add_argument('--preset', choices=['ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium'],
                        default='ultrafast', help='FFmpeg encoding preset (default: ultrafast)')
    parser.add_argument('--output', type=str, default='eye_tracking_data',
                        help='Output directory for recordings (default: eye_tracking_data)')
    parser.add_argument('--slave', action='store_true',
                        help='Run in slave mode (no preview, command-driven)')
    return parser.parse_args()


def main():
    args = parse_args()
    recorder = None
    try:
        recorder = EyeTrackerRecorder(args)
        recorder.run()
    except KeyboardInterrupt:
        logger.info("Application interrupted by user")
        if recorder and recorder.slave_mode:
            recorder.send_status("shutdown", {"reason": "user_interrupt"})
    except RuntimeError as e:
        # Device not found or initialization failed - exit gracefully
        logger.error("Runtime error: %s", e)
        if recorder and recorder.slave_mode:
            recorder.send_status("error", {"message": str(e)})
        sys.exit(1)
    except Exception as e:
        logger.error("Fatal error: %s", e, exc_info=True)
        if recorder and recorder.slave_mode:
            recorder.send_status("error", {"message": f"Fatal error: {e}"})
        sys.exit(1)
    finally:
        if recorder:
            recorder.cleanup()


if __name__ == "__main__":
    main()