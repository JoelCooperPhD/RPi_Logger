"""
Session Recovery Observer - Manages running_modules.json for crash recovery.

This observer maintains the running_modules.json file which tracks which
modules were running. This allows the system to restore the previous state
after a crash or unexpected shutdown.
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Set, Optional

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.core.module_state_manager import (
    StateChange,
    StateEvent,
    ActualState,
    RUNNING_STATES,
    STOPPED_STATES,
)


class SessionRecoveryObserver:
    """
    Manages the running_modules.json state file for crash recovery.

    This observer:
    1. Updates running_modules.json when modules start/stop
    2. Tracks which modules should be auto-started on next launch
    3. Handles the cleanup of the state file after successful startup
    """

    def __init__(self, state_file_path: Path):
        """
        Initialize the observer.

        Args:
            state_file_path: Path to the running_modules.json file
        """
        self.logger = get_module_logger("SessionRecoveryObserver")
        self._state_file = state_file_path
        self._write_lock = asyncio.Lock()

        # Track forcefully stopped modules (shouldn't auto-restart)
        self._forcefully_stopped: Set[str] = set()

        # Track if we're in startup phase
        self._startup_phase = True
        self._pending_cleanup = False

    async def __call__(self, change: StateChange) -> None:
        """Handle state change events."""
        if change.event == StateEvent.ACTUAL_STATE_CHANGED:
            await self._handle_actual_state_change(change)

        elif change.event == StateEvent.STARTUP_COMPLETE:
            await self._handle_startup_complete(change)

    async def _handle_actual_state_change(self, change: StateChange) -> None:
        """Handle module actual state changes."""
        module_name = change.module_name
        new_state: ActualState = change.new_value
        old_state: ActualState = change.old_value

        # Module started running
        if new_state in RUNNING_STATES and old_state in STOPPED_STATES:
            self._forcefully_stopped.discard(module_name)
            if not self._startup_phase:
                await self._update_state_file()

        # Module stopped
        elif new_state in STOPPED_STATES and old_state in RUNNING_STATES:
            if not self._startup_phase:
                await self._update_state_file()

    async def _handle_startup_complete(self, change: StateChange) -> None:
        """Handle startup completion."""
        self._startup_phase = False
        success = change.new_value

        if success and self._pending_cleanup:
            await self._delete_state_file()
            self._pending_cleanup = False

        # Write current state
        await self._update_state_file()

    def mark_forcefully_stopped(self, module_name: str) -> None:
        """Mark a module as forcefully stopped (shouldn't auto-restart)."""
        self._forcefully_stopped.add(module_name)
        self.logger.info(
            "Marked module %s as forcefully stopped", module_name
        )

    def clear_forcefully_stopped(self, module_name: str) -> None:
        """Clear the forcefully stopped flag for a module."""
        self._forcefully_stopped.discard(module_name)

    def get_forcefully_stopped(self) -> Set[str]:
        """Get set of forcefully stopped module names."""
        return self._forcefully_stopped.copy()

    def set_pending_cleanup(self) -> None:
        """Mark that state file should be cleaned up after startup."""
        self._pending_cleanup = True

    def end_startup_phase(self) -> None:
        """Mark the end of startup phase."""
        self._startup_phase = False

    # =========================================================================
    # State File Operations
    # =========================================================================

    async def load_state_file(self) -> Optional[Set[str]]:
        """
        Load the running modules from the state file.

        Returns:
            Set of module names that were running, or None if file doesn't exist
        """
        if not self._state_file.exists():
            self.logger.debug("No state file found at %s", self._state_file)
            return None

        try:
            def read_file():
                with open(self._state_file, 'r') as f:
                    return json.load(f)

            state = await asyncio.to_thread(read_file)
            running_modules = set(state.get('running_modules', []))

            self.logger.info(
                "Loaded %d modules from state file: %s",
                len(running_modules), running_modules
            )

            # Mark for cleanup after successful startup
            self._pending_cleanup = True

            return running_modules

        except Exception as e:
            self.logger.error(
                "Error loading state file: %s", e, exc_info=True
            )
            return None

    async def _update_state_file(self, running_modules: Optional[Set[str]] = None) -> bool:
        """
        Update the state file with currently running modules.

        This is called by the ModuleManager/LoggerSystem, not directly by observers.
        """
        # This method will be called by LoggerSystem which tracks running modules
        # The observer doesn't track this directly to avoid circular dependencies
        pass

    async def write_state_file(self, running_modules: Set[str]) -> bool:
        """
        Write the running modules to the state file.

        Args:
            running_modules: Set of module names currently running

        Returns:
            True if write succeeded
        """
        # Filter out forcefully stopped modules
        modules_to_save = [
            m for m in running_modules
            if m not in self._forcefully_stopped
        ]

        async with self._write_lock:
            try:
                if not modules_to_save:
                    # No modules to save - delete file if exists
                    return await self._delete_state_file()

                # Ensure parent directory exists
                await asyncio.to_thread(
                    self._state_file.parent.mkdir,
                    parents=True,
                    exist_ok=True
                )

                state = {
                    'timestamp': datetime.now().isoformat(),
                    'running_modules': sorted(modules_to_save),
                }

                def write_file():
                    with open(self._state_file, 'w') as f:
                        json.dump(state, f, indent=2)

                await asyncio.to_thread(write_file)

                self.logger.info(
                    "Wrote %d modules to state file: %s",
                    len(modules_to_save), modules_to_save
                )
                return True

            except Exception as e:
                self.logger.error(
                    "Error writing state file: %s", e, exc_info=True
                )
                return False

    async def _delete_state_file(self) -> bool:
        """Delete the state file."""
        if not self._state_file.exists():
            return True

        try:
            await asyncio.to_thread(self._state_file.unlink)
            self.logger.info("Deleted state file: %s", self._state_file)
            return True
        except Exception as e:
            self.logger.error(
                "Error deleting state file: %s", e, exc_info=True
            )
            return False

    async def save_shutdown_state(self, running_modules: Set[str]) -> bool:
        """
        Save the final state before shutdown.

        This is called during shutdown to persist which modules should
        be restarted on next launch.

        Args:
            running_modules: Set of module names that are currently running

        Returns:
            True if save succeeded
        """
        return await self.write_state_file(running_modules)

    async def finalize_shutdown_state(self, running_modules: Set[str]) -> bool:
        """
        Finalize the shutdown state after modules have stopped.

        This updates the state file to exclude any modules that failed
        to stop cleanly (forcefully stopped).

        Args:
            running_modules: Set of modules that were supposed to be running

        Returns:
            True if update succeeded
        """
        # Re-filter in case more modules were forcefully stopped during shutdown
        return await self.write_state_file(running_modules)
