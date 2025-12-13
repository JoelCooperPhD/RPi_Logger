"""Device enablement logic for the audio module.

Device discovery is centralized in the main logger. This manager handles
enabling/disabling devices that are assigned by the main logger.
"""

from __future__ import annotations

import logging

from ..domain import AudioDeviceInfo, AudioState
from ..services import RecorderService


class DeviceManager:
    """Manage enable/disable of audio devices.

    Device discovery is now centralized in the main logger.
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

    async def toggle_device(self, device_id: int, enabled: bool) -> bool:
        """Toggle device enabled state.

        Args:
            device_id: The sounddevice index
            enabled: True to enable, False to disable

        Returns:
            True if the operation succeeded, False otherwise
        """
        self.logger.debug("Toggle requested for device %d (enabled=%s)", device_id, enabled)
        devices = self.state.devices
        if device_id not in devices:
            self.logger.info("Toggle ignored for missing device %s", device_id)
            return False

        if enabled:
            device = devices[device_id]
            meter = self.state.ensure_meter(device_id)
            already_selected = device_id in self.state.selected_devices
            if not already_selected:
                self.state.select_device(device)
            success = await self.recorder_service.enable_device(device, meter)
            if not success:
                self.logger.warning(
                    "Device %s (%d) failed to start streaming",
                    device.name,
                    device.device_id,
                )
                return False
            self.logger.info("Device %s (%d) enabled", device.name, device.device_id)
            return True
        else:
            self.state.deselect_device(device_id)
            await self.recorder_service.disable_device(device_id)
            self.logger.info("Device %d disabled", device_id)
            return True


__all__ = ["DeviceManager"]
