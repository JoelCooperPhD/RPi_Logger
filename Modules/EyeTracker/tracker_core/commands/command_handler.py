
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

        # Get session_dir from command_data if available
        from pathlib import Path
        session_dir = None
        if "session_dir" in command_data:
            session_dir = Path(command_data["session_dir"])

        await self.system.recording_manager.start_recording(session_dir, trial_number)
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

    async def handle_custom_command(self, command: str, command_data: Dict[str, Any]) -> bool:
        """Handle Eye Tracker specific commands"""
        if command == "pause_tracker":
            await self.handle_pause_tracker(command_data)
            return True
        elif command == "resume_tracker":
            await self.handle_resume_tracker(command_data)
            return True
        return False  # Not handled

    async def handle_pause_tracker(self, command_data: Dict[str, Any]) -> None:
        """Pause eye tracker frame processing (CPU saving mode)"""
        try:
            if not hasattr(self.system, 'pause'):
                StatusMessage.send("error", {"message": "Pause not supported by this tracker"})
                return

            await self.system.pause()
            StatusMessage.send("tracker_paused", {"paused": True})
            self.logger.info("Eye tracker paused (CPU saving mode)")

        except Exception as e:
            self.logger.exception("Failed to pause tracker: %s", e)
            StatusMessage.send("error", {
                "message": f"Failed to pause tracker: {str(e)[:100]}"
            })

    async def handle_resume_tracker(self, command_data: Dict[str, Any]) -> None:
        """Resume eye tracker frame processing"""
        try:
            if not hasattr(self.system, 'resume'):
                StatusMessage.send("error", {"message": "Resume not supported by this tracker"})
                return

            await self.system.resume()
            StatusMessage.send("tracker_resumed", {"paused": False})
            self.logger.info("Eye tracker resumed")

        except Exception as e:
            self.logger.exception("Failed to resume tracker: %s", e)
            StatusMessage.send("error", {
                "message": f"Failed to resume tracker: {str(e)[:100]}"
            })

    async def handle_get_status(self, command_data: Dict[str, Any]) -> None:
        try:
            status_data = {
                "running": self.system.running,
                "recording": self.system.recording,
                "connected": hasattr(self.system, 'device_manager') and
                           self.system.device_manager.is_connected,
            }

            # Add paused status if available
            if hasattr(self.system, 'is_paused'):
                status_data["paused"] = self.system.is_paused()

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
