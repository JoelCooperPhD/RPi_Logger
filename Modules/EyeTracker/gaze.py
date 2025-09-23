#!/usr/bin/env python3
"""
Simplified Eye Tracker recorder with hot-plug detection.
Version 2: Rolling window frame statistics (5-second window).
"""
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
import numpy as np

from pupil_labs.realtime_api.simple import discover_one_device

# Environment: suppress Qt plugin noise
os.environ['QT_LOGGING_RULES'] = 'qt.qpa.plugin=false'

# Logging setup with RTSP noise suppression
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", stream=sys.stderr)
logging.getLogger("pupil_labs.realtime_api.simple.Device.receive_data").setLevel(logging.CRITICAL)
logging.getLogger("aiortsp.rtsp.reader").setLevel(logging.CRITICAL + 1)
logging.getLogger("aiortsp").setLevel(logging.CRITICAL + 1)
logging.getLogger("pupil_labs.realtime_api").setLevel(logging.WARNING)
logging.getLogger("pupil_labs").setLevel(logging.WARNING)

# Completely silence aiortsp
aiortsp_logger = logging.getLogger("aiortsp")
aiortsp_logger.handlers = []
aiortsp_logger.propagate = False

logger = logging.getLogger("EyeTrackerSystem")

def parse_resolution(res_string):
    try:
        width, height = map(int, res_string.split('x'))
        return width, height
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid resolution format: {res_string}. Use WIDTHxHEIGHT")

def parse_args():
    parser = argparse.ArgumentParser(description='Eye tracking video recorder with gaze overlay')
    parser.add_argument('--resolution', '-r', type=parse_resolution, default=(1600, 1200),
                        help='Recording resolution (default: 1600x1200)')
    parser.add_argument('--fps', '-f', type=float, default=20,
                        help='Target recording framerate (default: 20)')
    parser.add_argument('--preview-width', '-p', type=int, default=480,
                        help='Preview window width in pixels (default: 480)')
    parser.add_argument('--preset', choices=['ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium'],
                        default='ultrafast', help='FFmpeg encoding preset (default: ultrafast)')
    parser.add_argument('--output', type=str, default='eye_tracking_data',
                        help='Output directory for recordings (default: eye_tracking_data)')
    parser.add_argument('--slave', action='store_true',
                        help='Run in slave mode (no preview, command-driven)')
    return parser.parse_args()

