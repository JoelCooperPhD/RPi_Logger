"""Service that manages per-device AudioDeviceRecorder instances."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Dict, List

from ..domain import AudioDeviceInfo, LevelMeter
from .device_recorder import AudioDeviceRecorder


class RecorderService:
    """Manage AudioDeviceRecorder instances keyed by device id."""

    def __init__(
        self,
        logger: logging.Logger,
        sample_rate: int,
        start_timeout: float,
        stop_timeout: float,
    ) -> None:
        self.logger = logger.getChild("RecorderService")
        self._default_sample_rate = max(1, int(sample_rate))
        self.start_timeout = start_timeout
        self.stop_timeout = stop_timeout
        self.recorders: Dict[int, AudioDeviceRecorder] = {}

    async def enable_device(self, device: AudioDeviceInfo, meter: LevelMeter) -> bool:
        effective_rate = self._resolve_sample_rate(device)
        recorder = self.recorders.get(device.device_id)
        if recorder and recorder.sample_rate != effective_rate:
            await self.disable_device(device.device_id)
            recorder = None
        if recorder is None:
            recorder = AudioDeviceRecorder(device, effective_rate, meter, self.logger)
            self.recorders[device.device_id] = recorder

        self.logger.debug("Enabling recorder for device %d (%s)", device.device_id, device.name)
        try:
            await asyncio.wait_for(
                asyncio.to_thread(recorder.start_stream),
                timeout=self.start_timeout,
            )
            return True
        except asyncio.TimeoutError:
            self.logger.error("Timeout starting device %d", device.device_id)
        except Exception as exc:
            self.logger.error("Failed to start device %d: %s", device.device_id, exc)
        self.recorders.pop(device.device_id, None)
        return False

    async def disable_device(self, device_id: int) -> None:
        recorder = self.recorders.pop(device_id, None)
        if not recorder:
            return
        self.logger.debug("Disabling recorder for device %d", device_id)
        try:
            await asyncio.wait_for(
                asyncio.to_thread(recorder.stop_stream),
                timeout=self.stop_timeout,
            )
        except Exception as exc:
            self.logger.debug("Device %d stop raised: %s", device_id, exc)

    async def begin_recording(
        self,
        device_ids: List[int],
        session_dir: Path,
        trial_number: int,
    ) -> int:
        started = 0
        for device_id in device_ids:
            recorder = self.recorders.get(device_id)
            if not recorder:
                continue
            try:
                self.logger.debug(
                    "Starting recording thread for device %d (trial %d)",
                    device_id,
                    trial_number,
                )
                await asyncio.to_thread(recorder.begin_recording, session_dir, trial_number)
                started += 1
            except Exception as exc:
                self.logger.error("Failed to prepare recorder %d: %s", device_id, exc)
        return started

    async def finish_recording(self) -> List[Path]:
        tasks = []
        for recorder in self.recorders.values():
            tasks.append(asyncio.to_thread(recorder.finish_recording))
        if not tasks:
            return []
        finished = await asyncio.gather(*tasks, return_exceptions=True)
        results: List[Path] = []
        for maybe_path in finished:
            if isinstance(maybe_path, Exception) or maybe_path is None:
                continue
            results.append(maybe_path)
        self.logger.debug("Finished %d recording file(s)", len(results))
        return results

    async def stop_all(self) -> None:
        device_ids = list(self.recorders.keys())
        if device_ids:
            self.logger.info("Stopping %d recorder(s)", len(device_ids))
        tasks = [self.disable_device(device_id) for device_id in device_ids]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.recorders.clear()

    @property
    def any_recording_active(self) -> bool:
        return any(recorder.recording for recorder in self.recorders.values())

    # ------------------------------------------------------------------
    # Internal helpers

    def _resolve_sample_rate(self, device: AudioDeviceInfo) -> int:
        try:
            candidate = device.sample_rate
            if candidate:
                rate = int(float(candidate))
                if rate > 0:
                    return rate
        except (TypeError, ValueError):
            pass
        return self._default_sample_rate


__all__ = ["RecorderService"]
