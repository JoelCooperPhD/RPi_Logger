#!/usr/bin/env python3
"""
Camera Module for Raspberry Pi Logger

A comprehensive camera module supporting high-quality video recording with real-time preview,
timestamp overlays, and flexible control options. Designed for Raspberry Pi systems with
libcamera-compatible cameras.

Features:
- Real-time preview window with timestamp overlay (default)
- Interactive controls during recording (q=quit, s=snapshot)
- High-quality H.264 video encoding
- Automatic timestamp embedding in video
- IPC support for subprocess communication
- Configurable resolution and frame rate
- Headless operation mode

Compatible Hardware:
- All Raspberry Pi camera modules (V1, V2, V3, HQ, Global Shutter)
- Raspberry Pi 4, 5, and compatible boards
- USB cameras (limited support)

Usage Examples:
    # Record with preview (default)
    python camera_module.py --duration 30

    # Record without preview (headless)
    python camera_module.py --duration 30 --no-preview

    # High resolution recording
    python camera_module.py --resolution 3840x2160 --fps 24

    # Interactive mode (record until 'q' pressed)
    python camera_module.py

Requirements:
- picamera2
- opencv-python
- numpy
- libcamera
"""

import asyncio
import argparse
import json
import sys
import signal
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, Dict, Any
import numpy as np
from io import BytesIO

from picamera2 import Picamera2, Preview
from picamera2.encoders import H264Encoder, MJPEGEncoder, Quality
from picamera2.outputs import FileOutput, CircularOutput
from libcamera import controls, Transform
import cv2

