from typing import Dict, Any
from logger_core.commands import BaseCommandHandler, StatusMessage


class CommandHandler(BaseCommandHandler):

    def __init__(self, gps_system, gui=None):
        super().__init__(gps_system, gui)

    async def handle_get_status(self, command_data: Dict[str, Any]) -> None:
        status_data = {
            "recording": self.system.recording,
            "initialized": self.system.initialized,
        }

        if self.system.gps_handler:
            gps_data = self.system.gps_handler.get_latest_data()
            status_data.update({
                "has_fix": gps_data.get('fix_quality', 0) > 0,
                "latitude": gps_data.get('latitude', 0.0),
                "longitude": gps_data.get('longitude', 0.0),
                "satellites": gps_data.get('satellites', 0),
            })

        StatusMessage.send("status", status_data)

    async def _start_recording_impl(self, command_data: Dict[str, Any], trial_number: int) -> bool:
        return await self.system.start_recording(trial_number)

    async def _stop_recording_impl(self, command_data: Dict[str, Any]) -> bool:
        return await self.system.stop_recording()
