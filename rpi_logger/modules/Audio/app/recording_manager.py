"""Recording/session orchestration helpers for the audio module."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Callable

from rpi_logger.core.commands import StatusType
from rpi_logger.modules.base.storage_utils import ensure_module_data_dir

from ..domain import AudioState
from ..services import RecorderService, SessionService
from .module_bridge import ModuleBridge


class RecordingManager:
    """Coordinate session creation and recorder lifecycle."""

    def __init__(
        self,
        state: AudioState,
        recorder_service: RecorderService,
        session_service: SessionService,
        module_bridge: ModuleBridge,
        logger: logging.Logger,
        status_callback: Callable[[StatusType, dict[str, object]], None],
    ) -> None:
        self.state = state
        self.recorder_service = recorder_service
        self.session_service = session_service
        self.module_bridge = module_bridge
        self.logger = logger.getChild("RecordingManager")
        self._emit_status = status_callback
        self._active_session_dir: Path | None = None
        self._module_subdir = "Audio"
        self._start_lock = asyncio.Lock()

    async def ensure_session_dir(self, current: Path | None) -> Path:
        session_dir = await self.session_service.ensure_session_dir(current)
        self._active_session_dir = session_dir
        self.module_bridge.set_session_dir(session_dir)
        self.state.set_session_dir(session_dir)
        return session_dir

    async def start(self, device_ids: list[int], trial_number: int) -> bool:
        self.logger.debug(
            "Recording start requested for trial %d with devices %s",
            trial_number,
            device_ids,
        )
        if self.state.recording or self._start_lock.locked():
            self.logger.debug("Recording already active or starting")
            return False
        async with self._start_lock:
            if self.state.recording:
                self.logger.debug("Recording already active inside lock")
                return False
            if not device_ids:
                self.logger.warning("No devices selected for recording")
                return False

            session_dir = await self.ensure_session_dir(self.state.session_dir)
            module_dir = await asyncio.to_thread(
                ensure_module_data_dir,
                session_dir,
                self._module_subdir,
            )
            started = await self.recorder_service.begin_recording(device_ids, module_dir, trial_number)
            if started == 0:
                self.logger.error("No recorders ready; aborting start")
                return False

            self.state.set_recording(True, trial_number)
            self.module_bridge.set_recording(True, trial_number)
            self._emit_status(
                StatusType.RECORDING_STARTED,
                {
                    "trial_number": trial_number,
                    "devices": started,
                    "session_dir": str(session_dir),
                },
            )
            self.logger.info(
                "Recording started for trial %d (%d device%s)",
                trial_number,
                started,
                "s" if started != 1 else "",
            )
            return True

    async def stop(self) -> bool:
        self.logger.debug("Recording stop requested (active=%s)", self.state.recording)
        if not self.state.recording:
            return False

        recordings = await self.recorder_service.finish_recording()
        trial = self.state.trial_number
        self.state.set_recording(False, trial)
        self.module_bridge.set_recording(False, trial)

        session_dir = self._active_session_dir or self.state.session_dir
        artifact_payload = []
        for handle in recordings:
            artifact_payload.append({
                "audio_file": str(handle.file_path),
                "timing_csv": str(handle.timing_csv_path),
                "device_id": handle.device_id,
                "device_name": handle.device_name,
                "start_time_unix": handle.start_time_unix,
                "start_time_monotonic": handle.start_time_monotonic,
            })
        payload = {
            "trial_number": trial,
            "recordings": artifact_payload,
            "session_dir": str(session_dir) if session_dir else None,
        }
        self._emit_status(StatusType.RECORDING_STOPPED, payload)
        self.logger.info(
            "Recording stopped (%d file%s)",
            len(artifact_payload),
            "s" if len(artifact_payload) != 1 else "",
        )
        return True


__all__ = ["RecordingManager"]