class CameraModule:
    """Async camera module with timestamp overlay and IPC support."""

    def __init__(self,
                 resolution: Tuple[int, int] = (1920, 1080),
                 fps: int = 30,
                 save_location: str = "./recordings",
                 camera_id: int = 0,
                 use_ipc: bool = False,
                 show_preview: bool = True):
        """
        Initialize the camera module.

        Args:
            resolution: Video resolution (width, height)
            fps: Frames per second
            save_location: Directory for saved recordings
            camera_id: Camera index (0 or 1 for Pi 5)
            use_ipc: Whether to use pipe-based IPC
            show_preview: Whether to show live preview during recording (default True)
        """
        self.resolution = resolution
        self.fps = fps
        self.save_location = Path(save_location)
        self.camera_id = camera_id
        self.use_ipc = use_ipc
        self.show_preview = show_preview and not use_ipc  # No preview in IPC mode

        # Create save directory if it doesn't exist
        self.save_location.mkdir(parents=True, exist_ok=True)

        # Initialize camera
        self.picam2: Optional[Picamera2] = None
        self.encoder: Optional[H264Encoder] = None
        self.output: Optional[FileOutput] = None
        self.circular_buffer: Optional[CircularOutput] = None

        # Control flags
        self.recording = False
        self.preview_enabled = False
        self.preview_window_open = False
        self.shutdown_event = asyncio.Event()

        # Setup logging
        self.setup_logging()

        # IPC communication queues
        self.command_queue: asyncio.Queue = asyncio.Queue()
        self.response_queue: asyncio.Queue = asyncio.Queue()

    def setup_logging(self):
        """Configure logging based on operation mode."""
        level = logging.INFO if not self.use_ipc else logging.WARNING
        logging.basicConfig(
            level=level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        self.logger = logging.getLogger(__name__)

    async def initialize_camera(self):
        """Initialize and configure the camera."""
        try:
            # Check available cameras
            cameras = Picamera2.global_camera_info()
            if self.camera_id >= len(cameras):
                raise ValueError(f"Camera {self.camera_id} not found. Available: {cameras}")

            self.logger.info(f"Initializing camera {self.camera_id}: {cameras[self.camera_id]}")

            # Create camera instance
            self.picam2 = Picamera2(self.camera_id)

            # Create configuration optimized for video
            config = self.picam2.create_video_configuration(
                main={"size": self.resolution, "format": "RGB888"},
                lores={"size": (640, 480), "format": "YUV420"},  # Low-res stream for preview
                encode="main",
                buffer_count=6,  # Increase buffers for smooth recording
                queue=True,
                controls={
                    "FrameRate": self.fps,
                    "ExposureTime": 0,  # Auto exposure
                    "AnalogueGain": 1.0,
                    "ColourGains": (0, 0),  # Auto white balance
                }
            )

            # Apply configuration
            self.picam2.configure(config)

            # Setup encoder for H264 video
            self.encoder = H264Encoder(bitrate=10000000, repeat=True, iperiod=30)
            self.encoder.quality = Quality.HIGH

            # Setup circular buffer for pre-event recording (5 seconds)
            buffer_size = self.fps * 5 * self.resolution[0] * self.resolution[1] * 3
            self.circular_buffer = CircularOutput(buffersize=buffer_size)

            self.logger.info(f"Camera initialized: {self.resolution}@{self.fps}fps")

        except Exception as e:
            self.logger.error(f"Failed to initialize camera: {e}")
            raise

    def add_timestamp_overlay(self, request):
        """
        Add timestamp overlay to the frame.
        Called for each frame via the pre_callback.
        """
        try:
            # Get the current timestamp at frame capture
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

            # Get the main buffer as numpy array directly from request
            array = request.make_array("main")

            # Overlay parameters
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.8
            color = (255, 255, 255)  # White
            thickness = 2
            position = (10, 30)  # Upper left corner

            # Add black background for better visibility
            (text_width, text_height), baseline = cv2.getTextSize(
                timestamp, font, font_scale, thickness
            )
            cv2.rectangle(
                array,
                (position[0] - 5, position[1] - text_height - 5),
                (position[0] + text_width + 5, position[1] + baseline + 5),
                (0, 0, 0),
                -1
            )

            # Add timestamp text
            cv2.putText(
                array,
                timestamp,
                position,
                font,
                font_scale,
                color,
                thickness,
                cv2.LINE_AA
            )

        except Exception as e:
            self.logger.warning(f"Failed to add timestamp overlay: {e}")

    async def start_camera(self):
        """Start the camera."""
        try:
            # Set pre-callback for timestamp overlay
            self.picam2.pre_callback = self.add_timestamp_overlay

            # Start the camera
            self.picam2.start()
            self.logger.info("Camera started")

            # Initialize OpenCV window if preview is enabled
            if self.show_preview:
                cv2.namedWindow("Camera Feed", cv2.WINDOW_NORMAL)
                cv2.resizeWindow("Camera Feed", 960, 540)  # Half resolution for display
                self.preview_window_open = True
                self.logger.info("Preview window opened")

            # Allow camera to stabilize
            await asyncio.sleep(1)

        except Exception as e:
            self.logger.error(f"Failed to start camera: {e}")
            raise

    async def start_recording(self, filename: Optional[str] = None) -> str:
        """
        Start recording video to file.

        Args:
            filename: Optional filename, auto-generated if not provided

        Returns:
            Path to the recording file
        """
        if self.recording:
            self.logger.warning("Already recording")
            return self.current_recording_path

        try:
            # Generate filename if not provided
            if filename is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"recording_{timestamp}.h264"

            filepath = self.save_location / filename
            self.current_recording_path = str(filepath)

            # Create file output
            self.output = FileOutput(str(filepath))

            # Start encoder with output
            self.picam2.start_encoder(self.encoder, [self.output])
            self.recording = True

            self.logger.info(f"Started recording to {filepath}")
            return self.current_recording_path

        except Exception as e:
            self.logger.error(f"Failed to start recording: {e}")
            raise

    async def stop_recording(self):
        """Stop recording video."""
        if not self.recording:
            self.logger.warning("Not recording")
            return

        try:
            self.picam2.stop_encoder()
            self.recording = False

            if self.output:
                self.output.close()
                self.output = None

            self.logger.info(f"Stopped recording: {self.current_recording_path}")

        except Exception as e:
            self.logger.error(f"Failed to stop recording: {e}")

    async def capture_image(self, filename: Optional[str] = None) -> str:
        """
        Capture a still image.

        Args:
            filename: Optional filename, auto-generated if not provided

        Returns:
            Path to the captured image
        """
        try:
            # Generate filename if not provided
            if filename is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                filename = f"capture_{timestamp}.jpg"

            filepath = self.save_location / filename

            # Switch to still configuration for high quality
            still_config = self.picam2.create_still_configuration(
                main={"size": self.picam2.camera_properties['PixelArraySize']}
            )
            self.picam2.switch_mode_and_capture_file(still_config, str(filepath))

            self.logger.info(f"Captured image: {filepath}")
            return str(filepath)

        except Exception as e:
            self.logger.error(f"Failed to capture image: {e}")
            raise

    async def handle_ipc_commands(self):
        """Handle commands received via IPC."""
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

        writer_transport, writer_protocol = await asyncio.get_event_loop().connect_write_pipe(
            asyncio.streams.FlowControlMixin, sys.stdout
        )
        writer = asyncio.StreamWriter(writer_transport, writer_protocol, reader, asyncio.get_event_loop())

        while not self.shutdown_event.is_set():
            try:
                # Read command from stdin
                line = await asyncio.wait_for(reader.readline(), timeout=0.1)
                if not line:
                    continue

                command = json.loads(line.decode().strip())
                self.logger.debug(f"Received command: {command}")

                response = await self.process_command(command)

                # Send response via stdout
                response_json = json.dumps(response) + '\n'
                writer.write(response_json.encode())
                await writer.drain()

            except asyncio.TimeoutError:
                continue
            except json.JSONDecodeError as e:
                self.logger.error(f"Invalid JSON command: {e}")
            except Exception as e:
                self.logger.error(f"IPC error: {e}")

    async def process_command(self, command: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process IPC command and return response.

        Args:
            command: Command dictionary with 'action' and optional 'params'

        Returns:
            Response dictionary with 'status' and optional 'data'
        """
        action = command.get('action')
        params = command.get('params', {})

        try:
            if action == 'start_recording':
                path = await self.start_recording(params.get('filename'))
                return {'status': 'success', 'data': {'path': path}}

            elif action == 'stop_recording':
                await self.stop_recording()
                return {'status': 'success'}

            elif action == 'capture_image':
                path = await self.capture_image(params.get('filename'))
                return {'status': 'success', 'data': {'path': path}}

            elif action == 'get_status':
                status = {
                    'recording': self.recording,
                    'resolution': self.resolution,
                    'fps': self.fps,
                    'camera_id': self.camera_id
                }
                return {'status': 'success', 'data': status}

            elif action == 'set_controls':
                self.picam2.set_controls(params)
                return {'status': 'success'}

            elif action == 'shutdown':
                self.shutdown_event.set()
                return {'status': 'success'}

            else:
                return {'status': 'error', 'message': f'Unknown action: {action}'}

        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    async def run_standalone(self, duration: Optional[int] = None):
        """
        Run in standalone mode with optional auto-recording.

        Args:
            duration: Recording duration in seconds (None for manual control)
        """
        self.logger.info(f"Running standalone mode (duration: {duration}s)")

        try:
            # Start recording automatically
            await self.start_recording()

            if self.show_preview:
                self.logger.info("Showing preview. Press 'q' to quit, 's' for snapshot")
                # Run preview loop
                await self.run_preview_loop(duration)
            else:
                if duration:
                    # Record for specified duration
                    await asyncio.sleep(duration)
                else:
                    # Wait for interrupt signal
                    self.logger.info("Recording... Press Ctrl+C to stop")
                    await self.shutdown_event.wait()

            # Stop recording
            await self.stop_recording()

        except KeyboardInterrupt:
            self.logger.info("Interrupted by user")
        except Exception as e:
            self.logger.error(f"Standalone mode error: {e}")

    async def run(self, duration: Optional[int] = None):
        """
        Main run loop for the camera module.

        Args:
            duration: Recording duration for standalone mode
        """
        try:
            # Initialize and start camera
            await self.initialize_camera()
            await self.start_camera()

            if self.use_ipc:
                # Run IPC command handler
                self.logger.info("Running in IPC mode")
                await self.handle_ipc_commands()
            else:
                # Run standalone mode
                await self.run_standalone(duration)

        except Exception as e:
            self.logger.error(f"Runtime error: {e}")
        finally:
            await self.cleanup()

    async def run_preview_loop(self, duration: Optional[int] = None):
        """
        Run the preview display loop.

        Args:
            duration: Optional duration in seconds
        """
        start_time = asyncio.get_event_loop().time()
        snapshot_count = 0

        while not self.shutdown_event.is_set():
            try:
                # Check duration
                if duration and (asyncio.get_event_loop().time() - start_time) >= duration:
                    break

                # Check if window was closed by user (red X button)
                if cv2.getWindowProperty("Camera Feed", cv2.WND_PROP_VISIBLE) < 1:
                    self.logger.info("Preview window closed by user")
                    break

                # Capture frame for display
                frame = self.picam2.capture_array("main")

                # Add timestamp overlay for display (in addition to callback)
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                font = cv2.FONT_HERSHEY_SIMPLEX
                # Add shadow for better visibility
                cv2.putText(frame, timestamp, (12, 32),
                           font, 0.8, (0, 0, 0), 3)
                cv2.putText(frame, timestamp, (10, 30),
                           font, 0.8, (0, 255, 0), 2)

                # Add recording indicator
                if self.recording:
                    cv2.circle(frame, (frame.shape[1] - 30, 30), 10, (0, 0, 255), -1)
                    cv2.putText(frame, "REC", (frame.shape[1] - 80, 37),
                               font, 0.7, (0, 0, 255), 2)

                # Display frame
                cv2.imshow("Camera Feed", frame)

                # Handle keyboard input (non-blocking)
                key = cv2.waitKey(1) & 0xFF

                if key == ord('q'):
                    self.logger.info("Quit requested via keyboard")
                    break
                elif key == ord('s'):
                    # Take snapshot
                    snapshot_path = await self.capture_image()
                    snapshot_count += 1
                    self.logger.info(f"Snapshot saved: {snapshot_path}")

                # Small delay to prevent CPU overload
                await asyncio.sleep(0.03)  # ~30 FPS display rate

            except cv2.error as e:
                # Window was destroyed
                self.logger.info("Preview window destroyed")
                break
            except Exception as e:
                self.logger.error(f"Preview loop error: {e}")
                break

        if snapshot_count > 0:
            self.logger.info(f"Saved {snapshot_count} snapshot(s)")

    async def cleanup(self):
        """Clean up camera resources."""
        try:
            if self.recording:
                await self.stop_recording()

            if self.preview_window_open:
                cv2.destroyAllWindows()
                self.preview_window_open = False

            if self.picam2:
                if self.preview_enabled:
                    self.picam2.stop_preview()
                self.picam2.stop()
                self.picam2.close()

            self.logger.info("Camera cleanup completed")

        except Exception as e:
            self.logger.error(f"Cleanup error: {e}")

    def handle_signal(self, sig, frame):
        """Handle shutdown signals."""
        self.logger.info(f"Received signal {sig}")
        self.shutdown_event.set()


async def main():
    """Main entry point for standalone execution."""
    parser = argparse.ArgumentParser(description='Raspberry Pi Camera Module')
    parser.add_argument('--resolution', type=str, default='1920x1080',
                        help='Video resolution (e.g., 1920x1080, 3840x2160)')
    parser.add_argument('--fps', type=int, default=30,
                        help='Frames per second (10-60)')
    parser.add_argument('--save-location', type=str, default='./recordings',
                        help='Directory for saved recordings')
    parser.add_argument('--camera-id', type=int, default=0,
                        help='Camera ID (0 or 1 for Pi 5)')
    parser.add_argument('--duration', type=int, default=None,
                        help='Recording duration in seconds (None for manual)')
    parser.add_argument('--ipc', action='store_true',
                        help='Run in IPC mode for subprocess communication')
    parser.add_argument('--no-preview', action='store_true',
                        help='Disable preview window (headless mode)')

    args = parser.parse_args()

    # Parse resolution
    try:
        width, height = map(int, args.resolution.split('x'))
        resolution = (width, height)
    except ValueError:
        print(f"Invalid resolution format: {args.resolution}")
        sys.exit(1)

    # Validate FPS
    if not 10 <= args.fps <= 60:
        print(f"FPS must be between 10 and 60, got {args.fps}")
        sys.exit(1)

    # Create camera module
    camera = CameraModule(
        resolution=resolution,
        fps=args.fps,
        save_location=args.save_location,
        camera_id=args.camera_id,
        use_ipc=args.ipc,
        show_preview=not args.no_preview
    )

    # Setup signal handlers
    signal.signal(signal.SIGINT, camera.handle_signal)
    signal.signal(signal.SIGTERM, camera.handle_signal)

    # Run camera module
    await camera.run(duration=args.duration)


if __name__ == "__main__":
    asyncio.run(main())