
import logging
from typing import TYPE_CHECKING, Dict, Any

from logger_core.commands import BaseCommandHandler, StatusMessage

if TYPE_CHECKING:
    from ..tracker_system import TrackerSystem


class CommandHandler(BaseCommandHandler):

    def __init__(self, system: 'TrackerSystem', gui=None):
        super().__init__(system, gui=gui)

    async def _start_recording_impl(self, command_data: Dict[str, Any], trial_number: int) -> bool:
        if not hasattr(self.system, 'recording_manager'):
            self.logger.error("Recording manager not available")
            return False

        await self.system.recording_manager.start_recording(trial_number)
        self.system.recording = True
        return True

    async def _stop_recording_impl(self, command_data: Dict[str, Any]) -> bool:
        if not hasattr(self.system, 'recording_manager'):
            self.logger.error("Recording manager not available")
            return False

        await self.system.recording_manager.stop_recording()
        self.system.recording = False
        return True

    def _update_session_dir(self, command_data: Dict[str, Any]) -> None:
        super()._update_session_dir(command_data)

        if "session_dir" in command_data:
            from pathlib import Path
            session_dir = Path(command_data["session_dir"])
            if hasattr(self.system, 'recording_manager'):
                self.system.recording_manager._output_root = session_dir
                session_dir.mkdir(parents=True, exist_ok=True)

    def _get_recording_started_status_data(self, trial_number: int) -> Dict[str, Any]:
        data = super()._get_recording_started_status_data(trial_number)
        if hasattr(self.system, 'recording_manager'):
            data["experiment_dir"] = str(self.system.recording_manager.current_experiment_dir)
        return data

    async def handle_get_status(self, command_data: Dict[str, Any]) -> None:
        try:
            status_data = {
                "running": self.system.running,
                "recording": self.system.recording,
                "connected": hasattr(self.system, 'device_manager') and
                           self.system.device_manager.is_connected,
            }

            if hasattr(self.system, 'frame_count'):
                status_data["frame_count"] = self.system.frame_count

            if self.system.recording and hasattr(self.system, 'recording_manager'):
                status_data["experiment_dir"] = str(
                    self.system.recording_manager.current_experiment_dir
                )

            StatusMessage.send("status_report", status_data)

        except Exception as e:
            self.logger.exception("Failed to get status: %s", e)
            StatusMessage.send("error", {
                "message": f"Failed to get status: {str(e)[:100]}"
            })
