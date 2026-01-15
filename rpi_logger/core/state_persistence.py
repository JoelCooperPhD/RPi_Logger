"""
Centralized State Persistence Manager

This module consolidates all module state persistence logic into a single,
well-defined interface. It eliminates:
- Scattered state writes across multiple files
- Race conditions from boolean shutdown flags
- Duplicated multi-instance device tracking logic
- Complex session recovery lifecycle

State Persistence Rules:
1. `enabled` - User's intent to use this module type (checkbox in Modules menu)
   - Written when: User toggles checkbox
   - NOT written during: App shutdown (preserved for restart)

2. `device_connected` - Whether to auto-connect on startup
   - Written when: Device connects successfully OR user disconnects
   - NOT written during: App shutdown, module crash (only affects enabled)

3. `running_modules.json` - Crash recovery snapshot
   - Written when: Startup complete, Shutdown initiated
   - Loaded when: App starts (takes priority over config files)
"""

import asyncio
import json
import os
import tempfile
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Optional, Set, Dict, Callable, Awaitable
from dataclasses import dataclass

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.core.config_manager import get_config_manager
from rpi_logger.core.paths import STATE_FILE


class AppPhase(Enum):
    """Application lifecycle phases for state persistence decisions."""
    INITIALIZING = auto()      # Loading state, starting up
    RUNNING = auto()           # Normal operation
    SHUTTING_DOWN = auto()     # Shutdown initiated, preserving state
    STOPPED = auto()           # Cleanup complete


@dataclass
class ModuleStateSnapshot:
    """Snapshot of a module's persisted state."""
    enabled: bool
    device_connected: bool

    def __repr__(self) -> str:
        return f"ModuleState(enabled={self.enabled}, device_connected={self.device_connected})"


