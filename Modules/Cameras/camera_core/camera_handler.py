
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

logger = logging.getLogger(__name__)


class CameraHandler:

    def __init__(self, cam_info, cam_num, args, session_dir: Optional[Path]):
        self.logger = logging.getLogger(f"Camera{cam_num}")
        self.cam_num = cam_num
        self.args = args
        self.session_dir = Path(session_dir) if session_dir else None
        self.output_dir = Path(args.output_dir)
        self.recording = False
        self.active = True  # Camera active state (for GUI toggle)

        self.output_dir.mkdir(parents=True, exist_ok=True)

        config_path = Path(__file__).parent.parent / "config.txt"
        self.overlay_config = ConfigLoader.load_overlay_config(config_path)

        self.logger.info("Initializing camera %d", cam_num)
        self.picam2 = Picamera2(cam_num)

        # This eliminates artificial frame drops and improves efficiency
        requested_fps = float(args.fps)
        effective_fps = CameraConfig.validate_fps(requested_fps)
        frame_duration_us = CameraConfig.calculate_frame_duration_us(effective_fps)

        CameraConfig.log_resolution_info(cam_num, args.width, args.height)

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

        self.capture_loop = CameraCaptureLoop(cam_num, self.picam2)
        self.processor = CameraProcessor(
            cam_num,
            args,
            self.overlay_config,
            self.recording_manager,
            self.capture_loop,
            self.session_dir
        )

        self._capture_task: Optional[asyncio.Task] = None
        self._processor_task: Optional[asyncio.Task] = None
        self._running = False

    async def start_loops(self):
        if self._running:
            return

        self._running = True

        self._capture_task = asyncio.create_task(self.capture_loop.start())
        self._processor_task = asyncio.create_task(self.processor.start())

        self.logger.info("Started all async loops")

    async def start_recording(self, session_dir: Optional[Path] = None, trial_number: int = 1):
        if self.recording:
            return

        if session_dir:
            self.session_dir = session_dir
            self.processor.session_dir = session_dir

        if not self.session_dir:
            raise ValueError("No session directory available for recording")

        await self.recording_manager.start_recording(self.session_dir, trial_number)
        if self.recording_manager.video_path:
            self.logger.info("Recording to %s", self.recording_manager.video_path)
        self.recording = True

    async def stop_recording(self):
        if not self.recording:
            return
        await self.recording_manager.stop_recording()
        if self.recording_manager.video_path:
            self.logger.info("Stopped recording: %s", self.recording_manager.video_path)
        self.recording = False

    def get_frame(self):
        return self.processor.get_display_frame()

    def update_preview_cache(self):
        return self.processor.get_display_frame()

    async def pause_camera(self):
        if not self.active:
            return False

        if self.recording:
            self.logger.warning("Stopping recording on camera %d before pause", self.cam_num)
            await self.stop_recording()

        await self.capture_loop.pause()
        await self.processor.pause()

        self.active = False
        self.logger.info("Camera %d paused (CPU saving mode - ~35-50%% savings)", self.cam_num)
        return True

    async def resume_camera(self):
        if self.active:
            return False

        await self.capture_loop.resume()
        await self.processor.resume()

        self.active = True
        self.logger.info("Camera %d resumed", self.cam_num)
        return True

    @property
    def is_active(self) -> bool:
        return self.active

    async def cleanup(self):
        if self.recording:
            await self.stop_recording()
            await self.recording_manager.cleanup()

        try:
            self.picam2.stop()
        except Exception as e:
            self.logger.debug("Camera stop error (ignored): %s", e)

        self._running = False

        try:
            await asyncio.gather(
                self.capture_loop.stop(),
                self.processor.stop(),
                return_exceptions=True
            )
        except Exception as e:
            self.logger.debug("Error stopping loops: %s", e)

        tasks = []
        if self._capture_task and not self._capture_task.done():
            self._capture_task.cancel()
            tasks.append(self._capture_task)
        if self._processor_task and not self._processor_task.done():
            self._processor_task.cancel()
            tasks.append(self._processor_task)

        if tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=CLEANUP_TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError:
                self.logger.warning("Task cancellation did not complete within %d seconds", CLEANUP_TIMEOUT_SECONDS)

        try:
            self.picam2.stop_preview()
        except Exception:
            pass

        try:
            self.picam2.close()
        except Exception as e:
            self.logger.debug("Camera close error: %s", e)

        self.logger.info("Cleanup completed")
