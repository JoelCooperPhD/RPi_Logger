"""
Unified State Facade - Single interface for all state persistence.

This facade consolidates three persistence mechanisms:
1. ModuleStatePersistence - Lifecycle state (enabled, device_connected, crash recovery)
2. InstanceGeometryStore - Window positions per instance
3. ConfigManager - Module-specific settings/preferences

Usage:
    from rpi_logger.core.state_facade import StateFacade

    # In LoggerSystem.__init__
    self._state = StateFacade(module_configs)

    # Lifecycle state (phase-aware)
    await self._state.on_device_connected("EyeTracker")
    await self._state.on_module_crash("Audio")

    # Window geometry
    geometry = self._state.get_geometry("DRT:ACM0")
    self._state.set_geometry("main_window", WindowGeometry(x=100, y=100, width=800, height=600))

    # User preferences
    fps = await self._state.get_preference("EyeTracker", "target_fps", default=30.0)
    await self._state.set_preference("Audio", "volume", 0.8)
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.core.config_manager import get_config_manager, ConfigManager
from rpi_logger.core.instance_geometry_store import get_instance_geometry_store, InstanceGeometryStore
from rpi_logger.core.state_persistence import ModuleStatePersistence, ModuleStateSnapshot, AppPhase
from rpi_logger.core.window_manager import WindowGeometry


class StateFacade:
    """
    Unified interface for all state persistence in TheLogger.

    This facade provides a single API for:
    - Module lifecycle state (enabled, device_connected, crash recovery)
    - Window geometry persistence per instance
    - Module-specific user preferences

    Each category delegates to specialized managers internally, maintaining
    separation of concerns while providing a unified interface.
    """

    def __init__(self, module_configs: Dict[str, Optional[Path]]):
        """
        Initialize the state facade.

        Args:
            module_configs: Map of module_name -> config.txt path
        """
        self.logger = get_module_logger("StateFacade")
        self._module_configs = module_configs

        # Initialize internal managers
        self._lifecycle = ModuleStatePersistence(module_configs)
        self._geometry: InstanceGeometryStore = get_instance_geometry_store()
        self._config: ConfigManager = get_config_manager()

        self.logger.info("StateFacade initialized with %d modules", len(module_configs))

    # =========================================================================
    # Lifecycle State (phase-aware, async)
    # Delegates to ModuleStatePersistence
    # =========================================================================

    async def on_device_connected(self, module_name: str) -> None:
        """
        Called when a device successfully connects.

        Saves device_connected=True so module auto-connects on restart.
        Skipped during shutdown phase.
        """
        await self._lifecycle.on_device_connected(module_name)

    async def on_user_disconnect(self, module_name: str) -> None:
        """
        Called when user disconnects a hardware device.

        Saves device_connected=False and enabled=False.
        For internal modules, use on_internal_module_closed instead.
        """
        await self._lifecycle.on_user_disconnect(module_name)

    async def on_internal_module_closed(self, module_name: str) -> None:
        """
        Called when user closes an internal module window (Notes, etc.).

        Only saves device_connected=False. Module remains visible in Devices list.
        """
        await self._lifecycle.on_internal_module_closed(module_name)

    async def on_module_crash(self, module_name: str) -> None:
        """
        Called when a module crashes unexpectedly.

        Saves enabled=False to prevent broken module from auto-starting.
        """
        await self._lifecycle.on_module_crash(module_name)

    async def on_user_toggle_enabled(self, module_name: str, enabled: bool) -> None:
        """
        Called when user toggles the module checkbox in UI.

        Always saves regardless of phase (explicit user action).
        """
        await self._lifecycle.on_user_toggle_enabled(module_name, enabled)

    # Phase management

    def enter_running_phase(self) -> None:
        """Transition to running phase after startup complete."""
        self._lifecycle.enter_running_phase()

    def enter_shutdown_phase(self) -> None:
        """Transition to shutdown phase - lifecycle state writes will be skipped."""
        self._lifecycle.enter_shutdown_phase()

    def is_shutting_down(self) -> bool:
        """Check if app is in shutdown phase."""
        return self._lifecycle.is_shutting_down()

    @property
    def phase(self) -> AppPhase:
        """Current application phase."""
        return self._lifecycle.phase

    # Session recovery

    async def load_recovery_state(self) -> Optional[Set[str]]:
        """
        Load running modules from crash recovery file.

        Returns:
            Set of module names that were running, or None if no recovery needed
        """
        return await self._lifecycle.load_recovery_state()

    async def save_startup_snapshot(self, running_modules: Set[str]) -> bool:
        """Save snapshot after successful startup."""
        return await self._lifecycle.save_startup_snapshot(running_modules)

    async def save_shutdown_snapshot(self, running_modules: Set[str]) -> bool:
        """Save snapshot at shutdown initiation."""
        return await self._lifecycle.save_shutdown_snapshot(running_modules)

    async def delete_recovery_file(self) -> bool:
        """Delete recovery file after successful startup or clean shutdown."""
        return await self._lifecycle.delete_recovery_file()

    def mark_forcefully_stopped(self, module_name: str) -> None:
        """Mark a module as forcefully stopped (exclude from recovery)."""
        self._lifecycle.mark_forcefully_stopped(module_name)

    async def load_module_state(self, module_name: str) -> ModuleStateSnapshot:
        """
        Load persisted lifecycle state for a module.

        Returns:
            ModuleStateSnapshot with enabled and device_connected values
        """
        return await self._lifecycle.load_module_state(module_name)

    def update_module_config(self, module_name: str, config_path: Optional[Path]) -> None:
        """Update the config path for a module (e.g., when module is discovered late)."""
        self._lifecycle.update_module_config(module_name, config_path)
        self._module_configs[module_name] = config_path

    # =========================================================================
    # Window Geometry (synchronous)
    # Delegates to InstanceGeometryStore
    # =========================================================================

    def get_geometry(self, instance_id: str) -> Optional[WindowGeometry]:
        """
        Get saved window geometry for an instance.

        Args:
            instance_id: Instance ID like "DRT:ACM0" or "main_window"

        Returns:
            WindowGeometry if found, None otherwise
        """
        return self._geometry.get(instance_id)

    def set_geometry(self, instance_id: str, geometry: WindowGeometry) -> None:
        """
        Save window geometry for an instance.

        Args:
            instance_id: Instance ID like "DRT:ACM0" or "main_window"
            geometry: Window geometry to save
        """
        self._geometry.set(instance_id, geometry)

    def remove_geometry(self, instance_id: str) -> bool:
        """
        Remove saved geometry for an instance.

        Args:
            instance_id: Instance ID to remove

        Returns:
            True if removed, False if not found
        """
        return self._geometry.remove(instance_id)

    def get_all_geometries(self) -> Dict[str, WindowGeometry]:
        """Get all stored window geometries."""
        return self._geometry.get_all()

    def clear_all_geometries(self) -> None:
        """Clear all stored window geometries."""
        self._geometry.clear()

    # =========================================================================
    # User Preferences (async)
    # Delegates to ConfigManager
    # =========================================================================

    async def get_preference(
        self,
        module_name: str,
        key: str,
        default: Any = None,
    ) -> Any:
        """
        Get a single preference value for a module.

        Args:
            module_name: Module name (e.g., "EyeTracker")
            key: Config key (e.g., "target_fps")
            default: Default value if key not found

        Returns:
            The preference value, or default if not found
        """
        config_path = self._module_configs.get(module_name)
        if not config_path:
            return default

        config = await self._config.read_config_async(config_path)
        return config.get(key, default)

    async def get_preference_bool(
        self,
        module_name: str,
        key: str,
        default: bool = False,
    ) -> bool:
        """Get a boolean preference value."""
        config_path = self._module_configs.get(module_name)
        if not config_path:
            return default

        config = await self._config.read_config_async(config_path)
        return self._config.get_bool(config, key, default)

    async def get_preference_int(
        self,
        module_name: str,
        key: str,
        default: int = 0,
    ) -> int:
        """Get an integer preference value."""
        config_path = self._module_configs.get(module_name)
        if not config_path:
            return default

        config = await self._config.read_config_async(config_path)
        return self._config.get_int(config, key, default)

    async def get_preference_float(
        self,
        module_name: str,
        key: str,
        default: float = 0.0,
    ) -> float:
        """Get a float preference value."""
        config_path = self._module_configs.get(module_name)
        if not config_path:
            return default

        config = await self._config.read_config_async(config_path)
        return self._config.get_float(config, key, default)

    async def get_preferences(
        self,
        module_name: str,
        keys: List[str],
    ) -> Dict[str, Any]:
        """
        Get multiple preference values for a module.

        Args:
            module_name: Module name
            keys: List of config keys to retrieve

        Returns:
            Dict mapping keys to values (missing keys omitted)
        """
        config_path = self._module_configs.get(module_name)
        if not config_path:
            return {}

        config = await self._config.read_config_async(config_path)
        return {key: config[key] for key in keys if key in config}

    async def set_preference(
        self,
        module_name: str,
        key: str,
        value: Any,
    ) -> bool:
        """
        Set a single preference value for a module.

        Args:
            module_name: Module name
            key: Config key
            value: Value to set

        Returns:
            True if successful, False otherwise
        """
        config_path = self._module_configs.get(module_name)
        if not config_path:
            self.logger.warning("No config path for module %s", module_name)
            return False

        return await self._config.write_config_async(config_path, {key: value})

    async def set_preferences(
        self,
        module_name: str,
        updates: Dict[str, Any],
    ) -> bool:
        """
        Set multiple preference values for a module.

        Args:
            module_name: Module name
            updates: Dict of key-value pairs to set

        Returns:
            True if successful, False otherwise
        """
        config_path = self._module_configs.get(module_name)
        if not config_path:
            self.logger.warning("No config path for module %s", module_name)
            return False

        return await self._config.write_config_async(config_path, updates)

    async def load_all_preferences(self, module_name: str) -> Dict[str, str]:
        """
        Load all preferences for a module.

        Args:
            module_name: Module name

        Returns:
            Dict of all config key-value pairs
        """
        config_path = self._module_configs.get(module_name)
        if not config_path:
            return {}

        return await self._config.read_config_async(config_path)