class ModuleStatePersistence:
    """
    Centralized manager for all module state persistence.

    This class is the SINGLE source of truth for:
    - When to save state (based on app phase and event type)
    - How to save state (atomic writes, proper locking)
    - What state to save (enabled, device_connected, running_modules)

    Usage:
        persistence = ModuleStatePersistence(module_configs)

        # On device connect
        await persistence.on_device_connected("EyeTracker")

        # On user disconnect
        await persistence.on_user_disconnect("EyeTracker")

        # On shutdown
        persistence.enter_shutdown_phase()
        await persistence.save_shutdown_snapshot(running_modules)
    """

    def __init__(self, module_configs: Dict[str, Optional[Path]]):
        """
        Initialize the persistence manager.

        Args:
            module_configs: Map of module_name -> config.txt path
        """
        self.logger = get_module_logger("StatePersistence")
        self._module_configs = module_configs
        self._config_manager = get_config_manager()

        self._phase = AppPhase.INITIALIZING
        self._write_lock = asyncio.Lock()

        # Track modules that crashed (don't auto-connect on restart)
        self._crashed_modules: Set[str] = set()

        # Track forcefully stopped modules (exclude from recovery)
        self._forcefully_stopped: Set[str] = set()

        self.logger.info("StatePersistence initialized with %d modules", len(module_configs))

    # =========================================================================
    # Phase Management
    # =========================================================================

    def enter_running_phase(self) -> None:
        """Transition to running phase after startup complete."""
        self._phase = AppPhase.RUNNING
        self.logger.info("STATE PHASE: RUNNING")

    def enter_shutdown_phase(self) -> None:
        """Transition to shutdown phase - state writes will be skipped."""
        self._phase = AppPhase.SHUTTING_DOWN
        self.logger.info("STATE PHASE: SHUTTING_DOWN - device state will be preserved")

    def is_shutting_down(self) -> bool:
        """Check if app is in shutdown phase."""
        return self._phase == AppPhase.SHUTTING_DOWN

    @property
    def phase(self) -> AppPhase:
        """Current application phase."""
        return self._phase

    # =========================================================================
    # Event Handlers - These are the ONLY entry points for state changes
    # =========================================================================

    async def on_device_connected(self, module_name: str) -> None:
        """
        Called when a device successfully connects.

        Saves device_connected=True so module auto-connects on restart.
        """
        if self._phase == AppPhase.SHUTTING_DOWN:
            self.logger.info(
                "PERSIST SKIP: %s device_connected=True (shutting down)",
                module_name
            )
            return

        self._crashed_modules.discard(module_name)
        await self._write_device_connected(module_name, True)

    async def on_user_disconnect(self, module_name: str) -> None:
        """
        Called when user disconnects a hardware device (via label click or window close).

        Saves device_connected=False so module doesn't auto-connect on restart.
        Also saves enabled=False since user doesn't want this device type.

        For internal modules (Notes, etc.), use on_internal_module_closed instead.
        """
        if self._phase == AppPhase.SHUTTING_DOWN:
            self.logger.info(
                "PERSIST SKIP: %s disconnect (shutting down)",
                module_name
            )
            return

        await self._write_device_connected(module_name, False)
        await self._write_enabled(module_name, False)

    async def on_internal_module_closed(self, module_name: str) -> None:
        """
        Called when user closes an internal module window (Notes, etc.).

        Only saves device_connected=False. Does NOT change enabled state,
        so the module remains visible in the Devices list on restart.
        """
        if self._phase == AppPhase.SHUTTING_DOWN:
            self.logger.info(
                "PERSIST SKIP: %s internal close (shutting down)",
                module_name
            )
            return

        await self._write_device_connected(module_name, False)

    async def on_module_crash(self, module_name: str) -> None:
        """
        Called when a module crashes unexpectedly.

        Saves enabled=False to prevent broken module from auto-starting.
        Does NOT save device_connected (crash doesn't mean device is gone).
        """
        if self._phase == AppPhase.SHUTTING_DOWN:
            self.logger.info(
                "PERSIST SKIP: %s crash (shutting down)",
                module_name
            )
            return

        self._crashed_modules.add(module_name)
        await self._write_enabled(module_name, False)
        self.logger.warning("Module %s crashed - disabled for next startup", module_name)

    async def on_user_toggle_enabled(self, module_name: str, enabled: bool) -> None:
        """
        Called when user toggles the module checkbox in UI.

        Always saves (this is explicit user action).
        """
        await self._write_enabled(module_name, enabled)

    # =========================================================================
    # Session Recovery (running_modules.json)
    # =========================================================================

    async def load_recovery_state(self) -> Optional[Set[str]]:
        """
        Load running modules from crash recovery file.

        Returns:
            Set of module names that were running, or None if no recovery needed
        """
        if not STATE_FILE.exists():
            self.logger.info("RECOVERY: No recovery file found - fresh start")
            return None

        try:
            def read_file():
                with open(STATE_FILE, 'r') as f:
                    return json.load(f)

            state = await asyncio.to_thread(read_file)
            modules = set(state.get('running_modules', []))
            timestamp = state.get('timestamp', 'unknown')

            self.logger.info(
                "RECOVERY: Found %d modules from %s: %s",
                len(modules), timestamp, sorted(modules)
            )
            return modules

        except Exception as e:
            self.logger.error("RECOVERY: Failed to load: %s", e)
            return None

    async def save_startup_snapshot(self, running_modules: Set[str]) -> bool:
        """
        Save snapshot after successful startup.

        Called from on_startup_complete() to record which modules are actually running.
        """
        return await self._write_recovery_file(running_modules)

    async def save_shutdown_snapshot(self, running_modules: Set[str]) -> bool:
        """
        Save snapshot at shutdown initiation.

        This captures modules running BEFORE cleanup starts.
        """
        # Filter out crashed modules
        filtered = running_modules - self._crashed_modules - self._forcefully_stopped

        if filtered != running_modules:
            self.logger.info(
                "RECOVERY: Filtered %d crashed/forced modules from snapshot",
                len(running_modules - filtered)
            )

        return await self._write_recovery_file(filtered)

    async def delete_recovery_file(self) -> bool:
        """Delete recovery file after successful startup or clean shutdown."""
        if not STATE_FILE.exists():
            return True

        try:
            await asyncio.to_thread(STATE_FILE.unlink)
            self.logger.info("RECOVERY: Deleted recovery file")
            return True
        except Exception as e:
            self.logger.error("RECOVERY: Failed to delete: %s", e)
            return False

    def mark_forcefully_stopped(self, module_name: str) -> None:
        """Mark a module as forcefully stopped (don't include in recovery)."""
        self._forcefully_stopped.add(module_name)
        self.logger.info("RECOVERY: Marked %s as forcefully stopped", module_name)

    # =========================================================================
    # Config Loading
    # =========================================================================

    async def load_module_state(self, module_name: str) -> ModuleStateSnapshot:
        """
        Load persisted state for a module.

        Returns:
            ModuleStateSnapshot with enabled and device_connected values
        """
        config_path = self._module_configs.get(module_name)
        if not config_path:
            return ModuleStateSnapshot(enabled=False, device_connected=False)

        config = await self._config_manager.read_config_async(config_path)

        enabled = self._config_manager.get_bool(config, 'enabled', default=False)
        device_connected = self._config_manager.get_bool(
            config, 'device_connected', default=False
        )

        return ModuleStateSnapshot(enabled=enabled, device_connected=device_connected)

    # =========================================================================
    # Internal Write Methods
    # =========================================================================

    async def _write_enabled(self, module_name: str, enabled: bool) -> bool:
        """Write enabled state to module config."""
        config_path = self._module_configs.get(module_name)
        if not config_path:
            self.logger.debug("PERSIST: No config path for %s", module_name)
            return False

        async with self._write_lock:
            success = await self._config_manager.write_config_async(
                config_path,
                {'enabled': enabled}
            )

        if success:
            self.logger.info("PERSIST: %s enabled=%s", module_name, enabled)
        else:
            self.logger.error("PERSIST FAILED: %s enabled=%s", module_name, enabled)

        return success

    async def _write_device_connected(self, module_name: str, connected: bool) -> bool:
        """Write device_connected state to module config."""
        config_path = self._module_configs.get(module_name)
        if not config_path:
            self.logger.debug("PERSIST: No config path for %s", module_name)
            return False

        async with self._write_lock:
            success = await self._config_manager.write_config_async(
                config_path,
                {'device_connected': connected}
            )

        if success:
            self.logger.info("PERSIST: %s device_connected=%s", module_name, connected)
        else:
            self.logger.error("PERSIST FAILED: %s device_connected=%s", module_name, connected)

        return success

    async def _write_recovery_file(self, running_modules: Set[str]) -> bool:
        """Write running modules to recovery file."""
        if not running_modules:
            return await self.delete_recovery_file()

        async with self._write_lock:
            try:
                STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

                state = {
                    'timestamp': datetime.now().isoformat(),
                    'running_modules': sorted(running_modules),
                }

                def write_file():
                    tmp_path: Optional[Path] = None
                    try:
                        from rpi_logger.core.file_sync_utils import fsync_file
                        with tempfile.NamedTemporaryFile(
                            "w",
                            dir=str(STATE_FILE.parent),
                            delete=False,
                            encoding="utf-8",
                        ) as tmp:
                            tmp_path = Path(tmp.name)
                            json.dump(state, tmp, indent=2)
                            fsync_file(tmp)

                        os.replace(tmp_path, STATE_FILE)
                    finally:
                        if tmp_path is not None:
                            try:
                                tmp_path.unlink()
                            except FileNotFoundError:
                                pass

                await asyncio.to_thread(write_file)

                self.logger.info(
                    "RECOVERY: Saved %d modules: %s",
                    len(running_modules), sorted(running_modules)
                )
                return True

            except Exception as e:
                self.logger.error("RECOVERY: Failed to write: %s", e)
                return False

    # =========================================================================
    # Config Management
    # =========================================================================

    def update_module_config(self, module_name: str, config_path: Optional[Path]) -> None:
        """Update the config path for a module."""
        self._module_configs[module_name] = config_path
