"""USB camera runtime using simplified controller architecture."""

from __future__ import annotations

import asyncio
import contextlib
import sys
from pathlib import Path
from typing import Any, Dict, Optional
import logging

_module_dir = Path(__file__).resolve().parent
if str(_module_dir) not in sys.path:
    sys.path.insert(0, str(_module_dir))

try:
    from rpi_logger.core.commands import StatusMessage
except ImportError:
    StatusMessage = None

try:
    from rpi_logger.core.logging_utils import get_module_logger
except ImportError:
    def get_module_logger(name):
        return logging.getLogger(name)

try:
    from rpi_logger.core.paths import USER_MODULE_CONFIG_DIR
except ImportError:
    USER_MODULE_CONFIG_DIR = Path.home() / ".config" / "rpi_logger"

from .core import CameraController, CameraSettings, CameraState, USBDeviceInfo
from .discovery import get_device_by_path, get_device_by_stable_id, CameraKnowledge
from .ui.view import USBCameraView

try:
    from vmc.runtime import ModuleRuntime, RuntimeContext
except Exception:
    ModuleRuntime = object
    RuntimeContext = Any

logger = get_module_logger(__name__)


class USBCamerasRuntime(ModuleRuntime):
    def __init__(self, ctx: RuntimeContext) -> None:
        self.ctx = ctx
        self.logger = ctx.logger.getChild("USBCameras") if hasattr(ctx, "logger") and ctx.logger else logger
        self.module_dir = ctx.module_dir if hasattr(ctx, "module_dir") else _module_dir

        self._preferences = getattr(ctx.model, "preferences", None) if hasattr(ctx, "model") else None
        config = self._preferences.snapshot() if self._preferences else {}

        initial_settings = CameraSettings(
            frame_rate=self._parse_int(config.get("frame_rate"), 30),
            preview_scale=self._parse_float(config.get("preview_scale"), 0.25),
            preview_divisor=self._parse_int(config.get("preview_divisor"), 4),
            audio_mode=config.get("audio_mode", "auto"),
            sample_rate=self._parse_int(config.get("sample_rate"), 48000),
        )

        knowledge_path = USER_MODULE_CONFIG_DIR / "cameras_usb" / "camera_knowledge.json"
        self._knowledge = CameraKnowledge(knowledge_path)

        self.controller = CameraController(
            knowledge=self._knowledge,
            status_callback=self._on_status,
            settings_save_callback=self._save_settings,
        )
        self.controller._state.settings = initial_settings

        self._pending_device_ready: Optional[tuple[str, Optional[str]]] = None
        self._session_dir: Optional[Path] = None
        self._trial_number: int = 1
        self._auto_record: bool = False

        self.view = USBCameraView(getattr(ctx, "view", None))

    @staticmethod
    def _parse_int(val: Any, default: int) -> int:
        if val is None:
            return default
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _parse_float(val: Any, default: float) -> float:
        if val is None:
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    async def start(self) -> None:
        self.logger.info("=" * 60)
        self.logger.info("USB CAMERAS RUNTIME STARTING")
        self.logger.info("=" * 60)

        args = self.ctx.args
        self.logger.info("LAUNCH PARAMETERS:")
        self.logger.info("  device:       %s", getattr(args, "device", None))
        self.logger.info("  audio:        %s", getattr(args, "audio", "auto"))
        self.logger.info("  output_dir:   %s", getattr(args, "output_dir", None))
        self.logger.info("  record:       %s", getattr(args, "record", False))
        self.logger.info("=" * 60)

        await self._knowledge.load()

        self._auto_record = getattr(args, "record", False)
        if output_dir := getattr(args, "output_dir", None):
            self._session_dir = Path(output_dir)

        audio_mode = getattr(args, "audio", "auto")
        await self.controller.set_audio_mode(audio_mode)

        if self.ctx.view:
            with contextlib.suppress(Exception):
                self.ctx.view.set_preview_title("USB Camera")
            if hasattr(self.ctx.view, "set_data_subdir"):
                self.ctx.view.set_data_subdir("Cameras_USB")

        try:
            self.view.attach()
            self.view.bind_controller(self.controller)
            self.controller.subscribe(self.view.render)
            self.controller.set_preview_callback(self.view.set_preview_frame)
        except Exception as e:
            self.logger.warning("View attach failed (headless mode): %s", e)

        self.logger.info("USB Cameras runtime ready")
        if StatusMessage:
            StatusMessage.send("ready")

        device_path = getattr(self.ctx.args, "device", None)
        if device_path:
            self.logger.info("Auto-assigning USB camera %s via CLI arg", device_path)
            await self._assign_device_by_path(device_path, "cli_auto_assign")
        else:
            self.logger.info("Waiting for assign_device command")

    async def shutdown(self) -> None:
        self.logger.info("Shutting down USB Cameras runtime")
        await self.controller.shutdown()

    async def cleanup(self) -> None:
        pass

    async def handle_command(self, command: Dict[str, Any]) -> bool:
        action = (command.get("command") or "").lower()
        self.logger.debug("Received command: %s", action)

        if action == "assign_device":
            return await self._handle_assign_device(command)

        if action == "unassign_device":
            await self.controller.unassign()
            return True

        if action in {"start_recording", "record"}:
            return await self._handle_start_recording(command)

        if action in {"stop_recording", "stop"}:
            await self.controller.stop_recording()
            return True

        if action == "set_audio":
            mode = command.get("mode", "auto")
            await self.controller.set_audio_mode(mode)
            return True

        if action == "start_streaming":
            await self.controller.start_streaming()
            return True

        if action == "stop_streaming":
            await self.controller.stop_streaming()
            return True

        if action == "shutdown":
            await self.controller.shutdown()
            return True

        return False

    async def _handle_assign_device(self, command: Dict[str, Any]) -> bool:
        device_path = command.get("device_path") or command.get("camera_dev_path")
        stable_id = (
            command.get("stable_id")
            or command.get("camera_stable_id")
            or command.get("device_id")
        )
        command_id = command.get("command_id")

        self.logger.info("assign_device: device_path=%s, stable_id=%s", device_path, stable_id)

        if StatusMessage:
            device_id = stable_id or device_path or "unknown"
            StatusMessage.send("device_ack", {"device_id": device_id}, command_id=command_id)

        if device_path:
            return await self._assign_device_by_path(device_path, command_id)
        elif stable_id:
            return await self._assign_device_by_stable_id(stable_id, command_id)
        else:
            self.logger.warning("assign_device: no device_path or stable_id")
            if StatusMessage:
                StatusMessage.send("device_error", {"error": "Missing device_path or stable_id"}, command_id=command_id)
            return False

    async def _assign_device_by_path(self, device_path: str, command_id: Optional[str]) -> bool:
        device = await get_device_by_path(device_path)
        if not device:
            self.logger.error("Device not found: %s", device_path)
            if StatusMessage:
                StatusMessage.send("device_error", {"error": "Device not found"}, command_id=command_id)
            return False

        self._pending_device_ready = (device.stable_id, command_id)

        device_info = USBDeviceInfo(
            device=device.dev_path,
            stable_id=device.stable_id,
            display_name=device.display_name,
            vid_pid=device.vid_pid,
            sysfs_path=device.sysfs_path,
            bus_path=device.bus_path,
        )

        await self.controller.assign(device_info)
        return True

    async def _assign_device_by_stable_id(self, stable_id: str, command_id: Optional[str]) -> bool:
        device = await get_device_by_stable_id(stable_id)
        if not device:
            self.logger.error("Device not found: %s", stable_id)
            if StatusMessage:
                StatusMessage.send("device_error", {"error": "Device not found"}, command_id=command_id)
            return False

        return await self._assign_device_by_path(device.dev_path, command_id)

    async def _handle_start_recording(self, command: Dict[str, Any]) -> bool:
        state = self.controller.state
        if not state.streaming and state.ready:
            await self.controller.start_streaming()
            await asyncio.sleep(0.5)

        session_dir = command.get("session_dir")
        if session_dir:
            self._session_dir = Path(session_dir)
        elif not self._session_dir:
            self._session_dir = Path("/tmp/cameras_usb")

        trial = command.get("trial_number", self._trial_number)
        self._session_dir.mkdir(parents=True, exist_ok=True)

        await self.controller.start_recording(self._session_dir, trial)
        self._trial_number = trial + 1
        return True

    def _on_status(self, status_type: str, payload: dict) -> None:
        self.logger.debug("Status: %s %s", status_type, payload)

        if status_type == "camera_ready":
            if self._pending_device_ready:
                device_id, command_id = self._pending_device_ready
                self._pending_device_ready = None
                if StatusMessage:
                    StatusMessage.send("device_ready", {"device_id": device_id}, command_id=command_id)

                self.logger.info("Camera ready, auto-starting streaming for preview")
                asyncio.create_task(self._auto_start_streaming())

                if self._auto_record and self._session_dir:
                    self.logger.info("Auto-starting recording")
                    asyncio.create_task(self._auto_start_recording())

        elif status_type == "error":
            if self._pending_device_ready:
                device_id, command_id = self._pending_device_ready
                self._pending_device_ready = None
                if StatusMessage:
                    StatusMessage.send("device_error", {
                        "device_id": device_id,
                        "error": payload.get("message", "Unknown error"),
                    }, command_id=command_id)

        elif status_type == "recording_started":
            if StatusMessage:
                StatusMessage.send("recording_started", payload)

        elif status_type == "recording_stopped":
            if StatusMessage:
                StatusMessage.send("recording_stopped", payload)

    async def _auto_start_streaming(self) -> None:
        try:
            await asyncio.sleep(0.3)
            state = self.controller.state
            if not state.ready or state.streaming:
                return
            await self.controller.start_streaming()
        except Exception as e:
            self.logger.error("_auto_start_streaming failed: %s", e)

    async def _auto_start_recording(self) -> None:
        await asyncio.sleep(0.5)
        await self.controller.start_streaming()
        await asyncio.sleep(1.0)
        if self._session_dir:
            await self.controller.start_recording(self._session_dir, self._trial_number)
            self._trial_number += 1

    def _save_settings(self, settings: CameraSettings) -> None:
        if not self._preferences:
            return

        updates = {
            "frame_rate": str(settings.frame_rate),
            "preview_scale": str(settings.preview_scale),
            "preview_divisor": str(settings.preview_divisor),
            "audio_mode": settings.audio_mode,
            "sample_rate": str(settings.sample_rate),
        }
        self._preferences.write_sync(updates)


def factory(ctx: RuntimeContext) -> USBCamerasRuntime:
    return USBCamerasRuntime(ctx)
