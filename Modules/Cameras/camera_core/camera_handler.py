#!/usr/bin/env python3
"""
Single camera handler with async loop architecture.

This orchestrates three independent async loops:
1. Capture Loop - Tight camera capture at native FPS (~30)
2. Collator Loop - Timing-based frame collation at display FPS (10)
3. Processor Loop - Heavy processing (overlays, recording, resizing)

Each loop is in its own file and runs independently.
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional

import numpy as np
from picamera2 import Picamera2

from .camera_recorder import CameraRecordingManager
from .camera_capture_loop import CameraCaptureLoop
from .camera_collator_loop import CameraCollatorLoop
from .camera_processor import CameraProcessor

logger = logging.getLogger("CameraHandler")


class CameraHandler:
    """Handles individual camera with async loop architecture."""

    def __init__(self, cam_info, cam_num, args, session_dir: Path):
        self.logger = logging.getLogger(f"Camera{cam_num}")
        self.cam_num = cam_num
        self.args = args
        self.session_dir = Path(session_dir)
        self.output_dir = Path(args.output_dir)
        self.recording = False

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.session_dir.mkdir(parents=True, exist_ok=True)

        # Load overlay configuration
        self.overlay_config = self._load_overlay_config()

        self.logger.info("Initializing camera %d", cam_num)
        self.picam2 = Picamera2(cam_num)

        # Configure camera
        # Set camera hardware to run at 30 FPS (native rate)
        # Collation will run at args.fps (e.g., 10 FPS) for display/recording
        capture_fps = 30.0  # Camera hardware capture rate
        config = self.picam2.create_video_configuration(
            main={"size": (args.width, args.height)},
            controls={
                "FrameDurationLimits": (int(1e6 / capture_fps), int(1e6 / capture_fps)),
            },
        )
        self.picam2.configure(config)
        self.picam2.start()
        self.logger.info("Camera %d initialized", cam_num)

        # Recording manager
        self.recording_manager = CameraRecordingManager(
            camera_id=cam_num,
            resolution=(args.width, args.height),
            fps=float(args.fps),
        )

        # Create async loops
        self.capture_loop = CameraCaptureLoop(cam_num, self.picam2)
        self.collator_loop = CameraCollatorLoop(cam_num, float(args.fps), self.capture_loop)
        self.processor = CameraProcessor(
            cam_num,
            args,
            self.overlay_config,
            self.recording_manager,
            self.capture_loop,
            self.collator_loop,
            self.session_dir
        )

        # Event loop task
        self._loop_task: Optional[asyncio.Task] = None
        self._running = False

    def _load_overlay_config(self) -> dict:
        """Load configuration from file."""
        config_path = Path(__file__).parent.parent / "config.txt"
        defaults = {
            # Camera settings
            'resolution_width': 1920,
            'resolution_height': 1080,
            'preview_width': 640,
            'preview_height': 360,
            'target_fps': 30.0,
            'min_cameras': 2,
            'allow_partial': False,
            'discovery_timeout': 5.0,
            'discovery_retry': 3.0,
            'output_dir': 'recordings/cameras',
            'session_prefix': 'session',
            # Overlay settings
            'font_scale_base': 0.6,
            'thickness_base': 2,
            'font_type': 'SIMPLEX',
            'outline_enabled': True,
            'outline_extra_thickness': 2,
            'line_start_y': 30,
            'line_spacing': 30,
            'margin_left': 10,
            'text_color_b': 255,
            'text_color_g': 255,
            'text_color_r': 255,
            'outline_color_b': 0,
            'outline_color_g': 0,
            'outline_color_r': 0,
            'line_type': 16,
            'background_enabled': False,
            'background_shape': 'rectangle',
            'background_color_b': 0,
            'background_color_g': 0,
            'background_color_r': 0,
            'background_opacity': 0.6,
            'background_padding_top': 10,
            'background_padding_bottom': 10,
            'background_padding_left': 10,
            'background_padding_right': 10,
            'background_corner_radius': 10,
            'show_camera_and_time': True,
            'show_session': True,
            'show_requested_fps': True,
            'show_sensor_fps': True,
            'show_display_fps': True,
            'show_frame_counter': True,
            'show_recording_info': True,
            'show_recording_filename': True,
            'show_controls': True,
            'scale_mode': 'auto',
            'manual_scale_factor': 3.0,
        }

        if not config_path.exists():
            self.logger.warning("Overlay config not found at %s, using defaults", config_path)
            return defaults

        try:
            with open(config_path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        if '#' in value:
                            value = value.split('#')[0].strip()
                        if key in defaults:
                            if isinstance(defaults[key], bool):
                                defaults[key] = value.lower() in ('true', '1', 'yes', 'on')
                            elif isinstance(defaults[key], float):
                                defaults[key] = float(value)
                            elif isinstance(defaults[key], int):
                                defaults[key] = int(value)
                            else:
                                defaults[key] = value
            self.logger.info("Loaded overlay config from %s", config_path)
        except Exception as e:
            self.logger.warning("Failed to load overlay config: %s, using defaults", e)

        return defaults

    def start_loops(self):
        """Start all async loops in a background thread."""
        if self._running:
            return

        self._running = True

        # Run event loop in thread
        import threading

        def run_loops():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop_task = loop.create_task(self._run_all_loops())
            try:
                loop.run_until_complete(self._loop_task)
            except asyncio.CancelledError:
                pass
            finally:
                loop.close()

        self._loop_thread = threading.Thread(target=run_loops, daemon=True)
        self._loop_thread.start()
        self.logger.info("Started all async loops")

    async def _run_all_loops(self):
        """Run all loops concurrently."""
        # Start all loops (creates tasks)
        await self.capture_loop.start()
        await self.collator_loop.start()
        await self.processor.start()

        # Keep running until stopped
        while self._running:
            await asyncio.sleep(0.1)

    def start_recording(self):
        """Start recording."""
        if self.recording:
            return
        self.recording_manager.start_recording(self.session_dir)
        if self.recording_manager.video_path:
            self.logger.info("Recording to %s", self.recording_manager.video_path)
        self.recording = True

    def stop_recording(self):
        """Stop recording."""
        if not self.recording:
            return
        self.recording_manager.stop_recording()
        if self.recording_manager.video_path:
            self.logger.info("Stopped recording: %s", self.recording_manager.video_path)
        self.recording = False

    def get_frame(self):
        """
        Get processed frame for preview display.

        Called from main thread for OpenCV display.
        """
        return self.processor.get_display_frame()

    def update_preview_cache(self):
        """
        Get the latest preview frame (called from main thread).

        Same as get_frame() - just returns display frame from processor.
        """
        return self.processor.get_display_frame()

    def cleanup(self):
        """Clean up all resources."""
        self._running = False

        # Stop async loops properly
        try:
            import threading
            import time

            def stop_loops_sync():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    # Stop all loops
                    loop.run_until_complete(asyncio.gather(
                        self.capture_loop.stop(),
                        self.collator_loop.stop(),
                        self.processor.stop(),
                        return_exceptions=True
                    ))
                except Exception as e:
                    self.logger.debug("Loop stop error: %s", e)
                finally:
                    loop.close()

            thread = threading.Thread(target=stop_loops_sync, daemon=True)
            thread.start()
            thread.join(timeout=1.0)
        except Exception as e:
            self.logger.debug("Async cleanup error: %s", e)

        self.stop_recording()
        self.recording_manager.cleanup()

        try:
            self.picam2.stop_preview()
        except Exception:
            pass
        self.picam2.stop()
        self.picam2.close()
        self.logger.info("Cleanup completed")
