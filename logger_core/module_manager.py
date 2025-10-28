"""
Module Manager - Handles module discovery, selection, and lifecycle.

This module provides centralized management of logger modules including
discovery, selection state, and process lifecycle management.
"""

import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set, Callable

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
        self.selected_modules: Set[str] = set()
        self.module_processes: Dict[str, ModuleProcess] = {}

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
        """Load module selection state from configs."""
        self.selected_modules.clear()

        for module_info in self.available_modules:
            if not module_info.config_path:
                self.selected_modules.add(module_info.name)
                self.logger.debug("Module %s has no config, defaulting to enabled", module_info.name)
                continue

            # Use async config reading to avoid blocking
            config = await self.config_manager.read_config_async(module_info.config_path)
            enabled = self.config_manager.get_bool(config, 'enabled', default=True)

            if enabled:
                self.selected_modules.add(module_info.name)
                self.logger.info("Module %s enabled in config", module_info.name)
            else:
                self.logger.info("Module %s disabled in config", module_info.name)

    def get_available_modules(self) -> List[ModuleInfo]:
        """Get list of all discovered modules."""
        return self.available_modules

    def select_module(self, module_name: str) -> bool:
        """
        Mark a module as selected.

        Args:
            module_name: Name of the module to select

        Returns:
            True if module exists and was selected, False otherwise
        """
        if not any(m.name == module_name for m in self.available_modules):
            self.logger.warning("Module not found: %s", module_name)
            return False

        self.selected_modules.add(module_name)
        self.logger.info("Selected module: %s", module_name)
        return True

    def deselect_module(self, module_name: str) -> None:
        """Remove a module from selection."""
        self.selected_modules.discard(module_name)
        self.logger.info("Deselected module: %s", module_name)

    def get_selected_modules(self) -> List[str]:
        """Get list of currently selected module names."""
        return list(self.selected_modules)

    def is_module_selected(self, module_name: str) -> bool:
        """Check if a module is currently selected."""
        return module_name in self.selected_modules

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

    async def start_module(
        self,
        module_name: str,
        window_geometry: Optional[WindowGeometry] = None
    ) -> bool:
        """
        Start a module process.

        Args:
            module_name: Name of the module to start
            window_geometry: Optional window positioning

        Returns:
            True if module started successfully, False otherwise
        """
        # Check if module is already running and wait for it to stop
        if module_name in self.module_processes:
            process = self.module_processes[module_name]

            if process.is_running():
                self.logger.info("Module %s still running, stopping...", module_name)
                await process.stop()

            self.module_processes.pop(module_name, None)
            self.selected_modules.discard(module_name)

        # Find module info
        module_info = next(
            (m for m in self.available_modules if m.name == module_name),
            None
        )
        if not module_info:
            self.logger.error("Module info not found: %s", module_name)
            return False

        # Ensure session directory exists
        self.session_dir.mkdir(parents=True, exist_ok=True)
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
                self.selected_modules.add(module_name)
                self.logger.info("Module %s started successfully", module_name)
            else:
                self.logger.error("Module %s failed to start", module_name)
            return success
        except Exception as e:
            self.logger.error("Exception starting %s: %s", module_name, e, exc_info=True)
            return False

    async def stop_module(self, module_name: str) -> bool:
        """
        Stop a module process.

        Args:
            module_name: Name of the module to stop

        Returns:
            True if module stopped successfully, False otherwise
        """
        process = self.module_processes.get(module_name)
        if not process:
            self.logger.warning("Module %s not found in processes", module_name)
            return False

        if not process.is_running():
            self.logger.warning("Module %s not running", module_name)
            self.module_processes.pop(module_name, None)
            self.selected_modules.discard(module_name)
            return True

        try:
            if process.is_recording():
                await process.pause()

            await process.stop()

            self.module_processes.pop(module_name, None)
            self.selected_modules.discard(module_name)

            self.logger.info("Module %s stopped successfully", module_name)
            return True
        except Exception as e:
            self.logger.error("Error stopping %s: %s", module_name, e, exc_info=True)
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
                    except Exception as e:
                        self.logger.error("Error stopping %s: %s", name, e)

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
