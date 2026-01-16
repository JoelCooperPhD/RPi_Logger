"""
Module discovery package loader.

Loads discovery packages from modules and builds runtime registries.
Each module can have a discovery/ package that exports a discovery class
implementing the ModuleDiscoveryProtocol.
"""

import importlib
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.core.paths import MODULES_DIR
from .discovery_protocol import (
    ModuleDiscoverySpec,
    ModuleDiscoveryProtocol,
    BaseModuleDiscovery,
    DeviceMatch,
    USBDeviceSpec,
    XBeePattern,
)
from .types import InterfaceType, DeviceFamily

logger = get_module_logger("DiscoveryLoader")


class DiscoveryRegistry:
    """
    Runtime registry built from loaded module discovery specs.

    Provides lookup methods similar to the old device_registry.py,
    but derived from module-provided discovery packages.
    """

    def __init__(self) -> None:
        self._specs: Dict[str, ModuleDiscoverySpec] = {}
        self._discoveries: Dict[str, BaseModuleDiscovery] = {}
        self._usb_matchers: List[Tuple[str, BaseModuleDiscovery]] = []
        self._xbee_matchers: List[Tuple[str, BaseModuleDiscovery]] = []

    def register(
        self,
        module_id: str,
        spec: ModuleDiscoverySpec,
        discovery: BaseModuleDiscovery,
    ) -> None:
        """Register a module's discovery spec and handler."""
        self._specs[module_id] = spec
        self._discoveries[module_id] = discovery

        # Register for USB matching if module has USB devices
        if spec.usb_devices:
            self._usb_matchers.append((module_id, discovery))

        # Register for XBee matching if module has XBee patterns
        if spec.xbee_patterns:
            self._xbee_matchers.append((module_id, discovery))

    def get_spec(self, module_id: str) -> Optional[ModuleDiscoverySpec]:
        """Get discovery spec for a module."""
        return self._specs.get(module_id)

    def get_discovery(self, module_id: str) -> Optional[BaseModuleDiscovery]:
        """Get discovery handler for a module."""
        return self._discoveries.get(module_id)

    def all_specs(self) -> List[ModuleDiscoverySpec]:
        """Get all registered discovery specs."""
        return list(self._specs.values())

    def identify_usb_device(self, vid: int, pid: int) -> Optional[DeviceMatch]:
        """
        Identify a USB device by VID/PID using registered module matchers.

        Iterates through all module USB matchers until one claims the device.
        """
        for module_id, discovery in self._usb_matchers:
            try:
                match = discovery.identify_usb_device(vid, pid)
                if match is not None:
                    return match
            except Exception as e:
                logger.error(f"Error in USB matcher for {module_id}: {e}")
        return None

    def parse_xbee_node(self, node_id: str) -> Optional[DeviceMatch]:
        """
        Parse XBee node ID using registered module matchers.

        Iterates through all module XBee matchers until one claims the device.
        """
        for module_id, discovery in self._xbee_matchers:
            try:
                match = discovery.parse_xbee_node(node_id)
                if match is not None:
                    return match
            except Exception as e:
                logger.error(f"Error in XBee matcher for {module_id}: {e}")
        return None

    def get_modules_with_custom_scanner(self) -> List[Tuple[str, BaseModuleDiscovery]]:
        """Get modules that provide custom scanners."""
        return [
            (module_id, discovery)
            for module_id, discovery in self._discoveries.items()
            if self._specs[module_id].has_custom_scanner
        ]

    def get_modules_for_interface(
        self,
        interface: InterfaceType,
    ) -> List[ModuleDiscoverySpec]:
        """Get all modules that use a specific interface type."""
        return [
            spec for spec in self._specs.values()
            if interface in spec.interfaces
        ]

    def get_modules_for_family(
        self,
        family: DeviceFamily,
    ) -> List[ModuleDiscoverySpec]:
        """Get all modules for a device family."""
        return [
            spec for spec in self._specs.values()
            if spec.family == family
        ]

    def get_internal_modules(self) -> List[ModuleDiscoverySpec]:
        """Get modules that are internal (no hardware discovery)."""
        return [
            spec for spec in self._specs.values()
            if spec.is_internal
        ]

    def get_uart_modules(self) -> List[ModuleDiscoverySpec]:
        """Get modules that use UART interface."""
        return [
            spec for spec in self._specs.values()
            if spec.uart_path is not None
        ]

    def get_multi_instance_modules(self) -> set[str]:
        """Get normalized set of module IDs that support multiple instances.

        Returns module IDs normalized (uppercase, no underscores) to match
        the format used by InstanceIdentity.is_multi_instance_module().
        """
        return {
            spec.module_id.upper().replace("_", "")
            for spec in self._specs.values()
            if spec.multi_instance
        }

    def get_module_for_device_id(self, device_id: str) -> Optional[ModuleDiscoverySpec]:
        """Get the module spec that handles a device ID based on prefix.

        Looks up modules by their device_id_prefix field if present.

        Args:
            device_id: The device identifier (e.g., "picam:0")

        Returns:
            The ModuleDiscoverySpec for the matching module, or None if no match.
        """
        for spec in self._specs.values():
            if spec.device_id_prefix and device_id.startswith(spec.device_id_prefix):
                return spec
        return None


