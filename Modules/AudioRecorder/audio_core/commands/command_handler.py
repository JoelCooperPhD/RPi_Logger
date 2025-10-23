
import logging
from typing import TYPE_CHECKING, Dict, Any

from logger_core.commands import BaseCommandHandler, StatusMessage

if TYPE_CHECKING:
    from ..audio_system import AudioSystem


class CommandHandler(BaseCommandHandler):

    def __init__(self, audio_system: 'AudioSystem', gui=None):
        super().__init__(audio_system, gui=gui)

    async def handle_start_recording(self, command_data: Dict[str, Any]) -> None:
        if not self._check_recording_state(should_be_recording=False):
            return

        success = await self.system.start_recording()
        if success:
            device_count = len(self.system.active_handlers)
            StatusMessage.send("recording_started", {
                "devices": device_count,
                "recording_count": self.system.recording_count
            })
            self.logger.info("Recording started on %d devices", device_count)
        else:
            StatusMessage.send("error", {"message": "Failed to start recording"})

    async def handle_stop_recording(self, command_data: Dict[str, Any]) -> None:
        if not self._check_recording_state(should_be_recording=True):
            return

        await self.system.stop_recording()
        StatusMessage.send("recording_stopped", {
            "recording_count": self.system.recording_count
        })
        self.logger.info("Recording stopped")

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
