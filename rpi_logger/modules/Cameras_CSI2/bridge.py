"""CSI2 camera runtime using Elm/Redux architecture internally.

Presents ModuleRuntime interface to StubCodexSupervisor while using
pure state machine (Store) for all business logic.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from rpi_logger.core.commands import StatusMessage, StatusType
from rpi_logger.core.logging_utils import get_module_logger

# Ensure module can find sibling packages
_module_dir = Path(__file__).resolve().parent
if str(_module_dir) not in sys.path:
    sys.path.insert(0, str(_module_dir))

from core import (
    AppState, CameraStatus, RecordingStatus,
    Action, AssignCamera, UnassignCamera, CameraAssigned, CameraError,
    StartRecording, StopRecording, RecordingStarted, RecordingStopped,
    Shutdown, FrameReceived, UpdateMetrics,
    create_store, Store,
)
from infra import EffectExecutor
from ui.view import CSI2CameraView

try:
    from vmc.runtime import ModuleRuntime, RuntimeContext
except Exception:
    ModuleRuntime = object
    RuntimeContext = Any

logger = get_module_logger(__name__)


class CSI2CamerasRuntime(ModuleRuntime):
    """Runtime using Elm/Redux Store internally for state management."""

    def __init__(self, ctx: RuntimeContext) -> None:
        self.ctx = ctx
        self.logger = ctx.logger.getChild("CSI2Cameras") if hasattr(ctx, "logger") else logger
        self.module_dir = ctx.module_dir

        self.store: Store = create_store()

        self._pending_device_ready: Optional[tuple[str, Optional[str]]] = None
        self._session_dir: Optional[Path] = None
        self._trial_number: int = 1
        self._auto_record: bool = False

        self.executor = EffectExecutor(
            status_callback=self._on_effect_status,
            logger=self.logger,
        )
        self.store.set_effect_handler(self.executor)

        self.view = CSI2CameraView(ctx.view, logger=self.logger)

    async def start(self) -> None:
        self.logger.info("=" * 60)
        self.logger.info("CSI2 CAMERAS RUNTIME STARTING (Elm/Redux architecture)")
        self.logger.info("=" * 60)

        args = self.ctx.args
        self.logger.info("LAUNCH PARAMETERS:")
        self.logger.info("  instance_id:     %s", getattr(args, "instance_id", None))
        self.logger.info("  camera_index:    %s", getattr(args, "camera_index", None))
        self.logger.info("  output_dir:      %s", getattr(args, "output_dir", None))
        self.logger.info("  record:          %s", getattr(args, "record", False))
        self.logger.info("=" * 60)

        self._auto_record = getattr(args, "record", False)
        if output_dir := getattr(args, "output_dir", None):
            self._session_dir = Path(output_dir)

        if self.ctx.view:
            with contextlib.suppress(Exception):
                self.ctx.view.set_preview_title("CSI2 Camera")
            if hasattr(self.ctx.view, "set_data_subdir"):
                self.ctx.view.set_data_subdir("Cameras_CSI2")

        self.view.attach()
        self.view.bind_dispatch(self.store.dispatch)
        self.store.subscribe(self.view.render)

        self.executor.set_preview_callback(self.view.push_frame)

        self.logger.info("CSI2 Cameras runtime ready")
        StatusMessage.send("ready")

        camera_index = getattr(self.ctx.args, "camera_index", None)

        if camera_index is not None:
            self.logger.info("Auto-assigning CSI camera %d via CLI arg", camera_index)
            await self._assign_camera({
                "command_id": "cli_auto_assign",
                "device_id": f"picam:{camera_index}",
                "camera_index": camera_index,
            })
        else:
            self.logger.info("Waiting for assign_device command")

    async def shutdown(self) -> None:
        self.logger.info("Shutting down CSI2 Cameras runtime")
        await self.store.dispatch(Shutdown())

    async def cleanup(self) -> None:
        pass

    async def handle_command(self, command: Dict[str, Any]) -> bool:
        action = (command.get("command") or "").lower()
        self.logger.debug("Received command: %s", action)

        if action == "assign_device":
            return await self._assign_camera(command)
        if action == "unassign_device":
            await self.store.dispatch(UnassignCamera())
            return True
        if action == "unassign_all_devices":
            command_id = command.get("command_id")
            state = self.store.state
            port_released = state.camera_status != CameraStatus.IDLE
            if port_released:
                await self.store.dispatch(UnassignCamera())
            StatusMessage.send(StatusType.DEVICE_UNASSIGNED, {
                "device_id": state.camera_id or "",
                "port_released": port_released,
            }, command_id=command_id)
            return True
        if action in {"start_recording", "record"}:
            if sd := command.get("session_dir"):
                self._session_dir = Path(sd)
            if (tn := command.get("trial_number")) is not None:
                self._trial_number = int(tn)
            session_dir = self._session_dir or Path.home() / "recordings"
            await self.store.dispatch(StartRecording(session_dir, self._trial_number))
            return True
        if action in {"stop_recording", "pause", "pause_recording"}:
            await self.store.dispatch(StopRecording())
            return True
        if action == "start_session":
            if sd := command.get("session_dir"):
                self._session_dir = Path(sd)
            return True
        if action == "stop_session":
            state = self.store.state
            if state.recording_status == RecordingStatus.RECORDING:
                await self.store.dispatch(StopRecording())
            return True
        return False

    async def handle_user_action(self, action: str, **kwargs: Any) -> bool:
        return await self.handle_command({"command": action, **kwargs})

    async def healthcheck(self) -> Dict[str, Any]:
        state = self.store.state
        return {
            "assigned": state.camera_status != CameraStatus.IDLE,
            "recording": state.recording_status == RecordingStatus.RECORDING,
            "camera_id": state.camera_id,
        }

    async def on_session_dir_available(self, path: Path) -> None:
        self._session_dir = path

    async def _assign_camera(self, command: Dict[str, Any]) -> bool:
        state = self.store.state
        if state.camera_status != CameraStatus.IDLE:
            self.logger.debug("Camera already assigned - ignoring duplicate")
            return True

        command_id = command.get("command_id")
        device_id = command.get("device_id", "")

        camera_index = 0
        if "camera_index" in command:
            camera_index = command["camera_index"]
        elif device_id.startswith("picam:"):
            try:
                camera_index = int(device_id.split(":")[1])
            except (ValueError, IndexError):
                camera_index = 0

        self._pending_device_ready = (device_id, command_id)
        await self.store.dispatch(AssignCamera(camera_index))
        return True

    def _on_effect_status(self, status_type: str, payload: dict) -> None:
        self.logger.debug("Effect status: %s - %s", status_type, payload)

        if status_type == "camera_assigned":
            if self._pending_device_ready:
                device_id, command_id = self._pending_device_ready
                self._pending_device_ready = None
                self.logger.info("Camera assigned - sending device_ready: %s", device_id)
                StatusMessage.send("device_ready", {"device_id": device_id}, command_id=command_id)

                controller = getattr(self.ctx, "controller", None)
                if controller and hasattr(controller, "start_command_listener"):
                    asyncio.create_task(controller.start_command_listener())

                if self._auto_record:
                    self._auto_record = False
                    session_dir = self._session_dir or Path.home() / "recordings"
                    self.logger.info("AUTO-RECORD: Starting recording to %s", session_dir)
                    asyncio.create_task(self.store.dispatch(StartRecording(session_dir, self._trial_number)))

        elif status_type == "camera_error":
            if self._pending_device_ready:
                device_id, command_id = self._pending_device_ready
                self._pending_device_ready = None
                StatusMessage.send("device_error", {
                    "device_id": device_id,
                    "error": payload.get("error", "Unknown error"),
                }, command_id=command_id)

        elif status_type == "recording_started":
            StatusMessage.send("recording_started", {
                "video_path": payload.get("video_path"),
                "camera_id": payload.get("camera_id"),
            })

        elif status_type == "recording_stopped":
            StatusMessage.send("recording_stopped", {
                "camera_id": payload.get("camera_id"),
            })


def factory(ctx: RuntimeContext) -> CSI2CamerasRuntime:
    return CSI2CamerasRuntime(ctx)
