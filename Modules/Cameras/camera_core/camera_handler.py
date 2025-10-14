#!/usr/bin/env python3
"""
Single camera handler with async loop architecture.

This orchestrates two independent async loops:
1. Capture Loop - Tight camera capture at configured FPS (1-60)
2. Processor Loop - Heavy processing (overlays, recording, display)

Simplified architecture: capture → processor (no intermediate buffering layer).

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

from .recording import CameraRecordingManager
from .camera_capture_loop import CameraCaptureLoop
from .camera_processor import CameraProcessor
from .config import ConfigLoader, CameraConfig
from .constants import DEFAULT_EXECUTOR_WORKERS, CLEANUP_TIMEOUT_SECONDS

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
        config_path = Path(__file__).parent.parent / "config.txt"
        self.overlay_config = ConfigLoader.load_overlay_config(config_path)

        self.logger.info("Initializing camera %d", cam_num)
        self.picam2 = Picamera2(cam_num)

        # Configure camera
        # MATCHED FPS MODE: Camera captures at same rate as recording
        # This eliminates artificial frame drops and improves efficiency
        requested_fps = float(args.fps)
        effective_fps = CameraConfig.validate_fps(requested_fps)
        frame_duration_us = CameraConfig.calculate_frame_duration_us(effective_fps)

        # Log resolution preset being used
        CameraConfig.log_resolution_info(cam_num, args.width, args.height)

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
        # NOTE: Recording manager registers overlay callback internally in its __init__

        # Create async loops (simplified: capture → processor)
        self.capture_loop = CameraCaptureLoop(cam_num, self.picam2)
        self.processor = CameraProcessor(
            cam_num,
            args,
            self.overlay_config,
            self.recording_manager,
            self.capture_loop,
            self.session_dir
        )

        # Event loop task
        self._loop_task: Optional[asyncio.Task] = None
        self._running = False

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

            executor = DaemonThreadPoolExecutor(max_workers=DEFAULT_EXECUTOR_WORKERS)
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
        await self.processor.start()

        try:
            while self._running:
                await asyncio.sleep(0.1)
        finally:
            self.logger.debug("Stopping async loops...")
            await asyncio.gather(
                self.capture_loop.stop(),
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
            self._loop_thread.join(timeout=CLEANUP_TIMEOUT_SECONDS)
            if self._loop_thread.is_alive():
                self.logger.warning("Async loop thread did not finish within %d seconds", CLEANUP_TIMEOUT_SECONDS)

        try:
            self.picam2.stop_preview()
        except Exception:
            pass

        try:
            self.picam2.close()
        except Exception as e:
            self.logger.debug("Camera close error: %s", e)

        self.logger.info("Cleanup completed")
