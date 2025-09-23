import signal
import sys
import os
import cv2
import threading
import time
import subprocess
import argparse
import queue
from datetime import datetime
from pupil_labs.realtime_api.simple import discover_one_device

# Suppress Qt platform plugin warnings
os.environ['QT_LOGGING_RULES'] = 'qt.qpa.plugin=false'

# Global state
device = None
current_gaze = None
gaze_lock = threading.Lock()
ffmpeg_process = None
frame_count = 0
frame_queue = queue.Queue(maxsize=30)
writer_thread = None
should_stop = threading.Event()


def signal_handler(sig, frame):
    global ffmpeg_process, should_stop
    should_stop.set()

    if writer_thread and writer_thread.is_alive():
        writer_thread.join(timeout=5)

    if ffmpeg_process:
        try:
            ffmpeg_process.stdin.close()
            ffmpeg_process.wait()
        except Exception:
            pass

    if device:
        device.close()
    cv2.destroyAllWindows()
    sys.exit(0)


def gaze_thread():
    global current_gaze
    while not should_stop.is_set():
        try:
            if device:
                gaze = device.receive_gaze_datum()
                with gaze_lock:
                    current_gaze = gaze
        except Exception:
            if not should_stop.is_set():
                print("Error: Gaze thread failure")
            break


def ffmpeg_writer_thread():
    global ffmpeg_process
    written_frames = 0

    while not should_stop.is_set() or not frame_queue.empty():
        try:
            frame_data = frame_queue.get(timeout=0.05)
            if ffmpeg_process and ffmpeg_process.poll() is None:
                try:
                    ffmpeg_process.stdin.write(frame_data)
                    written_frames += 1
                except Exception:
                    break
            frame_queue.task_done()
        except queue.Empty:
            continue
        except Exception:
            print("Error: Writer thread failure")
            break


def parse_resolution(res_string):
    try:
        width, height = map(int, res_string.split('x'))
        return width, height
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Invalid resolution format: {res_string}. Use WIDTHxHEIGHT"
        )


def draw_gaze_overlay(frame, gaze_data, frame_width, frame_height, orig_width, orig_height):
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


