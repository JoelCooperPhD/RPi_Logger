"""Device enable/disable management."""
from __future__ import annotations

import logging
from ..domain import AudioDeviceInfo, AudioState, LevelMeter
from ..services import RecorderService


class DeviceManager:
    """Manage audio device enable/disable."""
    def __init__(self, state: AudioState, recorder_service: RecorderService, logger: logging.Logger) -> None:
        self.state = state
        self.recorder_service = recorder_service
        self.logger = logger.getChild("DeviceManager")

    async def enable_device(self, device: AudioDeviceInfo) -> bool:
        self.state.set_device(device)
        meter = self.state.level_meter or LevelMeter()
        if not await self.recorder_service.enable_device(device, meter):
            self.logger.warning("Device %s (%d) failed to start streaming", device.name, device.device_id)
            self.state.clear_device()
            return False
        self.logger.info("Device %s (%d) enabled", device.name, device.device_id)
        return True

    async def disable_device(self) -> bool:
        if self.state.device is None:
            return True
        device_id = self.state.device.device_id
        await self.recorder_service.disable_device()
        self.state.clear_device()
        self.logger.info("Device %d disabled", device_id)
        return True


__all__ = ["DeviceManager"]
