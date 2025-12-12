"""
Device Selection Model - Observable state management for device selection.

This module provides a clean, observable state model for tracking:
- Which connection types (interface+family) are enabled
- Which devices are currently connected
- Auto-connect preferences

The model uses the observer pattern to notify interested parties
(UI, persistence, etc.) when state changes.
"""

from dataclasses import dataclass
from typing import Callable, Set
from enum import Enum

from rpi_logger.core.logging_utils import get_module_logger
from .device_registry import DeviceFamily, InterfaceType

logger = get_module_logger("DeviceSelectionModel")


class ConnectionState(Enum):
    """Device connection state."""
    DISCOVERED = "discovered"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


# Type alias for connection key
ConnectionKey = tuple[InterfaceType, DeviceFamily]

# Observer callback type
StateObserver = Callable[[], None]


@dataclass
class DeviceState:
    """State for a single device."""
    device_id: str
    connection_state: ConnectionState = ConnectionState.DISCOVERED


class DeviceSelectionModel:
    """
    Observable state model for device selection.

    This class manages:
    - Enabled connections (which interface+family combinations are active)
    - Device connection states
    - Auto-connect module preferences

    All state mutations automatically notify registered observers.
    """

    def __init__(self):
        # Enabled connection types
        self._enabled_connections: Set[ConnectionKey] = set()

        # Device connection states (device_id -> state)
        self._device_states: dict[str, ConnectionState] = {}

        # Auto-connect module preferences
        self._auto_connect_modules: Set[str] = set()

        # Multi-instance module IDs (e.g., {"DRT", "VOG", "CAMERAS"})
        # For these modules, auto-connect applies to ALL devices, not just first
        self._multi_instance_modules: Set[str] = set()

        # Track which devices have already been auto-connected during this session
        # Prevents double auto-connect for multi-instance modules
        self._auto_connected_devices: Set[str] = set()

        # Observers
        self._connection_observers: list[StateObserver] = []
        self._device_state_observers: list[StateObserver] = []

    # =========================================================================
    # Connection Enable/Disable State
    # =========================================================================

    def is_connection_enabled(self, interface: InterfaceType, family: DeviceFamily) -> bool:
        """Check if a specific interface+family connection is enabled."""
        return (interface, family) in self._enabled_connections

    def is_family_enabled(self, family: DeviceFamily) -> bool:
        """Check if ANY interface for this family is enabled."""
        return any(f == family for _, f in self._enabled_connections)

    def is_interface_enabled(self, interface: InterfaceType) -> bool:
        """Check if ANY family for this interface is enabled."""
        return any(i == interface for i, _ in self._enabled_connections)

    def get_enabled_connections(self) -> Set[ConnectionKey]:
        """Get all enabled connections as a set."""
        return self._enabled_connections.copy()

    def get_enabled_families(self) -> Set[DeviceFamily]:
        """Get all families that have at least one enabled interface."""
        return {family for _, family in self._enabled_connections}

    def get_enabled_interfaces_for_family(self, family: DeviceFamily) -> Set[InterfaceType]:
        """Get all enabled interfaces for a specific family."""
        return {
            interface
            for interface, f in self._enabled_connections
            if f == family
        }

    def set_connection_enabled(
        self,
        interface: InterfaceType,
        family: DeviceFamily,
        enabled: bool
    ) -> bool:
        """
        Enable or disable a specific interface+family connection.

        Returns:
            True if the state actually changed, False otherwise.
        """
        key: ConnectionKey = (interface, family)
        changed = False

        if enabled and key not in self._enabled_connections:
            self._enabled_connections.add(key)
            changed = True
            logger.info(f"Connection enabled: {interface.value}:{family.value}")
        elif not enabled and key in self._enabled_connections:
            self._enabled_connections.discard(key)
            changed = True
            logger.info(f"Connection disabled: {interface.value}:{family.value}")

        if changed:
            self._notify_connection_observers()

        return changed

    def set_enabled_connections(self, connections: Set[ConnectionKey]) -> None:
        """
        Set all enabled connections at once (used for loading from config).
        """
        if connections != self._enabled_connections:
            self._enabled_connections = connections.copy()
            logger.info(f"Enabled connections set: {len(connections)} connections")
            self._notify_connection_observers()

    def toggle_connection(self, interface: InterfaceType, family: DeviceFamily) -> bool:
        """Toggle a connection's enabled state. Returns the new state."""
        key: ConnectionKey = (interface, family)
        is_enabled = key in self._enabled_connections
        self.set_connection_enabled(interface, family, not is_enabled)
        return not is_enabled

    # =========================================================================
    # Device Connection State
    # =========================================================================

    def get_device_state(self, device_id: str) -> ConnectionState:
        """Get connection state for a device."""
        return self._device_states.get(device_id, ConnectionState.DISCOVERED)

    def is_device_connected(self, device_id: str) -> bool:
        """Check if a device is connected."""
        return self._device_states.get(device_id) == ConnectionState.CONNECTED

    def is_device_connecting(self, device_id: str) -> bool:
        """Check if a device is in the process of connecting."""
        return self._device_states.get(device_id) == ConnectionState.CONNECTING

    def get_connected_device_ids(self) -> Set[str]:
        """Get all connected device IDs."""
        return {
            device_id
            for device_id, state in self._device_states.items()
            if state == ConnectionState.CONNECTED
        }

    def set_device_state(self, device_id: str, state: ConnectionState) -> bool:
        """
        Set the connection state for a device.

        Returns:
            True if the state actually changed, False otherwise.
        """
        current = self._device_states.get(device_id)
        if current != state:
            self._device_states[device_id] = state
            logger.debug(f"Device {device_id} state: {state.value}")
            self._notify_device_state_observers()
            return True
        return False

    def set_device_connected(self, device_id: str, connected: bool) -> bool:
        """
        Set whether a device is connected.

        Returns:
            True if the state actually changed, False otherwise.
        """
        new_state = ConnectionState.CONNECTED if connected else ConnectionState.DISCOVERED
        return self.set_device_state(device_id, new_state)

    def remove_device_state(self, device_id: str) -> None:
        """Remove state tracking for a device (when device is lost)."""
        if device_id in self._device_states:
            del self._device_states[device_id]
            self._notify_device_state_observers()

    # =========================================================================
    # Auto-Connect Preferences
    # =========================================================================

    def should_auto_connect(self, module_id: str) -> bool:
        """Check if a module should auto-connect when its device is found."""
        return module_id in self._auto_connect_modules

    def set_auto_connect(self, module_id: str, auto_connect: bool) -> None:
        """Set auto-connect preference for a module."""
        if auto_connect:
            self._auto_connect_modules.add(module_id)
        else:
            self._auto_connect_modules.discard(module_id)

    def get_auto_connect_modules(self) -> Set[str]:
        """Get all module IDs that should auto-connect."""
        return self._auto_connect_modules.copy()

    def set_auto_connect_modules(self, modules: Set[str]) -> None:
        """Set all auto-connect modules at once."""
        self._auto_connect_modules = modules.copy()

    def consume_auto_connect_for_device(self, module_id: str, device_id: str) -> bool:
        """
        Check and consume an auto-connect request for a specific device.

        For multi-instance modules:
            - Returns True if module should auto-connect AND this device hasn't been auto-connected yet
            - Tracks this device as auto-connected (prevents double auto-connect)
            - Does NOT remove module from auto-connect set (so other devices also auto-connect)

        For single-instance modules:
            - Removes module from auto-connect set (standard consume behavior)

        Args:
            module_id: The module ID (e.g., "Cameras", "DRT")
            device_id: The specific device ID (e.g., "/dev/video0", "/dev/ttyACM0")

        Returns:
            True if this device should auto-connect, False otherwise.
        """
        # Check if module is in auto-connect set
        if module_id not in self._auto_connect_modules:
            return False

        # Normalize module_id for multi-instance check
        normalized = module_id.upper()

        if normalized in self._multi_instance_modules:
            # Multi-instance: track by device_id, keep module in set
            if device_id in self._auto_connected_devices:
                return False  # Already auto-connected this device
            self._auto_connected_devices.add(device_id)
            logger.debug(
                "Multi-instance auto-connect: %s device %s (total: %d)",
                module_id, device_id, len(self._auto_connected_devices)
            )
            return True
        else:
            # Single-instance: consume module from set
            self._auto_connect_modules.discard(module_id)
            return True

    def set_multi_instance_modules(self, modules: Set[str]) -> None:
        """Set which modules support multiple simultaneous instances.

        For these modules, auto-connect applies to ALL devices found,
        not just the first one.

        Args:
            modules: Set of module IDs (uppercase, e.g., {"DRT", "VOG", "CAMERAS"})
        """
        self._multi_instance_modules = {m.upper() for m in modules}
        logger.debug("Multi-instance modules: %s", self._multi_instance_modules)

    def clear_auto_connected_devices(self) -> None:
        """Clear the set of auto-connected devices.

        Call this after startup completes to allow future auto-connects
        if devices are reconnected.
        """
        count = len(self._auto_connected_devices)
        self._auto_connected_devices.clear()
        if count:
            logger.debug("Cleared %d auto-connected devices", count)

    # =========================================================================
    # Observers
    # =========================================================================

    def add_connection_observer(self, observer: StateObserver) -> None:
        """Register an observer for connection enable/disable changes."""
        if observer not in self._connection_observers:
            self._connection_observers.append(observer)

    def remove_connection_observer(self, observer: StateObserver) -> None:
        """Unregister a connection observer."""
        if observer in self._connection_observers:
            self._connection_observers.remove(observer)

    def add_device_state_observer(self, observer: StateObserver) -> None:
        """Register an observer for device state changes."""
        if observer not in self._device_state_observers:
            self._device_state_observers.append(observer)

    def remove_device_state_observer(self, observer: StateObserver) -> None:
        """Unregister a device state observer."""
        if observer in self._device_state_observers:
            self._device_state_observers.remove(observer)

    def _notify_connection_observers(self) -> None:
        """Notify all connection observers."""
        for observer in self._connection_observers:
            try:
                observer()
            except Exception as e:
                logger.error(f"Error in connection observer: {e}")

    def _notify_device_state_observers(self) -> None:
        """Notify all device state observers."""
        for observer in self._device_state_observers:
            try:
                observer()
            except Exception as e:
                logger.error(f"Error in device state observer: {e}")

    # =========================================================================
    # Serialization (for config persistence)
    # =========================================================================

    def serialize_connections(self) -> str:
        """
        Serialize enabled connections to string format.

        Format: "USB:VOG,USB:DRT,XBee:VOG,..."
        """
        return ",".join(
            f"{interface.value}:{family.value}"
            for interface, family in sorted(
                self._enabled_connections,
                key=lambda x: (x[0].value, x[1].value)
            )
        )

    def deserialize_connections(self, data: str) -> None:
        """
        Deserialize enabled connections from string format.

        Format: "USB:VOG,USB:DRT,XBee:VOG,..."
        """
        if not data:
            return

        connections: Set[ConnectionKey] = set()
        for item in data.split(","):
            item = item.strip()
            if ":" not in item:
                continue
            interface_str, family_str = item.split(":", 1)
            try:
                interface = InterfaceType(interface_str)
                family = DeviceFamily(family_str)
                connections.add((interface, family))
            except ValueError as e:
                logger.warning(f"Invalid connection format '{item}': {e}")

        self.set_enabled_connections(connections)

    # =========================================================================
    # Query Helpers
    # =========================================================================

    def get_devices_to_disconnect_on_disable(
        self,
        interface: InterfaceType,
        family: DeviceFamily,
        device_interfaces: dict[str, tuple[InterfaceType, DeviceFamily]],
    ) -> list[str]:
        """
        Get device IDs that should be disconnected when disabling a connection.

        Args:
            interface: The interface being disabled
            family: The family being disabled
            device_interfaces: Map of device_id to (interface, family) tuples

        Returns:
            List of device IDs that are connected and match the disabled connection.
        """
        devices_to_disconnect = []
        for device_id, (dev_interface, dev_family) in device_interfaces.items():
            if (
                dev_interface == interface
                and dev_family == family
                and self.is_device_connected(device_id)
            ):
                devices_to_disconnect.append(device_id)
        return devices_to_disconnect
