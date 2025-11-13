"""
Module Manager - Handles module discovery, selection, and lifecycle.

This module provides centralized management of logger modules including
discovery, selection state, and process lifecycle management.
"""

import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Optional, Callable, Set

from .module_discovery import ModuleInfo, discover_modules
from .module_process import ModuleProcess, ModuleState
from .commands import StatusMessage
from .window_manager import WindowGeometry
from .config_manager import get_config_manager


class ModuleManager:
    """
    Manages module discovery, selection, and lifecycle.

    Responsibilities:
    - Discover available modules
    - Track which modules are selected/enabled
    - Manage module processes (start, stop, status)
    - Handle module configuration
    """

    def __init__(
        self,
        session_dir: Path,
        session_prefix: str = "session",
        log_level: str = "info",
        status_callback: Optional[Callable] = None,
    ):
        self.logger = logging.getLogger("ModuleManager")
        self.session_dir = Path(session_dir)
        self.session_prefix = session_prefix
        self.log_level = log_level
        self.status_callback = status_callback

        self.available_modules: List[ModuleInfo] = []
        self.module_enabled_state: Dict[str, bool] = {}
        self.module_state_changing: Dict[str, bool] = {}
        self.module_processes: Dict[str, ModuleProcess] = {}
        self.state_change_callbacks: List[Callable] = []
        self.window_geometry_cache: Dict[str, Optional[WindowGeometry]] = {}
        self._state_locks: Dict[str, asyncio.Lock] = {}
        self.forcefully_stopped_modules: Set[str] = set()

        self.config_manager = get_config_manager()

        self._discover_modules()

    def _discover_modules(self) -> None:
        """Discover all available modules."""
        self.logger.info("Discovering modules...")
        self.available_modules = discover_modules()
        self.logger.info("Found %d modules: %s",
                        len(self.available_modules),
                        [m.name for m in self.available_modules])

    async def load_enabled_modules(self) -> None:
        """Load module enabled state from configs (sets state, does not start modules)."""
        self.module_enabled_state.clear()

        for module_info in self.available_modules:
            if not module_info.config_path:
                self.module_enabled_state[module_info.name] = True
                self.logger.debug("Module %s has no config, defaulting to enabled", module_info.name)
                continue

            config = await self.config_manager.read_config_async(module_info.config_path)
            enabled = self.config_manager.get_bool(config, 'enabled', default=True)

            self.module_enabled_state[module_info.name] = enabled
            if enabled:
                self.logger.info("Module %s enabled in config", module_info.name)
            else:
                self.logger.info("Module %s disabled in config", module_info.name)

    def get_available_modules(self) -> List[ModuleInfo]:
        """Get list of all discovered modules."""
        return self.available_modules

    def register_state_change_callback(self, callback: Callable) -> None:
        """Register a callback to be notified of module state changes."""
        self.state_change_callbacks.append(callback)

    async def _notify_state_change_started(self, module_name: str, target_state: bool) -> None:
        """Notify callbacks that state change has started."""
        for callback in self.state_change_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(module_name, "started", target_state)
                else:
                    callback(module_name, "started", target_state)
            except Exception as e:
                self.logger.error("State change callback error: %s", e)

    async def _notify_state_change_completed(self, module_name: str, target_state: bool, success: bool) -> None:
        """Notify callbacks that state change has completed."""
        for callback in self.state_change_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(module_name, "completed", target_state, success)
                else:
                    callback(module_name, "completed", target_state, success)
            except Exception as e:
                self.logger.error("State change callback error: %s", e)

    def _get_state_lock(self, module_name: str) -> asyncio.Lock:
        lock = self._state_locks.get(module_name)
        if lock is None:
            lock = asyncio.Lock()
            self._state_locks[module_name] = lock
        return lock

    async def set_module_enabled(self, module_name: str, enabled: bool) -> bool:
        """
        CENTRAL STATE MACHINE: Set module enabled state and start/stop accordingly.

        This is the SINGLE ENTRY POINT for all module state changes.
        All paths (GUI, CLI, config, crashes) route through here.

        Args:
            module_name: Name of the module
            enabled: True to enable/start, False to disable/stop

        Returns:
            True if state change succeeded, False otherwise
        """
        lock = self._get_state_lock(module_name)

        async with lock:
            current_state = self.module_enabled_state.get(module_name, False)
            is_running = self.is_module_running(module_name)

            if current_state == enabled and ((enabled and is_running) or (not enabled and not is_running)):
                self.logger.debug("Module %s already in desired state: enabled=%s, running=%s",
                                module_name, enabled, is_running)
                return True

            self.module_state_changing[module_name] = True
            await self._notify_state_change_started(module_name, enabled)

            success = False
            try:
                if enabled:
                    success = await self._start_module_internal(module_name)
                else:
                    success = await self._stop_module_internal(module_name)

                if success:
                    self.module_enabled_state[module_name] = enabled
                    self.logger.info("Module %s state changed to: %s", module_name, enabled)
                else:
                    self.logger.warning("Failed to change %s state to: %s", module_name, enabled)

            finally:
                self.module_state_changing[module_name] = False
                await self._notify_state_change_completed(module_name, enabled, success)

            return success

    def is_module_enabled(self, module_name: str) -> bool:
        """Check if a module is enabled (checkbox state)."""
        return self.module_enabled_state.get(module_name, False)

    def is_module_state_changing(self, module_name: str) -> bool:
        """Check if a module is currently transitioning state."""
        return self.module_state_changing.get(module_name, False)

    def get_module_enabled_states(self) -> Dict[str, bool]:
        """Get all module enabled states."""
        return self.module_enabled_state.copy()

    def select_module(self, module_name: str) -> bool:
        """
        Mark a module as enabled (LEGACY - prefer set_module_enabled).

        Args:
            module_name: Name of the module to select

        Returns:
            True if module exists and was selected, False otherwise
        """
        if not any(m.name == module_name for m in self.available_modules):
            self.logger.warning("Module not found: %s", module_name)
            return False

        self.module_enabled_state[module_name] = True
        self.logger.info("Selected module: %s", module_name)
        return True

    def deselect_module(self, module_name: str) -> None:
        """Remove a module from selection (LEGACY - prefer set_module_enabled)."""
        self.module_enabled_state[module_name] = False
        self.logger.info("Deselected module: %s", module_name)

    def get_selected_modules(self) -> List[str]:
        """Get list of currently enabled module names."""
        return [name for name, enabled in self.module_enabled_state.items() if enabled]

    def is_module_selected(self, module_name: str) -> bool:
        """Check if a module is currently enabled (LEGACY - prefer is_module_enabled)."""
        return self.module_enabled_state.get(module_name, False)

    def toggle_module_enabled(self, module_name: str, enabled: bool) -> bool:
        """
        Update a module's enabled state in its config file.

        Args:
            module_name: Name of the module
            enabled: New enabled state

        Returns:
            True if config was updated successfully, False otherwise
        """
        module_info = next(
            (m for m in self.available_modules if m.name == module_name),
            None
        )
        if not module_info or not module_info.config_path:
            self.logger.warning("Cannot update enabled state - no config for %s", module_name)
            return False

        success = self.config_manager.write_config(
            module_info.config_path,
            {'enabled': enabled}
        )

        if success:
            self.logger.info("Updated %s enabled state to %s", module_name, enabled)
        else:
            self.logger.error("Failed to update %s enabled state", module_name)

        return success

    def is_module_running(self, module_name: str) -> bool:
        """Check if a module process is currently running."""
        process = self.module_processes.get(module_name)
        return process is not None and process.is_running()

    def get_module_state(self, module_name: str) -> Optional[ModuleState]:
        """Get the current state of a module process."""
        process = self.module_processes.get(module_name)
        if process:
            return process.get_state()
        return None

    async def start_module(self, module_name: str) -> bool:
        """
        Start a module (PUBLIC API - delegates to state machine).

        Args:
            module_name: Name of the module to start

        Returns:
            True if module started successfully, False otherwise
        """
        return await self.set_module_enabled(module_name, True)

    def set_window_geometry(self, module_name: str, geometry: Optional[WindowGeometry]) -> None:
        """Cache window geometry for a module to use on next start."""
        self.window_geometry_cache[module_name] = geometry

    async def _start_module_internal(
        self,
        module_name: str
    ) -> bool:
        """
        Internal method to start a module process.

        Args:
            module_name: Name of the module to start

        Returns:
            True if module started successfully, False otherwise
        """
        window_geometry = self.window_geometry_cache.get(module_name)
        if module_name in self.module_processes:
            process = self.module_processes[module_name]

            if process.is_running() and process.get_state() != ModuleState.STOPPED:
                self.logger.info("Module %s still running (state=%s), stopping...", module_name, process.get_state())
                await process.stop()
                await asyncio.sleep(0.1)
            else:
                self.logger.debug("Module %s process exists but not running (state=%s), cleaning up",
                                module_name, process.get_state())

            self.module_processes.pop(module_name, None)

        # Find module info
        module_info = next(
            (m for m in self.available_modules if m.name == module_name),
            None
        )
        if not module_info:
            self.logger.error("Module info not found: %s", module_name)
            return False

        self.logger.info("Using session directory for %s: %s", module_name, self.session_dir)

        # Create and start process
        process = ModuleProcess(
            module_info,
            self.session_dir,
            session_prefix=self.session_prefix,
            status_callback=self.status_callback,
            log_level=self.log_level,
            window_geometry=window_geometry,
        )

        try:
            success = await process.start()
            if success:
                self.module_processes[module_name] = process
                self.logger.info("Module %s started successfully", module_name)
                self.forcefully_stopped_modules.discard(module_name)
            else:
                self.logger.error("Module %s failed to start", module_name)
            return success
        except Exception as e:
            self.logger.error("Exception starting %s: %s", module_name, e, exc_info=True)
            return False

    def set_session_dir(self, session_dir: Path) -> None:
        """Update the base session directory used for new module launches."""
        self.session_dir = Path(session_dir)
        self.logger.info("ModuleManager session directory set to: %s", self.session_dir)

    async def send_command(self, module_name: str, command: str) -> bool:
        """Send a raw command string to a running module process."""
        process = self.module_processes.get(module_name)
        if not process or not process.is_running():
            self.logger.warning("Cannot send command to %s - process not running", module_name)
            return False
        try:
            await process.send_command(command)
            return True
        except Exception as exc:
            self.logger.error("Failed to send command to %s: %s", module_name, exc)
            return False

    async def stop_module(self, module_name: str) -> bool:
        """
        Stop a module (PUBLIC API - delegates to state machine).

        Args:
            module_name: Name of the module to stop

        Returns:
            True if module stopped successfully, False otherwise
        """
        return await self.set_module_enabled(module_name, False)

    async def _stop_module_internal(self, module_name: str) -> bool:
        """
        Internal method to stop a module process.

        Args:
            module_name: Name of the module to stop

        Returns:
            True if module stopped successfully, False otherwise
        """
        process = self.module_processes.get(module_name)
        if not process:
            self.logger.info("Module %s already stopped (no active process)", module_name)
            # Preserve existing force-stop knowledge when no process object is available
            return True

        if not process.is_running():
            self.logger.info("Module %s already stopped", module_name)
            if process.was_forcefully_stopped:
                self.forcefully_stopped_modules.add(module_name)
            else:
                self.forcefully_stopped_modules.discard(module_name)
            self.module_processes.pop(module_name, None)
            return True

        try:
            if process.is_recording():
                await process.pause()

            await process.stop()

            if process.was_forcefully_stopped:
                self.forcefully_stopped_modules.add(module_name)
            else:
                self.forcefully_stopped_modules.discard(module_name)
            self.module_processes.pop(module_name, None)

            self.logger.info("Module %s stopped successfully", module_name)
            return True
        except Exception as e:
            self.logger.error("Error stopping %s: %s", module_name, e, exc_info=True)
            self.forcefully_stopped_modules.add(module_name)
            return False

    async def stop_all(self) -> None:
        """Stop all running module processes."""
        import time
        self.logger.info("Stopping all modules")

        stop_tasks = []
        for module_name, process in self.module_processes.items():
            if process.is_running():
                async def stop_module_task(name: str, proc: ModuleProcess):
                    try:
                        module_start = time.time()
                        await proc.stop()
                        module_duration = time.time() - module_start
                        self.logger.info("⏱️  Module %s stopped in %.3fs", name, module_duration)
                        if proc.was_forcefully_stopped:
                            self.forcefully_stopped_modules.add(name)
                        else:
                            self.forcefully_stopped_modules.discard(name)
                    except Exception as e:
                        self.logger.error("Error stopping %s: %s", name, e)
                        self.forcefully_stopped_modules.add(name)

                stop_tasks.append(stop_module_task(module_name, process))

        if stop_tasks:
            await asyncio.gather(*stop_tasks, return_exceptions=True)

        self.module_processes.clear()
        self.logger.info("All modules stopped")

    def get_running_modules(self) -> List[str]:
        """Get list of currently running module names."""
        return [
            name for name, proc in self.module_processes.items()
            if proc.is_running()
        ]

    def cleanup_stopped_process(self, module_name: str) -> None:
        """
        Remove a stopped process from tracking dict.
        Called by ModuleProcess when it detects process has exited.

        Args:
            module_name: Name of the module to clean up
        """
        if module_name in self.module_processes:
            process = self.module_processes[module_name]
            if not process.is_running():
                self.module_processes.pop(module_name, None)
                if process.was_forcefully_stopped:
                    self.forcefully_stopped_modules.add(module_name)
                else:
                    self.forcefully_stopped_modules.discard(module_name)
                self.logger.info("Cleaned up stopped process: %s", module_name)
