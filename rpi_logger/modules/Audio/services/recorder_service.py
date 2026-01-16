"""Recorder service."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from ..domain import AudioDeviceInfo, LevelMeter
from .device_recorder import AudioDeviceRecorder, RecordingHandle


class RecorderService:
    """Manage audio device recorder."""
    def __init__(self, logger: logging.Logger, sample_rate: int,
                 start_timeout: float, stop_timeout: float) -> None:
        self.logger = logger.getChild("RecorderService")
        self._default_sample_rate = max(1, int(sample_rate))
        self.start_timeout = start_timeout
        self.stop_timeout = stop_timeout
        self.recorder: AudioDeviceRecorder | None = None

    async def enable_device(self, device: AudioDeviceInfo, meter: LevelMeter) -> bool:
        effective_rate = self._resolve_sample_rate(device)
        if self.recorder and self.recorder.sample_rate != effective_rate:
            await self.disable_device()
        if self.recorder is None:
            self.recorder = AudioDeviceRecorder(device, effective_rate, meter, self.logger)
        try:
            await asyncio.wait_for(asyncio.to_thread(self.recorder.start_stream), timeout=self.start_timeout)
            return True
        except asyncio.TimeoutError:
            self.logger.warning("Timeout starting device %d", device.device_id)
        except Exception as exc:
            self.logger.warning("Failed to start device %d: %s", device.device_id, exc)
        self.recorder = None
        return False

    async def disable_device(self) -> None:
        if not (recorder := self.recorder):
            return
        self.recorder = None
        try:
            await asyncio.wait_for(asyncio.to_thread(recorder.stop_stream), timeout=self.stop_timeout)
        except Exception as exc:
            self.logger.debug("Device stop raised: %s", exc)

    async def begin_recording(self, session_dir: Path, trial_number: int) -> bool:
        if not self.recorder:
            self.logger.info("No recorder available for recording")
            return False
        try:
            await asyncio.to_thread(self.recorder.begin_recording, session_dir, trial_number)
            return True
        except Exception as exc:
            self.logger.error("Failed to prepare recorder: %s", exc)
            return False

    async def finish_recording(self) -> RecordingHandle | None:
        if not self.recorder:
            return None
        try:
            handle = await asyncio.to_thread(self.recorder.finish_recording)
            return handle
        except Exception as exc:
            self.logger.error("Failed to finish recording: %s", exc)
            return None

    async def stop_all(self) -> None:
        if self.recorder:
            self.logger.info("Stopping recorder")
            await self.disable_device()

    @property
    def any_recording_active(self) -> bool:
        return self.recorder is not None and self.recorder.recording

    def _resolve_sample_rate(self, device: AudioDeviceInfo) -> int:
        try:
            if (rate := int(float(device.sample_rate or 0))) > 0:
                return rate
        except (TypeError, ValueError):
            pass
        return self._default_sample_rate


__all__ = ["RecorderService"]
