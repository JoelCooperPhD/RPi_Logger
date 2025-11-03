
import asyncio
import logging
import time
from pathlib import Path
from typing import Optional

from picamera2 import Picamera2

from .recording import CameraRecordingManager
from .camera_capture_loop import CameraCaptureLoop
from .camera_processor import CameraProcessor
from .config import ConfigLoader, CameraConfig

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

        self.logger.warning("CameraHandler.start_recording cam=%d trial=%d session_dir=%s",
                            self.cam_num, trial_number, self.session_dir)
        await self.recording_manager.start_recording(self.session_dir, trial_number)
        if self.recording_manager.video_path:
            self.logger.info("Recording to %s", self.recording_manager.video_path)
        self.recording = True

    async def stop_recording(self):
        if not self.recording:
            return
        self.logger.warning("CameraHandler.stop_recording cam=%d invoked", self.cam_num)
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
        """Stop capture/processing loops and release camera resources."""
        shutdown_id = f"{time.time():.0f}"
        report = {
            "cam": self.cam_num,
            "shutdown_id": shutdown_id,
            "steps": [],
            "success": True,
            "force_stop": False,
        }

        self.logger.warning("CameraHandler.cleanup entered cam=%d id=%s running=%s capture_task=%s processor_task=%s",
                            self.cam_num, shutdown_id, self._running, self._capture_task, self._processor_task)
        start_perf = time.perf_counter()

        async def run_async_step(label: str, coro_factory, *, timeout: Optional[float] = None):
            step = {
                "label": label,
                "start_ts": time.time(),
            }
            report["steps"].append(step)
            self.logger.warning("Cleanup[%s][cam=%d] start step: %s", shutdown_id, self.cam_num, label)
            step_start = time.perf_counter()
            try:
                awaitable = coro_factory()
                if timeout:
                    result = await asyncio.wait_for(awaitable, timeout=timeout)
                else:
                    result = await awaitable
                step["status"] = "success"
                step["duration_s"] = time.perf_counter() - step_start
                self.logger.warning("Cleanup[%s][cam=%d] success step: %s (%.3fs)",
                                 shutdown_id, self.cam_num, label, step["duration_s"])
                return True, result
            except asyncio.TimeoutError:
                report["success"] = False
                step["status"] = "timeout"
                step["duration_s"] = timeout
                self.logger.error("Cleanup[%s][cam=%d] timeout step: %s after %.1fs",
                                  shutdown_id, self.cam_num, label, timeout)
                return False, None
            except Exception as exc:  # pragma: no cover - defensive logging
                report["success"] = False
                step["status"] = "error"
                step["error"] = repr(exc)
                step["duration_s"] = time.perf_counter() - step_start
                self.logger.error("Cleanup[%s][cam=%d] failed step: %s (%s)",
                                  shutdown_id, self.cam_num, label, exc, exc_info=True)
                return False, None

        async def run_blocking_step(label: str, func, *, timeout: float = 2.0):
            loop = asyncio.get_running_loop()
            return await run_async_step(label, lambda: loop.run_in_executor(None, func), timeout=timeout)

        def run_sync_step(label: str, func) -> None:
            step = {
                "label": label,
                "start_ts": time.time(),
            }
            report["steps"].append(step)
            self.logger.warning("Cleanup[%s][cam=%d] start sync step: %s", shutdown_id, self.cam_num, label)
            step_start = time.perf_counter()
            try:
                func()
            except Exception as exc:  # pragma: no cover - defensive logging
                step["status"] = "error"
                step["error"] = repr(exc)
                step["duration_s"] = time.perf_counter() - step_start
                report["success"] = False
                self.logger.error("Cleanup[%s][cam=%d] failed step: %s (%s)",
                                  shutdown_id, self.cam_num, label, exc, exc_info=True)
            else:
                step["status"] = "success"
                step["duration_s"] = time.perf_counter() - step_start
                self.logger.warning("Cleanup[%s][cam=%d] success sync step: %s (%.3fs)",
                                 shutdown_id, self.cam_num, label, step["duration_s"])

        async def await_task(label: str, task: Optional[asyncio.Task], *, timeout: float = 2.0):
            if task is None:
                return

            async def _wait():
                return await task

            await run_async_step(label, _wait, timeout=timeout)

        if self.recording:
            await run_async_step("stop_recording", lambda: self.stop_recording(), timeout=5.0)

        else:
            self.logger.warning("Cleanup[%s][cam=%d] camera not recording", shutdown_id, self.cam_num)

        await run_async_step("recording_manager.cleanup", lambda: self.recording_manager.cleanup(), timeout=5.0)

        self._running = False

        # Proactively break capture wait loops before awaiting their stop tasks
        run_sync_step("capture_loop.request_stop", self.capture_loop.request_stop)
        run_sync_step("processor.request_stop", self.processor.request_stop)

        stop_callable = getattr(self.picam2, "stop", None)
        if callable(stop_callable):
            self.logger.warning("Cleanup[%s][cam=%d] calling picam2.stop", shutdown_id, self.cam_num)
            await run_blocking_step("picam2.stop", stop_callable, timeout=5.0)
        else:
            self.logger.warning("Cleanup[%s][cam=%d] picam2.stop missing", shutdown_id, self.cam_num)

        await run_async_step("capture_loop.join", lambda: self.capture_loop.join(), timeout=5.0)
        await run_async_step("processor.join", lambda: self.processor.join(), timeout=5.0)

        self.logger.warning("Cleanup[%s][cam=%d] awaiting capture_start_task=%s", shutdown_id, self.cam_num, self._capture_task)
        await await_task("capture_start_task.done", self._capture_task, timeout=2.0)
        self._capture_task = None
        self.logger.warning("Cleanup[%s][cam=%d] awaiting processor_start_task=%s", shutdown_id, self.cam_num, self._processor_task)
        await await_task("processor_start_task.done", self._processor_task, timeout=2.0)
        self._processor_task = None

        close_callable = getattr(self.picam2, "close", None)
        if callable(close_callable):
            self.logger.warning("Cleanup[%s][cam=%d] calling picam2.close", shutdown_id, self.cam_num)
            await run_blocking_step("picam2.close", close_callable, timeout=5.0)
        else:
            self.logger.warning("Cleanup[%s][cam=%d] picam2.close missing", shutdown_id, self.cam_num)

        report["duration_s"] = time.perf_counter() - start_perf

        self.logger.warning("Cleanup complete id=%s success=%s duration=%.3fs", shutdown_id, report["success"], report["duration_s"])
        self.logger.warning("Cleanup summary id=%s cam=%d: %s", shutdown_id, self.cam_num, report)
        return report
