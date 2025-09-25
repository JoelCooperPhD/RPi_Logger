#!/usr/bin/env python3
"""
Gaze Tracker using Correct Async API
Uses the proper RTSP streaming functions with correct URLs.
"""

import asyncio
import time
import datetime
import os
from dataclasses import dataclass
from typing import Optional
import cv2
import numpy as np
import subprocess
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Suppress unwanted loggers
for logger_name in ['pupil_labs', 'aiortsp', 'websockets', 'aiohttp']:
    logging.getLogger(logger_name).setLevel(logging.ERROR)

# Import correct async API functions
from pupil_labs.realtime_api.discovery import discover_devices
from pupil_labs.realtime_api import receive_video_frames, receive_gaze_data
from pupil_labs.realtime_api.device import Device


@dataclass
class Config:
    """Configuration for gaze tracker"""
    fps: float = 30.0
    resolution: tuple = (1280, 720)
    output_dir: str = "video_out"
    display_width: int = 640


class CorrectAsyncGazeTracker:
    """Gaze tracker using correct async API with RTSP streaming"""

    def __init__(self, config: Config):
        self.config = config
        self.device: Optional[Device] = None
        self.device_ip = None
        self.device_port = None
        self.running = False

        # Recording state
        self.recording = False
        self.ffmpeg_process = None
        self.recording_filename = None

        # Stats
        self.frame_count = 0
        self.camera_frames = 0
        self.start_time = None
        self.duplicates = 0

        # Current data
        self.last_frame = None
        self.last_gaze = None

        # Tasks
        self.tasks = []

        # Ensure output directory exists
        os.makedirs(config.output_dir, exist_ok=True)

    async def connect(self) -> bool:
        """Connect to eye tracker using async discovery"""
        logger.info("Searching for eye tracker device...")

        try:
            # Discover devices
            async for device_info in discover_devices(timeout_seconds=5.0):
                logger.info(f"Found device: {device_info.name}")

                # Store connection info
                self.device_ip = device_info.addresses[0]
                self.device_port = device_info.port

                # Create device for control operations
                self.device = Device.from_discovered_device(device_info)

                logger.info(f"Connected to device at {self.device_ip}:{self.device_port}")
                return True

            logger.error("No devices found")
            return False

        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False

    async def run(self):
        """Main processing loop"""
        if not self.device or not self.device_ip:
            logger.error("No device connected")
            return

        self.running = True
        self.start_time = time.time()

        # Create OpenCV window
        cv2.namedWindow("Gaze Tracker", cv2.WINDOW_NORMAL)
        logger.info("Starting gaze tracker - Press Q to quit, R to toggle recording")

        try:
            # Construct RTSP URLs
            # The pattern seems to be rtsp://ip:port/?camera=world for video
            # and rtsp://ip:port/?camera=gaze for gaze data
            base_port = 8086  # RTSP port is typically different from HTTP port
            video_url = f"rtsp://{self.device_ip}:{base_port}/?camera=world"
            gaze_url = f"rtsp://{self.device_ip}:{base_port}/?camera=gaze"

            logger.info(f"Video URL: {video_url}")
            logger.info(f"Gaze URL: {gaze_url}")

            # Create streaming tasks
            self.tasks = [
                asyncio.create_task(self._stream_video_frames(video_url)),
                asyncio.create_task(self._stream_gaze_data(gaze_url)),
                asyncio.create_task(self._process_frames()),
            ]

            # Wait for all tasks (they run until cancelled)
            await asyncio.gather(*self.tasks, return_exceptions=True)

        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        except Exception as e:
            logger.error(f"Runtime error: {e}")
        finally:
            await self.cleanup()

    async def _stream_video_frames(self, video_url: str):
        """Continuously stream video frames using correct API"""
        logger.info("Starting video stream...")

        frame_count = 0
        try:
            async for frame in receive_video_frames(video_url):
                if not self.running:
                    break

                frame_count += 1
                if frame_count == 1:
                    logger.info("First video frame received!")
                    logger.info(f"Video frame type: {type(frame)}")
                    logger.info(f"Video frame attributes: {[attr for attr in dir(frame) if not attr.startswith('_')]}")

                if frame:
                    try:
                        # Simply use to_ndarray() method - this is the standard way
                        pixel_data = frame.to_ndarray()

                        if pixel_data is not None:
                            self.camera_frames += 1
                            self.last_frame = pixel_data  # Use frame directly without extraction

                            if self.camera_frames == 1:
                                logger.info(f"Frame shape: {pixel_data.shape}")
                                logger.info(f"Frame dtype: {pixel_data.dtype}")

                                # Check if it's grayscale or color
                                if len(pixel_data.shape) == 3:
                                    logger.info(f"Color channels: {pixel_data.shape[2]}")
                                    # Sample pixel to see values
                                    if pixel_data.shape[0] > 100 and pixel_data.shape[1] > 100:
                                        sample = pixel_data[100, 100]
                                        logger.info(f"Sample pixel: {sample}")
                                else:
                                    logger.info("Grayscale frame detected")

                            elif self.camera_frames % 30 == 1:  # Log every 30 frames
                                logger.info(f"Video frames received: {self.camera_frames}")
                        else:
                            if frame_count <= 5:
                                logger.warning(f"Frame {frame_count}: to_ndarray() returned None")

                    except Exception as e:
                        if frame_count <= 5:
                            logger.error(f"Frame {frame_count}: Error getting pixel data: {e}")

        except Exception as e:
            if self.running:
                logger.error(f"Video stream error: {e}")

    async def _stream_gaze_data(self, gaze_url: str):
        """Continuously stream gaze data using correct API"""
        logger.info("Starting gaze stream...")

        gaze_count = 0
        try:
            async for gaze in receive_gaze_data(gaze_url):
                if not self.running:
                    break

                gaze_count += 1
                if gaze_count == 1:
                    logger.info("First gaze data received!")
                    logger.info(f"Gaze data type: {type(gaze)}")
                    logger.info(f"Gaze data attributes: {[attr for attr in dir(gaze) if not attr.startswith('_')]}")

                self.last_gaze = gaze

                if gaze_count % 100 == 1:  # Log every 100 gaze samples
                    logger.info(f"Gaze samples received: {gaze_count}")

        except Exception as e:
            if self.running:
                logger.error(f"Gaze stream error: {e}")

    def _process_frame(self, raw_frame: np.ndarray) -> np.ndarray:
        """Process frame to extract scene camera and ensure proper format for OpenCV display"""
        try:
            # Check if this is a tiled frame (scene + eye cameras)
            h, w = raw_frame.shape[:2]

            # Log frame info once
            if not hasattr(self, '_logged_frame_info'):
                logger.info(f"Raw frame shape: {raw_frame.shape}")
                if len(raw_frame.shape) == 3:
                    logger.info(f"Channels: {raw_frame.shape[2]}")
                self._logged_frame_info = True

            # If the frame has the expected tiled layout (scene camera on top, eye cameras below)
            # The scene camera typically takes up the top portion
            scene_frame = raw_frame

            # If height is significantly larger than width, it's likely tiled vertically
            # Scene camera is typically on top
            if h > w * 1.1:  # Height is larger than width - likely tiled
                # Extract top portion (scene camera)
                # Typically the scene camera is about 2/3 of the total height
                scene_height = h * 2 // 3
                scene_frame = raw_frame[:scene_height, :].copy()

                if not hasattr(self, '_logged_extraction'):
                    logger.info(f"Extracting scene camera from tiled frame")
                    logger.info(f"Original: {h}x{w}, Scene: {scene_frame.shape}")
                    self._logged_extraction = True

            # Handle different color formats
            if len(scene_frame.shape) == 2:  # Grayscale
                # The Pupil Labs scene camera appears to be monochrome
                # Convert grayscale to BGR for OpenCV display
                processed_frame = cv2.cvtColor(scene_frame, cv2.COLOR_GRAY2BGR)

                if not hasattr(self, '_logged_color_info'):
                    logger.info("Scene camera is grayscale/monochrome - this is normal for Pupil Labs devices")
                    self._logged_color_info = True

            elif len(scene_frame.shape) == 3:
                if scene_frame.shape[2] == 1:  # Single channel in 3D array
                    processed_frame = cv2.cvtColor(scene_frame.squeeze(), cv2.COLOR_GRAY2BGR)
                elif scene_frame.shape[2] == 3:  # Already 3 channels
                    # Assume it's RGB and convert to BGR for OpenCV
                    processed_frame = cv2.cvtColor(scene_frame, cv2.COLOR_RGB2BGR)
                elif scene_frame.shape[2] == 4:  # RGBA
                    processed_frame = cv2.cvtColor(scene_frame, cv2.COLOR_RGBA2BGR)
                else:
                    logger.warning(f"Unexpected channel count: {scene_frame.shape[2]}")
                    processed_frame = scene_frame
            else:
                logger.warning(f"Unexpected scene frame shape: {scene_frame.shape}")
                processed_frame = scene_frame

            return processed_frame

        except Exception as e:
            logger.error(f"Error processing frame: {e}")
            # Return original frame if processing fails
            return raw_frame

    async def _process_frames(self):
        """Process frames at target FPS"""
        frame_interval = 1.0 / self.config.fps
        next_frame_time = time.time()
        no_frame_count = 0

        while self.running:
            try:
                # Wait for precise timing
                current_time = time.time()
                if current_time < next_frame_time:
                    await asyncio.sleep(next_frame_time - current_time)

                # Process frame if we have one
                if self.last_frame is not None:
                    self.frame_count += 1
                    no_frame_count = 0  # Reset counter

                    # Process frame to ensure proper format
                    processed_frame = self._process_frame(self.last_frame)

                    # Add overlays
                    display_frame = self._add_overlays(processed_frame.copy())

                    # Handle recording
                    if self.recording and self.ffmpeg_process:
                        self._write_frame_to_ffmpeg(display_frame)

                    # Display
                    self._display_frame(display_frame)

                    # Handle keyboard
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord('q'):
                        logger.info("Quit requested")
                        self.running = False
                    elif key == ord('r'):
                        await self._toggle_recording()
                else:
                    self.duplicates += 1
                    no_frame_count += 1

                    # Log if we haven't received frames for a while
                    if no_frame_count == 30:  # After 1 second at 30fps
                        logger.warning("No frames received for 1 second")
                    elif no_frame_count == 150:  # After 5 seconds
                        logger.warning("No frames received for 5 seconds - check device connection")

                # Update next frame time
                next_frame_time += frame_interval

                # Reset timing if we've fallen too far behind
                if time.time() - next_frame_time > 1.0:
                    next_frame_time = time.time() + frame_interval

            except Exception as e:
                logger.error(f"Frame processing error: {e}")
                if not self.running:
                    break

    def _add_overlays(self, frame: np.ndarray) -> np.ndarray:
        """Add overlays to frame"""
        h, w = frame.shape[:2]
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.6
        thickness = 2

        # Background for text
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (w, 120), (0, 0, 0), -1)
        frame = cv2.addWeighted(frame, 0.7, overlay, 0.3, 0)

        # Timestamp
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(frame, f"Time: {timestamp}", (10, 25),
                   font, font_scale, (255, 255, 255), thickness)

        # Stats
        if self.start_time:
            elapsed = time.time() - self.start_time
            camera_fps = self.camera_frames / elapsed if elapsed > 0 else 0
            display_fps = self.frame_count / elapsed if elapsed > 0 else 0

            cv2.putText(frame, f"Camera FPS: {camera_fps:.1f}", (10, 50),
                       font, font_scale, (0, 255, 255), thickness)
            cv2.putText(frame, f"Display FPS: {display_fps:.1f}", (10, 75),
                       font, font_scale, (0, 255, 255), thickness)
            cv2.putText(frame, f"Frames: {self.frame_count}", (10, 100),
                       font, font_scale, (0, 255, 255), thickness)

        # Recording status
        if self.recording:
            cv2.putText(frame, "RECORDING", (w - 150, 30),
                       font, font_scale, (0, 0, 255), thickness)

        # Gaze circle
        if self.last_gaze:
            gaze_x, gaze_y = None, None

            # Debug gaze data once
            if not hasattr(self, '_logged_gaze_debug'):
                logger.info(f"Gaze x: {getattr(self.last_gaze, 'x', 'None')}, y: {getattr(self.last_gaze, 'y', 'None')}")
                if hasattr(self.last_gaze, 'x') and hasattr(self.last_gaze, 'y'):
                    logger.info(f"Raw gaze coordinates: x={self.last_gaze.x}, y={self.last_gaze.y}")
                    logger.info(f"Frame dimensions: {w}x{h}")
                self._logged_gaze_debug = True

            # Try different gaze data formats
            if hasattr(self.last_gaze, 'x') and hasattr(self.last_gaze, 'y'):
                try:
                    # The gaze coordinates should be normalized (0-1)
                    # BUT they might be in original camera resolution, so check values
                    raw_x = float(self.last_gaze.x)
                    raw_y = float(self.last_gaze.y)

                    # If values are > 1, they're likely in pixel coordinates
                    if raw_x > 1.0 or raw_y > 1.0:
                        # Gaze coordinates are in original full frame coordinates (1600x1800)
                        # Our scene frame is extracted from top 2/3 of the original frame
                        # Original full frame: 1600w x 1800h
                        # Our scene frame: 1600w x 1200h (top 2/3)

                        # X coordinate scales directly (same width)
                        gaze_x = int((raw_x / 1600.0) * w)

                        # Y coordinate needs special handling for scene extraction
                        # The scene camera is in the top 2/3 of the full frame
                        # So gaze Y coordinates 0-1200 map to our scene frame
                        scene_y_in_full_frame = raw_y
                        if scene_y_in_full_frame <= 1200:  # Within scene camera area
                            gaze_y = int((scene_y_in_full_frame / 1200.0) * h)
                        else:
                            # Gaze is in the eye camera area (bottom 1/3), clamp to bottom
                            gaze_y = h - 1
                    else:
                        # Already normalized coordinates (0-1)
                        gaze_x = int(raw_x * w)
                        gaze_y = int(raw_y * h)

                except Exception as e:
                    if not hasattr(self, '_logged_gaze_error'):
                        logger.error(f"Gaze coordinate error: {e}")
                        self._logged_gaze_error = True

            if gaze_x is not None and gaze_y is not None:
                # Clamp to frame bounds
                gaze_x = max(0, min(gaze_x, w - 1))
                gaze_y = max(0, min(gaze_y, h - 1))

                # Use BGR color format (Blue, Green, Red)
                # Yellow = (0, 255, 255) in BGR
                # Red = (0, 0, 255) in BGR
                color = (0, 255, 255)  # Yellow for worn
                if hasattr(self.last_gaze, 'worn') and not self.last_gaze.worn:
                    color = (0, 0, 255)  # Red if not worn

                cv2.circle(frame, (gaze_x, gaze_y), 30, color, 3)
                cv2.circle(frame, (gaze_x, gaze_y), 2, color, -1)

        # Help text
        cv2.putText(frame, "Q: Quit | R: Record", (w - 200, h - 10),
                   font, 0.5, (255, 255, 255), 1)

        return frame

    def _display_frame(self, frame: np.ndarray):
        """Display frame with resize"""
        h, w = frame.shape[:2]
        aspect = h / w
        display_h = int(self.config.display_width * aspect)
        resized = cv2.resize(frame, (self.config.display_width, display_h))
        cv2.imshow("Gaze Tracker", resized)

    async def _toggle_recording(self):
        """Toggle recording on/off"""
        if self.recording:
            await self._stop_recording()
        else:
            await self._start_recording()

    async def _start_recording(self):
        """Start FFmpeg recording"""
        if self.recording:
            return

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        w, h = self.config.resolution
        self.recording_filename = os.path.join(
            self.config.output_dir,
            f"gaze_{w}x{h}_{self.config.fps}fps_{timestamp}.mp4"
        )

        ffmpeg_cmd = [
            'ffmpeg', '-y',
            '-f', 'rawvideo',
            '-vcodec', 'rawvideo',
            '-s', f'{w}x{h}',
            '-pix_fmt', 'bgr24',
            '-r', str(self.config.fps),
            '-i', '-',
            '-c:v', 'libx264',
            '-preset', 'ultrafast',
            '-crf', '23',
            self.recording_filename
        ]

        try:
            self.ffmpeg_process = subprocess.Popen(
                ffmpeg_cmd,
                stdin=subprocess.PIPE,
                stderr=subprocess.DEVNULL
            )
            self.recording = True
            logger.info(f"Recording started: {self.recording_filename}")
        except Exception as e:
            logger.error(f"Failed to start recording: {e}")

    async def _stop_recording(self):
        """Stop FFmpeg recording"""
        if not self.recording:
            return

        self.recording = False

        if self.ffmpeg_process:
            try:
                self.ffmpeg_process.stdin.close()
                self.ffmpeg_process.wait(timeout=5)
            except:
                self.ffmpeg_process.terminate()
            finally:
                self.ffmpeg_process = None

        logger.info(f"Recording saved: {self.recording_filename}")

    def _write_frame_to_ffmpeg(self, frame: np.ndarray):
        """Write frame to FFmpeg process"""
        if not self.ffmpeg_process or self.ffmpeg_process.poll() is not None:
            return

        # Resize to recording resolution
        w, h = self.config.resolution
        if frame.shape[:2] != (h, w):
            frame = cv2.resize(frame, (w, h))

        try:
            self.ffmpeg_process.stdin.write(frame.tobytes())
            self.ffmpeg_process.stdin.flush()
        except:
            pass

    async def cleanup(self):
        """Clean up resources"""
        logger.info("Cleaning up...")

        # Stop processing
        self.running = False

        # Cancel all tasks
        for task in self.tasks:
            if not task.done():
                task.cancel()

        # Wait briefly for tasks to finish
        await asyncio.sleep(0.5)

        # Stop recording
        if self.recording:
            await self._stop_recording()

        # Close device
        if self.device:
            try:
                await self.device.close()
            except:
                pass
            self.device = None

        # Close OpenCV windows
        cv2.destroyAllWindows()

        logger.info("Cleanup complete")


async def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description='Correct Async Gaze Tracker')
    parser.add_argument('--fps', type=float, default=30.0, help='Target FPS')
    parser.add_argument('--resolution', type=str, default='1280x720', help='Resolution')
    parser.add_argument('--output', type=str, default='video_out', help='Output directory')
    parser.add_argument('--display-width', type=int, default=640, help='Display width')

    args = parser.parse_args()

    # Parse resolution
    try:
        w, h = map(int, args.resolution.split('x'))
    except:
        logger.error("Invalid resolution format")
        return

    config = Config(
        fps=args.fps,
        resolution=(w, h),
        output_dir=args.output,
        display_width=args.display_width
    )

    tracker = CorrectAsyncGazeTracker(config)

    if await tracker.connect():
        await tracker.run()
    else:
        logger.error("Failed to connect to device")


if __name__ == "__main__":
    asyncio.run(main())