def main():
    parser = argparse.ArgumentParser(description='Eye tracking video recorder with gaze overlay')
    parser.add_argument('--resolution', '-r', type=parse_resolution, default=(1600, 1200))
    parser.add_argument('--fps', '-f', type=int, default=20)
    parser.add_argument('--preview-width', '-p', type=int, default=480)
    parser.add_argument('--timeout', '-t', type=int, default=10)
    parser.add_argument('--preset', choices=['ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium'],
                        default='ultrafast')

    args = parser.parse_args()

    record_width, record_height = args.resolution
    target_fps = args.fps
    preview_width = args.preview_width
    discovery_timeout = args.timeout
    encoding_preset = args.preset

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    global device, ffmpeg_process, frame_count, writer_thread

    try:
        device = discover_one_device(max_search_duration_seconds=discovery_timeout)
        if device is None:
            print("Error: No device found")
            raise SystemExit()

        gaze_thread_obj = threading.Thread(target=gaze_thread, daemon=True)
        gaze_thread_obj.start()

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = "./eye_tracking_data"
        os.makedirs(output_dir, exist_ok=True)
        output_filename = f"{output_dir}/gaze_video_{record_width}x{record_height}_{target_fps}fps_{timestamp}.mp4"

        cv2.namedWindow("Eye Tracking Recorder", cv2.WINDOW_NORMAL)

        preview_scale = None
        frame_interval = 1.0 / target_fps
        next_frame_time = time.time()
        display_interval = 1.0 / 30
        next_display_time = time.time()
        current_fps = 0

        while True:
            try:
                current_time = time.time()
                scene_sample = device.receive_scene_video_frame()
                frame = scene_sample.bgr_pixels
                orig_height, orig_width = frame.shape[:2]

                if orig_width != record_width or orig_height != record_height:
                    frame = cv2.resize(frame, (record_width, record_height), interpolation=cv2.INTER_LINEAR)
                    frame_height, frame_width = record_height, record_width
                else:
                    frame_height, frame_width = orig_height, orig_width

                if ffmpeg_process is None:
                    try:
                        ffmpeg_cmd = [
                            'ffmpeg', '-y',
                            '-f', 'rawvideo',
                            '-vcodec', 'rawvideo',
                            '-s', f'{frame_width}x{frame_height}',
                            '-pix_fmt', 'bgr24',
                            '-r', str(target_fps),
                            '-i', '-',
                            '-c:v', 'libx264',
                            '-pix_fmt', 'yuv420p',
                            '-preset', encoding_preset,
                            '-tune', 'zerolatency',
                            '-crf', '23',
                            output_filename
                        ]

                        ffmpeg_process = subprocess.Popen(
                            ffmpeg_cmd,
                            stdin=subprocess.PIPE,
                            stderr=subprocess.DEVNULL,  # silence FFmpeg progress
                            bufsize=frame_width * frame_height * 3
                        )

                        writer_thread = threading.Thread(target=ffmpeg_writer_thread, daemon=True)
                        writer_thread.start()
                        print("Recording started.")

                    except Exception:
                        print("Error: Failed to start FFmpeg")
                        ffmpeg_process = None

                if preview_scale is None:
                    preview_scale = preview_width / frame_width
                    preview_height = int(frame_height * preview_scale)

                record_frame = frame.copy()

                with gaze_lock:
                    gaze_data = current_gaze

                gaze_x, gaze_y, worn = draw_gaze_overlay(
                    record_frame, gaze_data, frame_width, frame_height, orig_width, orig_height
                )

                # Professional text overlay with dark background for visibility
                font = cv2.FONT_HERSHEY_SIMPLEX
                font_scale = 0.7
                font_thickness = 2
                text_color = (255, 255, 255)  # White text
                bg_color = (0, 0, 0)  # Black background
                padding = 10
                
                # Prepare text
                timestamp_text = f"Time: {scene_sample.timestamp_unix_seconds:.3f}s"
                frame_text = f"Frame: {frame_count:06d}"
                
                # Calculate text sizes
                (ts_width, ts_height), ts_baseline = cv2.getTextSize(timestamp_text, font, font_scale, font_thickness)
                (fr_width, fr_height), fr_baseline = cv2.getTextSize(frame_text, font, font_scale, font_thickness)
                
                # Draw background rectangles with transparency
                overlay = record_frame.copy()
                
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
                cv2.addWeighted(overlay, alpha, record_frame, 1 - alpha, 0, record_frame)
                
                # Draw text on top
                cv2.putText(record_frame, timestamp_text, 
                           (padding + 5, ts_height + padding + 5),
                           font, font_scale, text_color, font_thickness, cv2.LINE_AA)
                
                cv2.putText(record_frame, frame_text, 
                           (padding + 5, ts_height + fr_height + padding * 3 + 5),
                           font, font_scale, text_color, font_thickness, cv2.LINE_AA)

                if current_time >= next_frame_time:
                    if ffmpeg_process and ffmpeg_process.poll() is None:
                        try:
                            frame_queue.put_nowait(record_frame.tobytes())
                            next_frame_time = current_time + frame_interval
                        except queue.Full:
                            pass

                if current_time >= next_display_time:
                    preview_frame = cv2.resize(record_frame, (preview_width, int(frame_height * preview_scale)),
                                              interpolation=cv2.INTER_LINEAR)
                    cv2.imshow("Eye Tracking Recorder", preview_frame)
                    next_display_time = current_time + display_interval

                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    break

                frame_count += 1

            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"Error: {e}")
                continue

    finally:
        should_stop.set()
        if writer_thread and writer_thread.is_alive():
            writer_thread.join(timeout=5)
        if ffmpeg_process:
            try:
                ffmpeg_process.stdin.close()
                ffmpeg_process.wait(timeout=10)
            except Exception:
                pass
        if device:
            device.close()
        cv2.destroyAllWindows()
        print("Recording complete.")


if __name__ == "__main__":
    main()
