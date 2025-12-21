"""Device enablement logic for the audio module.

Device discovery is centralized in the main logger. This manager handles
enabling/disabling the single device assigned by the main logger.
"""

from __future__ import annotations

import logging

from ..domain import AudioDeviceInfo, AudioState, LevelMeter
from ..services import RecorderService


class DeviceManager:
    """Manage enable/disable of the single audio device.

    Device discovery is centralized in the main logger.
    This manager handles device enablement after assignment.
    """

    def __init__(
        self,
        state: AudioState,
        recorder_service: RecorderService,
        logger: logging.Logger,
    ) -> None:
        self.state = state
        self.recorder_service = recorder_service
        self.logger = logger.getChild("DeviceManager")

    async def enable_device(self, device: AudioDeviceInfo) -> bool:
        """Enable the assigned device.

        Args:
            device: The device info to enable

        Returns:
            True if the operation succeeded, False otherwise
        """
        self.logger.debug("Enabling device %d (%s)", device.device_id, device.name)

        # Update state (creates level meter)
        self.state.set_device(device)
        meter = self.state.level_meter
        if meter is None:
            meter = LevelMeter()

        # Start the audio stream
        success = await self.recorder_service.enable_device(device, meter)
        if not success:
            self.logger.warning(
                "Device %s (%d) failed to start streaming",
                device.name,
                device.device_id,
            )
            self.state.clear_device()
            return False

        self.logger.info("Device %s (%d) enabled", device.name, device.device_id)
        return True

    async def disable_device(self) -> bool:
        """Disable the current device.

        Returns:
            True if the operation succeeded
        """
        if self.state.device is None:
            self.logger.debug("No device to disable")
            return True

        device_id = self.state.device.device_id
        self.logger.debug("Disabling device %d", device_id)

        await self.recorder_service.disable_device()
        self.state.clear_device()

        self.logger.info("Device %d disabled", device_id)
        return True


__all__ = ["DeviceManager"]
