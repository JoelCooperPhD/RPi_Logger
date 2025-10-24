
import asyncio
import logging
from typing import TYPE_CHECKING, Dict, Any

from logger_core.commands import BaseCommandHandler, StatusMessage

if TYPE_CHECKING:
    from ..audio_system import AudioSystem


class CommandHandler(BaseCommandHandler):

    def __init__(self, audio_system: 'AudioSystem', gui=None, mode=None):
        super().__init__(audio_system, gui=gui)
        self.mode = mode

    async def _start_recording_impl(self, command_data: Dict[str, Any], trial_number: int) -> bool:
        capture_manager = getattr(self.mode, 'capture_manager', None) if self.mode else None

        if capture_manager:
            try:
                for device_id in self.system.selected_devices:
                    await capture_manager.stop_capture_for_device(device_id)
                    self.logger.debug("Stopped capture for device %d before recording", device_id)

                await asyncio.sleep(0.5)
            except Exception as e:
                self.logger.error("Error stopping capture: %s", e, exc_info=True)

        return await self.system.start_recording(trial_number)

    async def _stop_recording_impl(self, command_data: Dict[str, Any]) -> bool:
        await self.system.stop_recording()

        capture_manager = getattr(self.mode, 'capture_manager', None) if self.mode else None
        if capture_manager:
            for device_id in self.system.selected_devices:
                await capture_manager.start_capture_for_device(device_id)
                self.logger.debug("Restarted capture for device %d after recording", device_id)

        return True

    def _get_recording_started_status_data(self, trial_number: int) -> Dict[str, Any]:
        return {
            "devices": len(self.system.active_handlers),
            "recording_count": self.system.recording_count,
            "trial": trial_number
        }

    def _get_recording_stopped_status_data(self) -> Dict[str, Any]:
        return {
            "recording_count": self.system.recording_count
        }

    async def handle_get_status(self, command_data: Dict[str, Any]) -> None:
        status_data = {
            "recording": self.system.recording,
            "recording_count": self.system.recording_count,
            "devices_available": len(self.system.available_devices),
            "devices_selected": len(self.system.selected_devices),
            "devices_recording": len(self.system.active_handlers) if self.system.recording else 0,
            "session": self.system.session_label,
        }
        StatusMessage.send("status_report", status_data)
        self.logger.debug("Status report sent")

    async def handle_custom_command(self, command: str, command_data: Dict[str, Any]) -> bool:
        if command == "toggle_device":
            device_id = command_data.get("device_id")
            enabled = command_data.get("enabled", True)
            return await self._handle_toggle_device(device_id, enabled)

        return False  # Not handled

    async def _handle_toggle_device(self, device_id: int, enabled: bool) -> bool:
        if device_id is None:
            StatusMessage.send("error", {"message": "device_id required"})
            return True

        if enabled:
            success = self.system.select_device(device_id)
            action = "selected"
        else:
            success = self.system.deselect_device(device_id)
            action = "deselected"

        if success:
            StatusMessage.send("device_toggled", {
                "device_id": device_id,
                "enabled": enabled
            })
            self.logger.info("Device %d %s", device_id, action)
        else:
            StatusMessage.send("error", {"message": f"Failed to toggle device {device_id}"})

        return True
