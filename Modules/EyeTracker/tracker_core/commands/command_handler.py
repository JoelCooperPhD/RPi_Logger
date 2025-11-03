from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict

from logger_core.commands import BaseCommandHandler, StatusMessage

if TYPE_CHECKING:
    from ..tracker_system import TrackerSystem


class CommandHandler(BaseCommandHandler):

    def __init__(self, system: "TrackerSystem", gui=None):
        super().__init__(system, gui=gui)

    async def _start_recording_impl(self, command_data: Dict[str, Any], trial_number: int) -> bool:
        session_dir = None
        if "session_dir" in command_data:
            session_dir = Path(command_data["session_dir"])

        return await self.system.start_recording(session_dir=session_dir, trial_number=trial_number)

    async def _stop_recording_impl(self, command_data: Dict[str, Any]) -> bool:
        return await self.system.stop_recording()

    def _update_session_dir(self, command_data: Dict[str, Any]) -> None:
        super()._update_session_dir(command_data)

        if "session_dir" in command_data and hasattr(self.system, "recording_manager"):
            session_dir = Path(command_data["session_dir"])
            session_dir.mkdir(parents=True, exist_ok=True)
            self.system.recording_manager.set_session_context(session_dir)
            if hasattr(self.system, "config"):
                self.system.config.output_dir = str(session_dir)

    def _get_recording_started_status_data(self, trial_number: int) -> Dict[str, Any]:
        data = super()._get_recording_started_status_data(trial_number)
        data["session"] = getattr(self.system, "session_label", None)
        if hasattr(self.system, "recording_manager"):
            data["experiment_dir"] = str(self.system.recording_manager.current_experiment_dir)
        return data

    async def handle_custom_command(self, command: str, command_data: Dict[str, Any]) -> bool:
        """Handle Eye Tracker specific commands"""
        if command == "pause_tracker":
            await self.handle_pause_tracker(command_data)
            return True
        if command == "resume_tracker":
            await self.handle_resume_tracker(command_data)
            return True
        return False  # Not handled

    async def handle_pause_tracker(self, command_data: Dict[str, Any]) -> None:
        """Pause eye tracker frame processing (CPU saving mode)"""
        try:
            if not hasattr(self.system, "pause"):
                StatusMessage.send("error", {"message": "Pause not supported by this tracker"})
                return

            await self.system.pause()
            StatusMessage.send("tracker_paused", {"paused": True})
            self.logger.info("Eye tracker paused (CPU saving mode)")

        except Exception as exc:
            self.logger.exception("Failed to pause tracker: %s", exc)
            StatusMessage.send("error", {"message": f"Failed to pause tracker: {str(exc)[:100]}"})

    async def handle_resume_tracker(self, command_data: Dict[str, Any]) -> None:
        """Resume eye tracker frame processing"""
        try:
            if not hasattr(self.system, "resume"):
                StatusMessage.send("error", {"message": "Resume not supported by this tracker"})
                return

            await self.system.resume()
            StatusMessage.send("tracker_resumed", {"paused": False})
            self.logger.info("Eye tracker resumed")

        except Exception as exc:
            self.logger.exception("Failed to resume tracker: %s", exc)
            StatusMessage.send("error", {"message": f"Failed to resume tracker: {str(exc)[:100]}"})

    async def handle_get_status(self, command_data: Dict[str, Any]) -> None:
        try:
            status_data = {
                "running": self.system.running,
                "recording": self.system.recording,
                "connected": hasattr(self.system, "device_manager")
                and self.system.device_manager.is_connected,
                "session": getattr(self.system, "session_label", None),
            }

            if hasattr(self.system, "is_paused"):
                status_data["paused"] = self.system.is_paused()

            if hasattr(self.system, "frame_count"):
                status_data["frame_count"] = self.system.frame_count

            if self.system.recording and hasattr(self.system, "recording_manager"):
                status_data["experiment_dir"] = str(
                    self.system.recording_manager.current_experiment_dir
                )

            StatusMessage.send("status_report", status_data)

        except Exception as exc:
            self.logger.exception("Failed to get status: %s", exc)
            StatusMessage.send("error", {"message": f"Failed to get status: {str(exc)[:100]}"})
