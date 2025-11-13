import asyncio
import datetime
import logging
from pathlib import Path
from typing import Optional, Dict

from ..logger_system import LoggerSystem
from ..module_process import ModuleState
from ..shutdown_coordinator import get_shutdown_coordinator


class HeadlessController:
    """
    Headless controller for CLI operation.

    Similar to MainController but without GUI dependencies.
    Provides programmatic control over the logger system.
    """

    def __init__(self, logger_system: LoggerSystem):
        self.logger = logging.getLogger("HeadlessController")
        self.logger_system = logger_system
        self.logger_system.ui_callback = self._status_callback

        self.trial_counter: int = 0
        self.session_active = False
        self.trial_active = False
        self.trial_label: str = ""

    async def _status_callback(self, module_name: str, state: ModuleState, status) -> None:
        """Handle module status updates."""
        self.logger.info("Module %s state changed to: %s", module_name, state.value)

    async def auto_start_modules(self) -> None:
        """Auto-start modules based on configuration."""
        await asyncio.sleep(0.5)

        for module_name, enabled in self.logger_system.get_module_enabled_states().items():
            if enabled:
                self.logger.info("Auto-starting module: %s", module_name)
                success = await self.logger_system.set_module_enabled(module_name, True)
                if success:
                    self.logger.info("Module %s started successfully", module_name)
                    if self.logger_system.event_logger:
                        await self.logger_system.event_logger.log_module_started(module_name)
                else:
                    self.logger.error("Failed to start module: %s", module_name)

    async def start_module(self, module_name: str) -> bool:
        """Start a specific module."""
        if self.logger_system.event_logger:
            await self.logger_system.event_logger.log_button_press(f"module_{module_name}", "enable")

        self.logger_system.toggle_module_enabled(module_name, True)
        self.logger.info("Starting module: %s", module_name)

        success = await self.logger_system.set_module_enabled(module_name, True)
        if not success:
            self.logger.error("Failed to start module: %s", module_name)
            return False

        self.logger.info("Module %s started successfully", module_name)
        if self.logger_system.event_logger:
            await self.logger_system.event_logger.log_module_started(module_name)

        return True

    async def stop_module(self, module_name: str) -> bool:
        """Stop a specific module."""
        if self.logger_system.event_logger:
            await self.logger_system.event_logger.log_button_press(f"module_{module_name}", "disable")

        self.logger.info("Stopping module: %s", module_name)

        success = await self.logger_system.set_module_enabled(module_name, False)
        if not success:
            self.logger.warning("Failed to stop module: %s", module_name)
            return False

        self.logger.info("Module %s stopped successfully", module_name)
        if self.logger_system.event_logger:
            await self.logger_system.event_logger.log_module_stopped(module_name)

        return True

    async def start_session(self, session_dir: Optional[Path] = None) -> bool:
        """Start a recording session."""
        if self.session_active:
            self.logger.warning("Session already active")
            return False

        if session_dir is None:
            session_dir = self.logger_system.session_dir

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        session_name = f"{self.logger_system.session_prefix}_{timestamp}"
        full_session_dir = session_dir / session_name
        full_session_dir.mkdir(parents=True, exist_ok=True)

        self.logger_system.session_dir = full_session_dir

        from ..event_logger import EventLogger
        self.logger_system.event_logger = EventLogger(full_session_dir, timestamp)
        await self.logger_system.event_logger.initialize()

        await self.logger_system.event_logger.log_button_press("session_start")
        await self.logger_system.event_logger.log_session_start(str(full_session_dir))

        self.session_active = True
        self.trial_counter = 0

        self.logger.info("Session started in: %s", full_session_dir)

        await self.logger_system.start_session_all()

        return True

    async def stop_session(self) -> bool:
        """Stop the recording session."""
        if not self.session_active:
            self.logger.warning("No active session")
            return False

        if self.trial_active:
            await self.stop_trial()

        if self.logger_system.event_logger:
            await self.logger_system.event_logger.log_button_press("session_stop")
            await self.logger_system.event_logger.log_session_stop()

        await self.logger_system.stop_session_all()

        self.session_active = False

        self.logger.info("Session stopped")

        return True

    async def start_trial(self, trial_label: str = "") -> bool:
        """Start recording a trial."""
        if not self.session_active:
            self.logger.error("Cannot start trial - no active session")
            return False

        if self.trial_active:
            self.logger.warning("Trial already active")
            return False

        self.trial_label = trial_label
        next_trial_num = self.trial_counter + 1

        if self.logger_system.event_logger:
            await self.logger_system.event_logger.log_button_press("trial_record", f"trial={next_trial_num}")
            await self.logger_system.event_logger.log_trial_start(next_trial_num, trial_label)

        results = await self.logger_system.record_all(next_trial_num, trial_label)

        failed = [name for name, success in results.items() if not success]
        if failed:
            self.logger.warning("Failed to start recording on: %s", ", ".join(failed))

        self.trial_active = True

        self.logger.info("Trial %d started (label: %s)", next_trial_num, trial_label or "none")

        return True

    async def stop_trial(self) -> bool:
        """Stop recording the current trial."""
        if not self.trial_active:
            self.logger.warning("No active trial")
            return False

        results = await self.logger_system.pause_all()

        failed = [name for name, success in results.items() if not success]
        if failed:
            self.logger.warning("Failed to pause recording on: %s", ", ".join(failed))

        self.trial_active = False
        self.trial_counter += 1

        if self.logger_system.event_logger:
            await self.logger_system.event_logger.log_button_press("trial_pause", f"trial={self.trial_counter}")
            await self.logger_system.event_logger.log_trial_stop(self.trial_counter)

        self.logger.info(
            "Trial %d stopped (run python -m rpi_logger.tools.muxing_tool later to mux recordings)",
            self.trial_counter,
        )

        return True

    def get_status(self) -> Dict:
        """Get current system status."""
        return {
            "session_active": self.session_active,
            "trial_active": self.trial_active,
            "trial_counter": self.trial_counter,
            "session_dir": str(self.logger_system.session_dir) if self.session_active else None,
            "available_modules": [m.name for m in self.logger_system.get_available_modules()],
            "selected_modules": self.logger_system.get_selected_modules(),
            "running_modules": self.logger_system.get_running_modules(),
        }

    async def shutdown(self) -> None:
        """Graceful shutdown."""
        self.logger.info("Shutdown requested")

        if self.logger_system.event_logger:
            await self.logger_system.event_logger.log_button_press("shutdown")

        if self.trial_active:
            await self.stop_trial()

        if self.session_active:
            await self.stop_session()

        shutdown_coordinator = get_shutdown_coordinator()
        await shutdown_coordinator.initiate_shutdown("HeadlessController")
