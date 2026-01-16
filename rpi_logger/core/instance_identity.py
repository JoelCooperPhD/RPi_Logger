"""
Instance Identity - ID generation, parsing, and tracking for module instances.

This module handles the mapping between devices and module instances,
particularly for multi-instance modules (DRT, VOG, Cameras, Audio) that
can run multiple simultaneous instances for different hardware devices.
"""

from typing import Dict, Optional, Set, Tuple


# Cached multi-instance modules (lazy-loaded from discovery registry)
_multi_instance_modules: Optional[Set[str]] = None


def get_multi_instance_modules() -> Set[str]:
    """Get the set of modules that support multiple simultaneous instances.

    Lazily loads from the discovery registry on first call. The registry
    provides module specs with multi_instance=True, which are then normalized
    to match the format expected by is_multi_instance_module().

    Returns:
        Set of normalized module IDs (uppercase, no underscores).
    """
    global _multi_instance_modules
    if _multi_instance_modules is None:
        from rpi_logger.core.devices.discovery_loader import get_discovery_registry
        registry = get_discovery_registry()
        _multi_instance_modules = registry.get_multi_instance_modules()
    return _multi_instance_modules


# Backwards compatibility: MULTI_INSTANCE_MODULES is now a property-like
# that calls get_multi_instance_modules() at import time
# NOTE: This is evaluated at import time, so the registry must be ready
# For deferred evaluation, use get_multi_instance_modules() directly
MULTI_INSTANCE_MODULES: Set[str] = get_multi_instance_modules()


class InstanceIdentity:
    """
    Manages instance ID generation, parsing, and device-to-instance mapping.

    Instance IDs follow the format:
    - Multi-instance modules: "MODULE:ShortDeviceId" (e.g., "DRT:ACM0")
    - Single-instance modules: Just the module name (e.g., "Notes")
    """

    def __init__(self, multi_instance_modules: Optional[Set[str]] = None):
        """
        Initialize the instance identity manager.

        Args:
            multi_instance_modules: Set of module names that support multiple instances.
                                   If None, loads from the discovery registry.
        """
        self._multi_instance_modules = (
            multi_instance_modules if multi_instance_modules is not None
            else get_multi_instance_modules()
        )
        # Device-to-instance mapping: device_id -> instance_id
        self._device_instance_map: Dict[str, str] = {}

    @property
    def multi_instance_modules(self) -> Set[str]:
        """Get the set of multi-instance module names."""
        return self._multi_instance_modules

    def is_multi_instance_module(self, module_id: str) -> bool:
        """Check if a module supports multiple simultaneous instances.

        Args:
            module_id: The module identifier to check

        Returns:
            True if the module supports multiple instances
        """
        # Normalize: uppercase and remove underscores for consistent matching
        normalized = module_id.upper().replace("_", "")
        return normalized in self._multi_instance_modules

    def make_instance_id(self, module_id: str, device_id: str) -> str:
        """Generate an instance ID for a device-specific module instance.

        For multi-instance modules, returns "MODULE:ShortDeviceId" (e.g., "DRT:ACM0").
        For single-instance modules, returns just the module_id.

        Args:
            module_id: The module name (e.g., "DRT", "Notes")
            device_id: The device identifier (e.g., "/dev/ttyACM0")

        Returns:
            The generated instance ID
        """
        if self.is_multi_instance_module(module_id):
            short_id = self.extract_short_device_id(device_id)
            return f"{module_id.upper()}:{short_id}"
        return module_id

    @staticmethod
    def extract_short_device_id(device_id: str) -> str:
        """Extract short device ID from full path.

        Examples:
            /dev/ttyACM0 -> ACM0
            /dev/ttyUSB0 -> USB0
            ACM0 -> ACM0 (already short)

        Args:
            device_id: The full device path or ID

        Returns:
            The shortened device ID
        """
        if not device_id:
            return ""
        # Handle full paths like /dev/ttyACM0
        if "/" in device_id:
            short = device_id.split("/")[-1]
            if short.startswith("tty"):
                return short[3:]  # Remove "tty" prefix
            return short
        return device_id

    @staticmethod
    def parse_instance_id(instance_id: str) -> Tuple[str, Optional[str]]:
        """Parse an instance ID into (module_id, device_id).

        Args:
            instance_id: The instance ID to parse (e.g., "DRT:ACM0" or "Notes")

        Returns:
            Tuple of (module_id, device_id) where device_id is None for
            single-instance modules
        """
        if ":" in instance_id:
            parts = instance_id.split(":", 1)
            return parts[0], parts[1]
        return instance_id, None

    def get_instance_for_device(self, device_id: str) -> Optional[str]:
        """Get the instance ID for a device, if one is running.

        Args:
            device_id: The device identifier

        Returns:
            The instance ID if found, None otherwise
        """
        return self._device_instance_map.get(device_id)

    def register_device_instance(self, device_id: str, instance_id: str) -> None:
        """Register a device-to-instance mapping.

        Args:
            device_id: The device identifier
            instance_id: The instance ID to associate with this device
        """
        self._device_instance_map[device_id] = instance_id

    def unregister_device_instance(self, device_id: str) -> Optional[str]:
        """Unregister a device-to-instance mapping.

        Args:
            device_id: The device identifier to unregister

        Returns:
            The instance_id that was unregistered, if found
        """
        return self._device_instance_map.pop(device_id, None)

    def find_device_for_instance(self, instance_id: str) -> Optional[str]:
        """Find the device_id associated with an instance_id.

        Args:
            instance_id: The instance ID to look up

        Returns:
            The device_id if found, or extracted from instance_id format
        """
        for dev_id, inst_id in self._device_instance_map.items():
            if inst_id == instance_id:
                return dev_id
        # Fallback: extract from instance_id format "MODULE:device"
        _, extracted = self.parse_instance_id(instance_id)
        return extracted

    def has_other_instances(self, module_name: str) -> bool:
        """Check if other instances of this module are still running.

        Args:
            module_name: The module name to check

        Returns:
            True if at least one instance of this module is registered
        """
        # Normalize: uppercase and remove underscores for consistent matching
        normalized = module_name.upper().replace("_", "")
        return any(
            inst_id.upper().replace("_", "").startswith(f"{normalized}:")
            for inst_id in self._device_instance_map.values()
        )

    def get_all_instances_for_module(self, module_name: str) -> Dict[str, str]:
        """Get all device-to-instance mappings for a module.

        Args:
            module_name: The module name to filter by

        Returns:
            Dict of device_id -> instance_id for matching instances
        """
        normalized = module_name.upper().replace("_", "")
        return {
            dev_id: inst_id
            for dev_id, inst_id in self._device_instance_map.items()
            if inst_id.upper().replace("_", "").startswith(f"{normalized}:")
        }

    def clear(self) -> None:
        """Clear all device-to-instance mappings."""
        self._device_instance_map.clear()
