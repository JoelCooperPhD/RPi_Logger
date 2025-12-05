"""
Config Persistence Observer - Persists module enabled state to config files.

This observer listens for DESIRED_STATE_CHANGED events and updates the
corresponding module's config.txt file with the new enabled state.
"""

import asyncio
from pathlib import Path
from typing import Dict, Optional, TYPE_CHECKING

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.core.module_state_manager import (
    StateChange,
    StateEvent,
    DesiredState,
)
from rpi_logger.core.config_manager import get_config_manager

if TYPE_CHECKING:
    from rpi_logger.core.module_discovery import ModuleInfo


class ConfigPersistenceObserver:
    """
    Persists module enabled state to config files.

    When the user changes a module's desired state (enable/disable),
    this observer writes that preference to the module's config.txt file.
    This ensures the preference persists across sessions.
    """

    def __init__(self, module_configs: Dict[str, Optional[Path]]):
        """
        Initialize the observer.

        Args:
            module_configs: Dict mapping module names to their config file paths.
                           Value is None if module has no config file.
        """
        self.logger = get_module_logger("ConfigPersistenceObserver")
        self._module_configs = module_configs
        self._config_manager = get_config_manager()
        self._write_lock = asyncio.Lock()

    @classmethod
    def from_module_infos(cls, modules: list) -> 'ConfigPersistenceObserver':
        """Create observer from list of ModuleInfo objects."""
        configs = {
            m.name: m.config_path if m.config_path else None
            for m in modules
        }
        return cls(configs)

    async def __call__(self, change: StateChange) -> None:
        """Handle state change events."""
        if change.event != StateEvent.DESIRED_STATE_CHANGED:
            return

        await self._persist_enabled_state(
            change.module_name,
            change.new_value == DesiredState.ENABLED
        )

    async def _persist_enabled_state(self, module_name: str, enabled: bool) -> bool:
        """
        Write the enabled state to the module's config file.

        Args:
            module_name: Name of the module
            enabled: Whether the module should be enabled

        Returns:
            True if write succeeded, False otherwise
        """
        config_path = self._module_configs.get(module_name)
        if not config_path:
            self.logger.debug(
                "No config path for module %s, skipping persistence",
                module_name
            )
            return False

        async with self._write_lock:
            try:
                success = await self._config_manager.write_config_async(
                    config_path,
                    {'enabled': enabled}
                )

                if success:
                    self.logger.info(
                        "Persisted enabled=%s for module %s to %s",
                        enabled, module_name, config_path
                    )
                else:
                    self.logger.error(
                        "Failed to persist enabled state for module %s",
                        module_name
                    )

                return success

            except Exception as e:
                self.logger.error(
                    "Error persisting enabled state for %s: %s",
                    module_name, e, exc_info=True
                )
                return False

    def update_module_config(self, module_name: str, config_path: Optional[Path]) -> None:
        """Update the config path for a module."""
        self._module_configs[module_name] = config_path