def load_module_discovery(module_dir: Path) -> Optional[BaseModuleDiscovery]:
    """
    Load discovery package from a module directory.

    Args:
        module_dir: Path to module directory (e.g., modules/DRT/)

    Returns:
        Discovery handler instance if found, None otherwise
    """
    discovery_dir = module_dir / "discovery"
    if not discovery_dir.is_dir():
        logger.debug(f"No discovery/ package in {module_dir.name}")
        return None

    init_file = discovery_dir / "__init__.py"
    if not init_file.exists():
        logger.warning(f"discovery/ in {module_dir.name} missing __init__.py")
        return None

    # Build module import path
    # e.g., rpi_logger.modules.DRT.discovery
    module_name = module_dir.name
    import_path = f"rpi_logger.modules.{module_name}.discovery"

    try:
        # Import the discovery package
        discovery_module = importlib.import_module(import_path)

        # Look for the discovery class (convention: <Module>Discovery or Discovery)
        discovery_class = None

        # Try specific class name first
        class_names = [
            f"{module_name}Discovery",
            f"{module_name.upper()}Discovery",
            "Discovery",
            "ModuleDiscovery",
        ]

        for class_name in class_names:
            if hasattr(discovery_module, class_name):
                discovery_class = getattr(discovery_module, class_name)
                break

        if discovery_class is None:
            # Look for DISCOVERY_SPEC and create a basic handler
            if hasattr(discovery_module, "DISCOVERY_SPEC"):
                spec = discovery_module.DISCOVERY_SPEC
                logger.debug(f"Loaded discovery spec from {module_name}")

                # Create a wrapper discovery instance
                class SpecOnlyDiscovery(BaseModuleDiscovery):
                    pass

                instance = SpecOnlyDiscovery()
                instance.spec = spec
                return instance
            else:
                logger.warning(
                    f"No discovery class or DISCOVERY_SPEC in {import_path}"
                )
                return None

        # Instantiate the discovery class
        instance = discovery_class()

        if not hasattr(instance, "spec"):
            logger.warning(f"Discovery class in {import_path} missing 'spec' attribute")
            return None

        logger.debug(f"Loaded discovery handler from {module_name}")
        return instance

    except ImportError as e:
        logger.error(f"Failed to import {import_path}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error loading discovery from {module_name}: {e}")
        return None


def load_all_module_discoveries(
    modules_dir: Path = None,
) -> DiscoveryRegistry:
    """
    Load discovery packages from all modules.

    Args:
        modules_dir: Path to modules directory (defaults to MODULES_DIR)

    Returns:
        DiscoveryRegistry populated with all module discoveries
    """
    if modules_dir is None:
        modules_dir = MODULES_DIR

    registry = DiscoveryRegistry()

    if not modules_dir.exists():
        logger.error(f"Modules directory not found: {modules_dir}")
        return registry

    logger.debug(f"Loading module discoveries from: {modules_dir}")

    for module_dir in sorted(modules_dir.iterdir()):
        if not module_dir.is_dir():
            continue

        if module_dir.name.startswith(".") or module_dir.name in (
            "__pycache__",
            "base",
        ):
            continue

        discovery = load_module_discovery(module_dir)
        if discovery is not None:
            registry.register(
                module_id=discovery.spec.module_id,
                spec=discovery.spec,
                discovery=discovery,
            )

    logger.debug(f"Loaded {len(registry._specs)} module discovery packages")
    return registry


# Global registry instance (lazy-loaded)
_global_registry: Optional[DiscoveryRegistry] = None


def get_discovery_registry() -> DiscoveryRegistry:
    """Get the global discovery registry, loading if needed."""
    global _global_registry
    if _global_registry is None:
        _global_registry = load_all_module_discoveries()
    return _global_registry


def reload_discovery_registry() -> DiscoveryRegistry:
    """Reload the global discovery registry."""
    global _global_registry
    _global_registry = load_all_module_discoveries()
    return _global_registry
