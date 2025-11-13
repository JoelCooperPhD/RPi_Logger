import asyncio
import logging
import sys
from pathlib import Path
from typing import Any, Optional

from rpi_logger.modules.base import BaseSystem, ModuleInitializationError, RecordingStateMixin
from .config.tracker_config import TrackerConfig
from .device_manager import DeviceManager
from .stream_handler import StreamHandler
from .frame_processor import FrameProcessor
from .recording import RecordingManager
from .modes import GUIMode, HeadlessMode, SlaveMode
from .tracker_handler import TrackerHandler

logger = logging.getLogger(__name__)


class TrackerInitializationError(ModuleInitializationError):
    pass


class TrackerSystem(BaseSystem, RecordingStateMixin):

    # Device will connect in background after GUI is created
    DEFER_DEVICE_INIT_IN_GUI = True

    def __init__(self, args):
        super().__init__(args)
        RecordingStateMixin.__init__(self)

        self.frame_count = 0

        width = getattr(args, "width", 1280)
        height = getattr(args, "height", 720)
        self.config = TrackerConfig(
            fps=getattr(args, "target_fps", 5.0),
            resolution=(width, height),
            output_dir=str(getattr(args, "session_dir", "recordings")),
            display_width=getattr(args, "preview_width", 640),
            preview_width=getattr(args, "preview_width", 640),
            preview_height=getattr(args, "preview_height", None),
            enable_recording_overlay=getattr(args, "enable_recording_overlay", True),
            include_gaze_in_recording=getattr(args, "include_gaze_in_recording", True),
            overlay_font_scale=getattr(args, "overlay_font_scale", 0.6),
            overlay_thickness=getattr(args, "overlay_thickness", 1),
            overlay_color_r=getattr(args, "overlay_color_r", 0),
            overlay_color_g=getattr(args, "overlay_color_g", 0),
            overlay_color_b=getattr(args, "overlay_color_b", 0),
            overlay_margin_left=getattr(args, "overlay_margin_left", 10),
            overlay_line_start_y=getattr(args, "overlay_line_start_y", 30),
            gaze_circle_radius=getattr(args, "gaze_circle_radius", 30),
            gaze_circle_thickness=getattr(args, "gaze_circle_thickness", 3),
            gaze_center_radius=getattr(args, "gaze_center_radius", 2),
            gaze_shape=getattr(args, "gaze_shape", "circle"),
            gaze_color_worn_b=getattr(args, "gaze_color_worn_b", 255),
            gaze_color_worn_g=getattr(args, "gaze_color_worn_g", 255),
            gaze_color_worn_r=getattr(args, "gaze_color_worn_r", 0),
            gaze_color_not_worn_b=getattr(args, "gaze_color_not_worn_b", 0),
            gaze_color_not_worn_g=getattr(args, "gaze_color_not_worn_g", 0),
            gaze_color_not_worn_r=getattr(args, "gaze_color_not_worn_r", 255),
            enable_advanced_gaze_logging=getattr(args, "enable_advanced_gaze_logging", False),
            expand_eye_event_details=getattr(args, "expand_eye_event_details", True),
            enable_audio_recording=getattr(args, "enable_audio_recording", False),
            audio_stream_param=getattr(args, "audio_stream_param", "audio=scene"),
            enable_device_status_logging=getattr(args, "enable_device_status_logging", False),
            device_status_poll_interval=getattr(args, "device_status_poll_interval", 5.0),
        )

        self.device_manager = DeviceManager()
        self.device_manager.audio_stream_param = self.config.audio_stream_param
        self.stream_handler = StreamHandler()
        self.frame_processor = FrameProcessor(self.config)
        self.recording_manager = RecordingManager(self.config, device_manager=self.device_manager)
        self.tracker_handler = TrackerHandler(
            self.config,
            self.device_manager,
            self.stream_handler,
            self.frame_processor,
            self.recording_manager,
        )

        if self.session_dir:
            try:
                session_path = Path(self.session_dir)
                session_path.mkdir(parents=True, exist_ok=True)
                self.recording_manager.set_session_context(session_path)
            except Exception as exc:
                self.logger.warning(
                    "Failed to prepare session directory %s: %s", self.session_dir, exc
                )

    def _ensure_session_dir(self) -> Path:
        if self.session_dir is None:
            raise RuntimeError("Session directory is not initialized")

        session_path = Path(self.session_dir)
        session_path.mkdir(parents=True, exist_ok=True)
        return session_path

    async def _initialize_devices(self) -> None:
        self.logger.info("Initializing tracker system")
        self.lifecycle_timer.mark_phase("device_discovery_start")

        if self._should_send_status():
            from rpi_logger.core.commands import StatusMessage

            StatusMessage.send(
                "discovering", {"device_type": "eye_tracker", "timeout": self.device_timeout}
            )

        connected = await self.device_manager.connect()
        if not connected:
            raise TrackerInitializationError("Failed to connect to eye tracker device")

        self.initialized = True
        self.lifecycle_timer.mark_phase("device_discovery_complete")
        self.lifecycle_timer.mark_phase("initialized")
        self.logger.info("Tracker system initialized")

        if self._should_send_status():
            from rpi_logger.core.commands import StatusMessage

            init_duration = self.lifecycle_timer.get_duration(
                "device_discovery_start", "initialized"
            )
            StatusMessage.send_with_timing(
                "initialized",
                init_duration,
                {"device_type": "eye_tracker", "device_connected": True},
            )

    def _create_mode_instance(self, mode_name: str) -> Any:
        if mode_name in ("tkinter", "gui", "interactive"):
            return GUIMode(self, enable_commands=self.enable_gui_commands)
        elif mode_name == "slave":
            return SlaveMode(self)
        else:  # headless (default fallback)
            return HeadlessMode(self)

    async def start_recording(
        self,
        session_dir: Optional[Path] = None,
        trial_number: Optional[int] = None,
    ) -> bool:
        can_start, error_msg = self.validate_recording_start()
        if not can_start:
            self.logger.warning("Cannot start recording: %s", error_msg)
            return False

        if session_dir is not None:
            target_dir = Path(session_dir)
        elif self.recording_manager.current_experiment_dir is not None:
            target_dir = Path(self.recording_manager.current_experiment_dir)
        else:
            target_dir = self._ensure_session_dir()

        target_dir.mkdir(parents=True, exist_ok=True)
        self.session_dir = target_dir
        self.session_label = target_dir.name

        active_trial_number = trial_number or (self.recording_count + 1)

        self.recording_manager.set_session_context(target_dir, active_trial_number)

        try:
            await self.recording_manager.start_recording(target_dir, active_trial_number)
        except Exception as exc:
            self.logger.error("Failed to start recording: %s", exc, exc_info=True)
            self.recording = False
            return False

        self._increment_recording_count()
        self.recording = True
        self.logger.info("Recording started (trial %d)", active_trial_number)
        return True

    async def stop_recording(self) -> bool:
        can_stop, error_msg = self.validate_recording_stop()
        if not can_stop:
            self.logger.warning("Cannot stop recording: %s", error_msg)
            return False

        try:
            await self.recording_manager.stop_recording()
        except Exception as exc:
            self.logger.error("Failed to stop recording: %s", exc, exc_info=True)
            return False

        self.recording = False
        self.logger.info("Recording stopped")
        return True

    @property
    def gaze_tracker(self):
        return self.tracker_handler.gaze_tracker

    # Phase 1.4: Pause/resume support
    async def pause(self):
        """Pause tracking to save CPU"""
        if self.tracker_handler.gaze_tracker is None:
            logger.warning("Cannot pause: tracker not initialized")
            return

        await self.tracker_handler.pause()
        logger.info("Tracker system paused")

    async def resume(self):
        """Resume tracking"""
        if self.tracker_handler.gaze_tracker is None:
            logger.warning("Cannot resume: tracker not initialized")
            return

        await self.tracker_handler.resume()
        logger.info("Tracker system resumed")

    def is_paused(self) -> bool:
        """Check if paused"""
        return self.tracker_handler.is_paused()

    async def cleanup(self) -> None:
        self.logger.info("Cleaning up tracker system")
        self.running = False
        self.shutdown_event.set()

        if self.recording:
            await self.stop_recording()

        await self.tracker_handler.cleanup()
        await self.recording_manager.cleanup()
        await self.device_manager.cleanup()

        self.initialized = False
        self.logger.info("Tracker system cleanup complete")
