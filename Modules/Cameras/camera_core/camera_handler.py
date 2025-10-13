#!/usr/bin/env python3
"""
Single camera handler with async loop architecture.

This orchestrates three independent async loops:
1. Capture Loop - Tight camera capture at configured FPS (1-60)
2. Collator Loop - Timing-based frame collation
3. Processor Loop - Heavy processing (overlays, recording, resizing)

Each loop is in its own file and runs independently.

CLEANUP ARCHITECTURE:
The cleanup process is carefully orchestrated to ensure fast, clean exits:
- Uses DaemonThreadPoolExecutor for asyncio run_in_executor operations
- Daemon executor threads don't block Python's atexit shutdown
- Non-daemon event loop thread ensures proper cleanup completes
- Cleanup sequence: recording → camera → loops → executor → event loop
- Typical cleanup time: < 1 second
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

    def __init__(self, cam_info, cam_num, args, session_dir: Optional[Path]):
        self.logger = logging.getLogger(f"Camera{cam_num}")
        self.cam_num = cam_num
        self.args = args
        self.session_dir = Path(session_dir) if session_dir else None
        self.output_dir = Path(args.output_dir)
        self.recording = False

        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Load overlay configuration
        self.overlay_config = self._load_overlay_config()

        self.logger.info("Initializing camera %d", cam_num)
        self.picam2 = Picamera2(cam_num)

        # Configure camera
        # MATCHED FPS MODE: Camera captures at same rate as recording
        # This eliminates artificial frame drops and improves efficiency
        requested_fps = float(args.fps)
        min_hardware_fps = 1.0   # Minimum practical FPS
        max_hardware_fps = 60.0  # IMX296 sensor maximum (1456x1088 @ 60fps)

        # Clamp FPS to valid hardware range [1, 60]
        if requested_fps > max_hardware_fps:
            self.logger.warning(
                "Requested FPS (%.1f) exceeds hardware limit (%.1f). "
                "Capping at %.1f FPS.",
                requested_fps, max_hardware_fps, max_hardware_fps
            )
            effective_fps = max_hardware_fps
        elif requested_fps < min_hardware_fps:
            self.logger.warning(
                "Requested FPS (%.1f) is below minimum (%.1f). "
                "Setting to %.1f FPS.",
                requested_fps, min_hardware_fps, min_hardware_fps
            )
            effective_fps = min_hardware_fps
        else:
            effective_fps = requested_fps

        # Configure camera to capture at effective FPS (matched to recording rate)
        frame_duration_us = int(1e6 / effective_fps)

        # Log resolution preset being used
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
            from cli_utils import RESOLUTION_TO_PRESET, RESOLUTION_PRESETS
            resolution_tuple = (args.width, args.height)
            if resolution_tuple in RESOLUTION_TO_PRESET:
                preset_num = RESOLUTION_TO_PRESET[resolution_tuple]
                _, _, desc, aspect = RESOLUTION_PRESETS[preset_num]
                self.logger.info("Camera %d using resolution preset %d: %dx%d - %s (%s)",
                                cam_num, preset_num, args.width, args.height, desc, aspect)
            else:
                self.logger.info("Camera %d using custom resolution: %dx%d",
                                cam_num, args.width, args.height)
        except Exception:
            pass

        # DUAL STREAM CONFIG:
        # - main: Full resolution for H.264 encoder (hardware accelerated)
        # - lores: Preview resolution for display (hardware scaled, no frame stealing)
        # IMPORTANT: Explicitly set RGB888 format for both streams to ensure color output
        config = self.picam2.create_video_configuration(
            main={"size": (args.width, args.height), "format": "RGB888"},
            lores={"size": (args.preview_width, args.preview_height), "format": "RGB888"},
            controls={
                "FrameDurationLimits": (frame_duration_us, frame_duration_us),
            },
        )
        self.picam2.configure(config)
        self.picam2.start()
        self.logger.info("Camera %d initialized at %.1f FPS (FrameDuration=%d us)",
                        cam_num, effective_fps, frame_duration_us)
        self.logger.info("Camera %d dual-stream: main=%dx%d (recording), lores=%dx%d (preview)",
                        cam_num, args.width, args.height, args.preview_width, args.preview_height)

        # Recording manager with hardware H.264 encoding
        # Pass overlay config so recorder can add frame numbers via post_callback
        # NOTE: The post_callback will be registered immediately, not just during recording
        auto_remux = not self.overlay_config.get('disable_mp4_conversion', True)
        self.recording_manager = CameraRecordingManager(
            camera_id=cam_num,
            picam2=self.picam2,
            resolution=(args.width, args.height),
            fps=effective_fps,
            bitrate=10_000_000,  # 10 Mbps default
            enable_csv_logging=self.overlay_config.get('enable_csv_timing_log', True),
            auto_remux=auto_remux,
            enable_overlay=True,  # Always enable for frame/CSV correlation
            overlay_config=self.overlay_config,
        )

        # Register post_callback immediately for overlay on both preview and recording
        # This ensures frame numbers appear on preview even when not recording
        self.picam2.post_callback = self.recording_manager._overlay_callback
        self.logger.info("Camera %d: Registered overlay callback for both streams (main+lores)", cam_num)

        # Create async loops
        self.capture_loop = CameraCaptureLoop(cam_num, self.picam2)
        self.collator_loop = CameraCollatorLoop(cam_num, effective_fps, self.capture_loop)
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
            'min_cameras': 1,
            'allow_partial': True,
            'discovery_timeout': 5.0,
            'discovery_retry': 3.0,
            'output_dir': 'recordings',
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
            'show_frame_number': True,
            'scale_mode': 'auto',
            'manual_scale_factor': 3.0,
            # Recording settings
            'enable_csv_timing_log': True,
            'disable_mp4_conversion': True,
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
        self._loop = None

        # Run event loop in thread
        import threading

        def run_loops():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

            # Use custom executor with daemon threads to prevent atexit hangs
            from concurrent.futures import ThreadPoolExecutor
            from concurrent.futures.thread import _worker
            import threading
            import weakref

            class DaemonThreadPoolExecutor(ThreadPoolExecutor):
                def _adjust_thread_count(self):
                    def weakref_cb(_, q=self._work_queue):
                        q.put(None)

                    num_threads = len(self._threads)
                    if num_threads < self._max_workers:
                        thread_name = f'{self._thread_name_prefix or self}_{num_threads}'
                        t = threading.Thread(
                            name=thread_name,
                            target=_worker,
                            args=(weakref.ref(self, weakref_cb), self._work_queue,
                                  self._initializer, self._initargs),
                            daemon=True
                        )
                        t.start()
                        self._threads.add(t)

            executor = DaemonThreadPoolExecutor(max_workers=4)
            self._loop.set_default_executor(executor)

            self._loop_task = self._loop.create_task(self._run_all_loops())
            try:
                self._loop.run_until_complete(self._loop_task)
            except asyncio.CancelledError:
                self.logger.debug("Loop task cancelled")
            except Exception as e:
                self.logger.error("Loop error: %s", e)
            finally:
                try:
                    pending = asyncio.all_tasks(self._loop)
                    for task in pending:
                        task.cancel()
                    if pending:
                        try:
                            self._loop.run_until_complete(
                                asyncio.wait_for(
                                    asyncio.gather(*pending, return_exceptions=True),
                                    timeout=1.0
                                )
                            )
                        except (asyncio.TimeoutError, Exception):
                            pass
                except Exception:
                    pass

                try:
                    executor = self._loop._default_executor
                    if executor is not None:
                        executor.shutdown(wait=False, cancel_futures=True)
                except Exception:
                    pass

                try:
                    self._loop.close()
                except Exception:
                    pass
                self._loop = None

        self._loop_thread = threading.Thread(target=run_loops, daemon=False)
        self._loop_thread.start()
        self.logger.info("Started all async loops")

    async def _run_all_loops(self):
        await self.capture_loop.start()
        await self.collator_loop.start()
        await self.processor.start()

        try:
            while self._running:
                await asyncio.sleep(0.1)
        finally:
            self.logger.debug("Stopping async loops...")
            await asyncio.gather(
                self.capture_loop.stop(),
                self.collator_loop.stop(),
                self.processor.stop(),
                return_exceptions=True
            )
            self.logger.debug("All async loops stopped")

    def start_recording(self, session_dir: Optional[Path] = None):
        if self.recording:
            return

        if session_dir:
            self.session_dir = session_dir
            self.processor.session_dir = session_dir

        if not self.session_dir:
            raise ValueError("No session directory available for recording")

        self.recording_manager.start_recording(self.session_dir)
        if self.recording_manager.video_path:
            self.logger.info("Recording to %s", self.recording_manager.video_path)
        self.recording = True

    def stop_recording(self):
        if not self.recording:
            return
        self.recording_manager.stop_recording()
        if self.recording_manager.video_path:
            self.logger.info("Stopped recording: %s", self.recording_manager.video_path)
        self.recording = False

    def get_frame(self):
        return self.processor.get_display_frame()

    def update_preview_cache(self):
        return self.processor.get_display_frame()

    def cleanup(self):
        """Clean up resources: recording → camera → loops → close."""
        if self.recording:
            self.stop_recording()
            self.recording_manager.cleanup()

        try:
            self.picam2.stop()
        except Exception as e:
            self.logger.debug("Camera stop error (ignored): %s", e)

        self._running = False

        if hasattr(self, '_loop_thread') and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=2.0)
            if self._loop_thread.is_alive():
                self.logger.warning("Async loop thread did not finish within 2 seconds")

        try:
            self.picam2.stop_preview()
        except Exception:
            pass

        try:
            self.picam2.close()
        except Exception as e:
            self.logger.debug("Camera close error: %s", e)

        self.logger.info("Cleanup completed")