class EyeTrackerRecorder:
    def __init__(self, args):
        self.args = args
        self.slave_mode = args.slave

        # Device and shared data
        self.device = None
        self.current_gaze = None
        self.gaze_lock = threading.Lock()

        # Recording
        self.ffmpeg_process = None
        self.frame_queue = queue.Queue(maxsize=100)
        self.writer_thread = None
        self.recording = False
        self.output_filename = None
        self.frame_count = 0

        # Threads & control
        self.gaze_thread_obj = None
        self.command_thread = None

        # Shutdown controls
        self.should_stop = threading.Event()
        self.session_stop = threading.Event()
        self.running = False

        # Frame rate control and statistics
        self.frame_interval = 1.0 / args.fps
        self.recording_start_time = None
        self.next_frame_time = None
        self.device_frames = 0
        self.current_frame = None  # Latest device frame for temporal emission

        # Rolling window frame statistics (5 second window)
        self.frame_events = []  # List of (timestamp, event_type) tuples
        self.window_duration = 5.0  # 5 second rolling window

        # Preview display timing (always matches target fps)
        self.last_preview_time = 0
        self.next_preview_time = None

        # Ensure output directory
        os.makedirs(self.args.output, exist_ok=True)

        # Signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        if self.slave_mode:
            self.send_status("initializing", {"device": "pupil_labs_neon"})

    def _signal_handler(self, signum, frame):
        logger.info("Signal %d received -> setting shutdown flags", signum)
        self.should_stop.set()
        self.session_stop.set()
        self.running = False
        if self.slave_mode:
            self.send_status("shutdown", {"signal": signum})

    def search_for_device(self):
        """Continuous search for a device with keyboard input handling."""
        logger.info("Starting search loop for device.")
        if self.slave_mode:
            self.send_status("searching", {"device": "pupil_labs_neon"})
        else:
            print("Searching for eye tracker... (press Ctrl+C to quit)")

        # Create search window for non-slave mode
        if not self.slave_mode:
            cv2.namedWindow("Eye Tracker Search", cv2.WINDOW_NORMAL)
            cv2.resizeWindow("Eye Tracker Search", 400, 100)
            search_img = np.zeros((100, 400, 3), dtype=np.uint8)
            cv2.putText(search_img, "Searching for Eye Tracker...", (10, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(search_img, "Press Q to quit", (10, 60),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (128, 128, 128), 1)

        while not self.should_stop.is_set():
            try:
                dev = discover_one_device(max_search_duration_seconds=1)
                if dev and self.verify_device(dev):
                    logger.info("Device verified.")
                    if not self.slave_mode:
                        cv2.destroyWindow("Eye Tracker Search")
                    return dev
                elif dev:
                    dev.close()
            except Exception as e:
                logger.debug("discover_one_device exception: %s", e)

            # Handle keyboard input during search
            if not self.slave_mode:
                cv2.imshow("Eye Tracker Search", search_img)
                key = cv2.waitKey(100) & 0xFF
                if key == ord('q'):
                    logger.info("User pressed 'q' during search - quitting")
                    self.should_stop.set()
                    break
                elif key in [ord('r'), ord('s')]:
                    print("Recording/Snapshot key pressed, but no eye tracker connected - ignoring")
            else:
                time.sleep(0.1)

        if not self.slave_mode:
            cv2.destroyWindow("Eye Tracker Search")
        return None

    def verify_device(self, dev):
        """Quick device verification with longer timeouts to avoid RTSP churn."""
        attempts = 0
        max_attempts = 10
        while attempts < max_attempts and not self.should_stop.is_set():
            attempts += 1
            try:
                g = dev.receive_gaze_datum(timeout_seconds=0.5)
                if g is not None:
                    return True
            except Exception as e:
                logger.debug("verify_device gaze attempt %d failed: %s", attempts, e)
            try:
                f = dev.receive_scene_video_frame(timeout_seconds=0.5)
                if f is not None:
                    return True
            except Exception as e:
                logger.debug("verify_device frame attempt %d failed: %s", attempts, e)
            time.sleep(0.1)
        logger.warning("Device verification failed after %d attempts", attempts)
        return False

    def send_status(self, status_type, data=None):
        """Send status message in slave mode."""
        if not self.slave_mode:
            return
        message = {
            "type": "status",
            "status": status_type,
            "timestamp": datetime.datetime.now().isoformat(),
            "data": data or {}
        }
        sys.stdout.write(json.dumps(message) + "\n")
        sys.stdout.flush()

    def gaze_thread(self):
        """Continuously read gaze data."""
        consecutive_failures = 0
        while not self.should_stop.is_set() and not self.session_stop.is_set() and self.device:
            try:
                datum = self.device.receive_gaze_datum(timeout_seconds=0.1)
                if datum is not None:
                    with self.gaze_lock:
                        self.current_gaze = datum
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
                    if consecutive_failures >= 30:
                        logger.warning("Gaze thread: device disconnected")
                        self.session_stop.set()
                        break
            except Exception as e:
                logger.debug("Gaze thread exception: %s", e)
                consecutive_failures += 1
                if consecutive_failures >= 30:
                    logger.warning("Gaze thread: persistent exceptions")
                    self.session_stop.set()
                    break

    def ffmpeg_writer_thread(self):
        """Writes frames to ffmpeg stdin."""
        w, h = self.args.resolution
        expected_frame_size = w * h * 3

        while not self.should_stop.is_set() and (not self.session_stop.is_set() or not self.frame_queue.empty()):
            try:
                frame_data = self.frame_queue.get(timeout=0.05)
                if frame_data is None:
                    self.frame_queue.task_done()
                    continue

                if isinstance(frame_data, np.ndarray):
                    frame_bytes = frame_data.tobytes()
                else:
                    frame_bytes = frame_data

                if len(frame_bytes) == expected_frame_size and self.ffmpeg_process and self.ffmpeg_process.poll() is None:
                    self.ffmpeg_process.stdin.write(frame_bytes)

                self.frame_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error("Writer thread error: %s", e)
                break

    def process_frame(self, scene_sample):
        """Common frame processing for both preview and slave modes."""
        frame = scene_sample.bgr_pixels
        if frame is None:
            return None

        orig_height, orig_width = frame.shape[:2]
        record_width, record_height = self.args.resolution

        # Resize if needed
        if orig_width != record_width or orig_height != record_height:
            frame = cv2.resize(frame, (record_width, record_height), interpolation=cv2.INTER_LINEAR)

        # Add gaze overlay - this draws the fixation circle
        gaze_pos = self.draw_gaze_overlay(frame, record_width, record_height, orig_width, orig_height)

        # Add text overlay with frame statistics
        self.add_text_overlay(frame, scene_sample, gaze_pos)
        return frame

    def draw_gaze_overlay(self, frame, frame_width, frame_height, orig_width, orig_height):
        """Draw gaze fixation circle on frame."""
        with self.gaze_lock:
            gaze_data = self.current_gaze

        if gaze_data:
            gaze_x = None
            gaze_y = None

            # Try different gaze position formats
            if hasattr(gaze_data, "norm_pos") and gaze_data.norm_pos is not None:
                try:
                    nx, ny = gaze_data.norm_pos
                    gaze_x = int(nx * frame_width)
                    gaze_y = int(ny * frame_height)
                except Exception:
                    pass
            elif hasattr(gaze_data, "x") and hasattr(gaze_data, "y"):
                try:
                    gx = float(gaze_data.x)
                    gy = float(gaze_data.y)
                    if orig_width and orig_height and (orig_width != frame_width or orig_height != frame_height):
                        gaze_x = int((gx / orig_width) * frame_width)
                        gaze_y = int((gy / orig_height) * frame_height)
                    else:
                        gaze_x = int(gx)
                        gaze_y = int(gy)
                except Exception:
                    pass

            if gaze_x is not None and gaze_y is not None:
                gaze_x = max(0, min(gaze_x, frame_width - 1))
                gaze_y = max(0, min(gaze_y, frame_height - 1))
                color = (0, 0, 255) if getattr(gaze_data, "worn", False) else (0, 255, 255)
                cv2.circle(frame, (gaze_x, gaze_y), 30, color, 4)
                return gaze_x, gaze_y, getattr(gaze_data, "worn", False)

        return None, None, False

    def add_frame_event(self, event_type):
        """Add a frame event to the rolling window."""
        current_time = time.time()
        self.frame_events.append((current_time, event_type))

        # Remove events older than window duration
        cutoff_time = current_time - self.window_duration
        self.frame_events = [(t, e) for t, e in self.frame_events if t >= cutoff_time]

    def get_rolling_stats(self):
        """Get rolling window statistics."""
        if not self.frame_events:
            return 0.0, 0.0

        saved_count = sum(1 for _, event in self.frame_events if event == 'saved')
        dropped_count = sum(1 for _, event in self.frame_events if event == 'dropped')
        total_count = len(self.frame_events)

        if total_count == 0:
            return 0.0, 0.0

        saved_pct = (saved_count / total_count) * 100
        dropped_pct = (dropped_count / total_count) * 100

        return saved_pct, dropped_pct

    def add_text_overlay(self, frame, scene_sample=None, gaze_pos=None):
        """Add text overlay with frame statistics."""
        font = cv2.FONT_HERSHEY_SIMPLEX

        # Recording status
        status_text = "RECORDING" if self.recording else "NOT RECORDING"
        status_color = (0, 0, 255) if self.recording else (128, 128, 128)

        # Frame count and FPS
        frame_text = f"Frame: {self.frame_count:06d}"
        fps_text = f"Target: {self.args.fps}fps"

        # Rolling window statistics (only during recording)
        stats_text = ""
        if self.recording:
            saved_pct, dropped_pct = self.get_rolling_stats()
            stats_text = f"Saved: {saved_pct:.0f}% | Dropped: {dropped_pct:.0f}% (5s window)"

        # Controls
        help_text = "Controls: R=Record | S=Snapshot | Q=Quit"

        # Draw text with black backgrounds
        y_pos = 30
        texts = [
            (frame_text, (255, 255, 255)),
            (fps_text, (255, 255, 255)),
            (status_text, status_color)
        ]

        if stats_text:
            texts.append((stats_text, (0, 255, 255)))

        for text, color in texts:
            (text_width, text_height), _ = cv2.getTextSize(text, font, 0.7, 2)
            cv2.rectangle(frame, (5, y_pos - text_height - 5), (15 + text_width, y_pos + 5), (0, 0, 0), -1)
            cv2.putText(frame, text, (10, y_pos), font, 0.7, color, 2, cv2.LINE_AA)
            y_pos += text_height + 15

        # Help text at bottom
        frame_h, frame_w = frame.shape[:2]
        (help_width, help_height), _ = cv2.getTextSize(help_text, font, 0.5, 1)
        help_x = frame_w - help_width - 15
        help_y = frame_h - 15
        cv2.rectangle(frame, (help_x - 5, help_y - help_height - 5), (frame_w - 5, frame_h - 5), (0, 0, 0), -1)
        cv2.putText(frame, help_text, (help_x, help_y), font, 0.5, (255, 255, 255), 1, cv2.LINE_AA)

    def take_snapshot(self):
        """Take a snapshot."""
        try:
            scene_sample = self.device.receive_scene_video_frame(timeout_seconds=0.1)
            if scene_sample is None:
                logger.error("Snapshot failed: no scene frame available")
                return None

            frame = self.process_frame(scene_sample)
            if frame is None:
                logger.error("Snapshot failed: frame processing failed")
                return None

            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = os.path.join(self.args.output, f"gaze_snapshot_{timestamp}.jpg")
            cv2.imwrite(filename, frame)
            logger.info("Snapshot saved: %s", filename)
            return filename
        except Exception as e:
            logger.error("Failed to take snapshot: %s", e)
            return None

    def start_recording(self):
        """Start recording with simple frame rate control."""
        if self.recording:
            return False

        # Initialize recording statistics (timing is handled by preview loop)
        self.recording_start_time = time.time()
        # Clear frame events when starting new recording
        self.frame_events = []

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        record_width, record_height = self.args.resolution
        self.output_filename = os.path.join(self.args.output, f"gaze_video_{record_width}x{record_height}_{self.args.fps}fps_{timestamp}.mp4")

        ffmpeg_cmd = [
            'ffmpeg', '-y',
            '-f', 'rawvideo',
            '-vcodec', 'rawvideo',
            '-s', f'{record_width}x{record_height}',
            '-pix_fmt', 'bgr24',
            '-r', f'{self.args.fps}',
            '-i', '-',
            '-c:v', 'libx264',
            '-pix_fmt', 'yuv420p',
            '-preset', self.args.preset,
            '-crf', '23',
            '-r', f'{self.args.fps}',
            self.output_filename
        ]

        try:
            self.ffmpeg_process = subprocess.Popen(
                ffmpeg_cmd,
                stdin=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=record_width * record_height * 3
            )
            self.writer_thread = threading.Thread(target=self.ffmpeg_writer_thread, daemon=True)
            self.writer_thread.start()
            self.recording = True
            logger.info("Recording started: %s", self.output_filename)
            return True
        except Exception as e:
            logger.error("Failed to start recording: %s", e)
            return False

    def stop_recording(self):
        """Stop recording with background cleanup."""
        if not self.recording:
            return False

        self.recording = False
        logger.info("Recording stopping: %s", self.output_filename)

        def cleanup_recording():
            if self.writer_thread and self.writer_thread.is_alive():
                self.writer_thread.join(timeout=5)
            if self.ffmpeg_process:
                try:
                    if self.ffmpeg_process.stdin:
                        self.ffmpeg_process.stdin.close()
                    self.ffmpeg_process.wait(timeout=10)
                except Exception:
                    pass
                self.ffmpeg_process = None
            logger.info("Recording cleanup complete: %s", self.output_filename)

        cleanup_thread = threading.Thread(target=cleanup_recording, daemon=True)
        cleanup_thread.start()
        return True

    def handle_command(self, command_data):
        """Handle slave mode commands."""
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
                self.send_status("quitting")
                self.should_stop.set()
                self.session_stop.set()
                self.running = False
            else:
                self.send_status("error", {"message": f"Unknown command: {cmd}"})
        except Exception as e:
            self.send_status("error", {"message": str(e)})

    def command_listener(self):
        """Listen for commands in slave mode."""
        while not self.should_stop.is_set():
            try:
                if select.select([sys.stdin], [], [], 0.1)[0]:
                    line = sys.stdin.readline().strip()
                    if line:
                        command_data = json.loads(line)
                        self.handle_command(command_data)
            except json.JSONDecodeError as e:
                self.send_status("error", {"message": f"Invalid JSON: {e}"})
            except Exception as e:
                self.send_status("error", {"message": f"Command listener error: {e}"})
                break

    def preview_loop(self):
        """Main preview loop with frame rate control."""
        if not self.device:
            return

        self.running = True
        self.session_stop.clear()
        cv2.namedWindow("Eye Tracking Recorder", cv2.WINDOW_NORMAL)

        record_width, record_height = self.args.resolution
        # Preview shows actual recording resolution - no scaling
        logger.info(f"Preview will show recording resolution: {record_width}x{record_height} at {self.args.fps}fps")

        # Initialize preview timing to match target fps
        start_time = time.time()
        self.next_preview_time = start_time + self.frame_interval

        consecutive_failures = 0
        logger.info("Preview running ('q' to quit, 'r' toggle recording, 's' snapshot)")

        while not self.should_stop.is_set() and not self.session_stop.is_set():
            try:
                scene_sample = self.device.receive_scene_video_frame(timeout_seconds=0.1)
                if scene_sample is None:
                    consecutive_failures += 1
                    if consecutive_failures >= 40:
                        logger.warning("Preview: device disconnected")
                        self.session_stop.set()
                        break
                    time.sleep(0.01)
                    continue

                consecutive_failures = 0
                frame = self.process_frame(scene_sample)
                if frame is None:
                    continue

                # Track device frames and store latest frame
                self.device_frames += 1
                self.current_frame = frame.tobytes()  # Always store latest frame for temporal use

                # Check if it's time for next temporal frame (both preview and recording)
                current_time = time.time()
                should_display_and_emit = current_time >= self.next_preview_time

                if should_display_and_emit:
                    # Display preview at target fps
                    cv2.imshow("Eye Tracking Recorder", frame)

                    # If recording, this device frame gets saved for recording
                    if self.recording and self.ffmpeg_process and self.ffmpeg_process.poll() is None:
                        try:
                            self.frame_queue.put_nowait(self.current_frame)
                            self.add_frame_event('saved')
                        except queue.Full:
                            logger.warning("Frame queue full, dropping temporal frame")
                            self.add_frame_event('saved')  # Still counts as saved attempt from device perspective
                    elif self.recording:
                        # Recording but no valid process - count as saved attempt
                        self.add_frame_event('saved')

                    # Advance to next frame time
                    self.next_preview_time += self.frame_interval
                else:
                    # This device frame is skipped (not at temporal boundary)
                    if self.recording:
                        self.add_frame_event('dropped')

                # Handle keyboard input
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    logger.info("Preview: user 'q' -> shutdown")
                    self.should_stop.set()
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
                logger.info("Preview: KeyboardInterrupt")
                self.should_stop.set()
                break
            except Exception as e:
                logger.debug("Preview loop exception: %s", e)
                consecutive_failures += 1
                if consecutive_failures >= 40:
                    logger.warning("Preview: persistent exceptions")
                    self.session_stop.set()
                    break

        cv2.destroyAllWindows()
        self.running = False

    def slave_loop(self):
        """Slave mode loop."""
        self.running = True
        self.session_stop.clear()
        logger.info("Slave session started")
        consecutive_failures = 0

        while not self.should_stop.is_set() and not self.session_stop.is_set():
            try:
                scene_sample = self.device.receive_scene_video_frame(timeout_seconds=0.1)
                if scene_sample is None:
                    consecutive_failures += 1
                    if consecutive_failures >= 40:
                        logger.warning("Slave: device disconnected")
                        self.session_stop.set()
                        break
                    time.sleep(0.01)
                    continue

                consecutive_failures = 0

                if self.recording:
                    frame = self.process_frame(scene_sample)
                    if frame and self.ffmpeg_process and self.ffmpeg_process.poll() is None:
                        self.device_frames += 1
                        self.current_frame = frame.tobytes()

                        # Check if this device frame should be saved (temporal boundary)
                        current_time = time.time()
                        frame_saved = False
                        while current_time >= self.next_frame_time:
                            try:
                                self.frame_queue.put_nowait(self.current_frame)
                                frame_saved = True
                                self.next_frame_time += self.frame_interval
                            except queue.Full:
                                frame_saved = True  # Still counts as saved attempt
                                break

                        # Track this device frame as saved or dropped
                        if frame_saved:
                            self.add_frame_event('saved')
                        else:
                            self.add_frame_event('dropped')
                    self.frame_count += 1

                time.sleep(0.01)

            except Exception as e:
                logger.debug("Slave loop exception: %s", e)
                consecutive_failures += 1
                if consecutive_failures >= 40:
                    logger.warning("Slave: persistent exceptions")
                    self.session_stop.set()
                    break

        self.running = False
        logger.info("Slave session ended")

    def _teardown_session(self):
        """Clean up session resources."""
        logger.info("Tearing down session resources")

        if self.recording:
            logger.info("Eye tracker disconnected - automatically stopping recording")
            self.stop_recording()

        if self.writer_thread and self.writer_thread.is_alive():
            self.writer_thread.join(timeout=2)
        if self.gaze_thread_obj and self.gaze_thread_obj.is_alive():
            self.gaze_thread_obj.join(timeout=2)

        if self.device:
            try:
                self.device.close()
            except Exception:
                pass
            self.device = None

        cv2.destroyAllWindows()
        logger.info("Session teardown complete")

    def run(self):
        """Main run loop."""
        if self.slave_mode:
            self.command_thread = threading.Thread(target=self.command_listener, daemon=True)
            self.command_thread.start()

        try:
            while not self.should_stop.is_set():
                # Search for device
                dev = self.search_for_device()
                if dev is None:
                    break
                self.device = dev

                # Start gaze thread
                self.session_stop.clear()
                self.gaze_thread_obj = threading.Thread(target=self.gaze_thread, daemon=True)
                self.gaze_thread_obj.start()

                # Run session
                if self.slave_mode:
                    self.send_status("initialized", {"device": "pupil_labs_neon", "fps": self.args.fps})
                    self.slave_loop()
                else:
                    print(f"Device connected: Recording at {self.args.fps}fps")
                    self.preview_loop()

                # Teardown and loop back
                self._teardown_session()

                if self.should_stop.is_set():
                    break

                time.sleep(0.2)

        except Exception as e:
            logger.exception("Unexpected failure in run loop: %s", e)
            if self.slave_mode:
                self.send_status("error", {"message": f"Unexpected run error: {e}"})
            raise
        finally:
            self.cleanup()

    def cleanup(self):
        """Global cleanup."""
        logger.info("Global cleanup")
        self.should_stop.set()
        self.session_stop.set()

        if self.recording:
            self.stop_recording()
        if self.writer_thread and self.writer_thread.is_alive():
            self.writer_thread.join(timeout=2)
        if self.gaze_thread_obj and self.gaze_thread_obj.is_alive():
            self.gaze_thread_obj.join(timeout=2)
        if self.device:
            try:
                self.device.close()
            except Exception:
                pass
            self.device = None

        cv2.destroyAllWindows()
        logger.info("Cleanup done")

def main():
    args = parse_args()
    recorder = EyeTrackerRecorder(args)
    try:
        recorder.run()
    except KeyboardInterrupt:
        logger.info("Main: interrupted by user")
        if recorder and recorder.slave_mode:
            recorder.send_status("shutdown", {"reason": "user_interrupt"})
    except Exception as e:
        logger.exception("Fatal error: %s", e)
        if recorder and recorder.slave_mode:
            recorder.send_status("error", {"message": str(e)})
        sys.exit(1)
    finally:
        if recorder:
            recorder.cleanup()

if __name__ == "__main__":
    main()