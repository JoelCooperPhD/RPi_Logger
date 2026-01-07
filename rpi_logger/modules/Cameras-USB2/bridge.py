# CamerasRuntime - main orchestration
# Tasks: P4.1, P4.2, P4.3, P4.4

import asyncio
from dataclasses import dataclass
from typing import Callable, Awaitable

from .config import CamerasConfig
from .camera_core.types import CameraId, CameraDescriptor, CameraCapabilities


@dataclass
class RuntimeState:
    camera_id: CameraId | None = None
    descriptor: CameraDescriptor | None = None
    capabilities: CameraCapabilities | None = None
    capturing: bool = False
    recording: bool = False


class CamerasRuntime:
    def __init__(
        self,
        config: CamerasConfig,
        view=None,
        status_callback: Callable[[str, dict], Awaitable[None]] | None = None
    ):
        self._config = config
        self._view = view
        self._status_callback = status_callback
        self._state = RuntimeState()
        self._capture = None
        self._encoder = None
        self._capture_task: asyncio.Task | None = None
        self._stop_capture = asyncio.Event()

    async def initialize(self) -> None:
        await self._report_status("ready", {})

    async def shutdown(self) -> None:
        await self.unassign_device()

    async def _report_status(self, status: str, payload: dict) -> None:
        if self._status_callback:
            await self._status_callback(status, payload)

    async def assign_device(
        self,
        camera_id: CameraId,
        descriptor: CameraDescriptor
    ) -> None:
        # TODO: Implement - Task P4.2
        raise NotImplementedError("See docs/tasks/phase4_runtime.md P4.2")

    async def unassign_device(self) -> None:
        # TODO: Implement - Task P4.2
        if self._state.camera_id is None:
            return
        raise NotImplementedError("See docs/tasks/phase4_runtime.md P4.2")

    async def start_recording(
        self,
        session_prefix: str,
        trial_number: int,
        output_dir=None
    ) -> None:
        # TODO: Implement - Task P3.2
        raise NotImplementedError("See docs/tasks/phase3_recording.md P3.2")

    async def stop_recording(self) -> None:
        # TODO: Implement - Task P3.2
        raise NotImplementedError("See docs/tasks/phase3_recording.md P3.2")

    async def handle_command(self, command: str, payload: dict) -> None:
        # TODO: Implement - Task P4.3
        raise NotImplementedError("See docs/tasks/phase4_runtime.md P4.3")

    async def _capture_loop(self) -> None:
        # TODO: Implement - Task P2.3
        raise NotImplementedError("See docs/tasks/phase2_capture.md P2.3")
