"""
Device Lifecycle Manager - Unified handling of all device events.

This module provides a single, unified handler for all device discovery
and removal events. Instead of 8 separate handlers with duplicated logic,
all scanner events flow through this manager.

Key responsibilities:
- Unified device discovery handling
- Unified device removal handling
- Display name generation
- Auto-connect logic
- Device state management
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

from rpi_logger.core.logging_utils import get_module_logger
from .device_registry import DeviceType, DeviceFamily, InterfaceType
from .catalog import DeviceCatalog
from .selection import DeviceSelectionModel, ConnectionState
from .events import DeviceDiscoveredEvent, DeviceLostEvent, DeviceEvent

logger = get_module_logger("DeviceLifecycleManager")


@dataclass
class DeviceInfo:
    """
    Complete information about a discovered device.

    This dataclass holds all information needed to display and interact
    with a device, regardless of its type or interface.
    """
    device_id: str
    device_type: DeviceType
    family: DeviceFamily
    interface_type: InterfaceType
    display_name: str
    port: str | None
    baudrate: int
    module_id: str
    state: ConnectionState = ConnectionState.DISCOVERED

    # Optional metadata (set based on device type)
    is_wireless: bool = False
    is_network: bool = False
    is_audio: bool = False
    is_internal: bool = False
    is_camera: bool = False
    is_uart: bool = False

    # Extended metadata (stored as dict for flexibility)
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_meta(self, key: str, default: Any = None) -> Any:
        """Get a metadata value."""
        return self.metadata.get(key, default)


# Type aliases
DevicesChangedCallback = Callable[[], None]
ConnectCallback = Callable[[str], Awaitable[None]]
DisconnectCallback = Callable[[str], Awaitable[None]]


class DeviceLifecycleManager:
    """
    Unified lifecycle manager for all device types.

    This class handles device discovery and removal events from all scanners
    through a single code path, eliminating the duplication of having
    separate handlers for USB, XBee, Network, Audio, etc.

    The manager:
    - Checks if devices are enabled before tracking them
    - Builds consistent display names
    - Handles auto-connect logic
    - Manages device state
    - Notifies observers when device list changes
    """

    def __init__(
        self,
        selection_model: DeviceSelectionModel,
        catalog: DeviceCatalog | None = None,
    ):
        """
        Initialize the lifecycle manager.

        Args:
            selection_model: The selection model for checking enabled state
            catalog: Device catalog for metadata (uses DeviceCatalog if None)
        """
        self._selection = selection_model
        self._catalog = catalog or DeviceCatalog

        # Device storage
        self._devices: dict[str, DeviceInfo] = {}

        # Observers
        self._change_observers: list[DevicesChangedCallback] = []

        # Connection callbacks (set by application layer)
        self._connect_callback: ConnectCallback | None = None
        self._disconnect_callback: DisconnectCallback | None = None

    # =========================================================================
    # Event Handling - Single Entry Point
    # =========================================================================

    async def handle_event(self, event: DeviceEvent) -> None:
        """
        Handle any device event (discovered or lost).

        This is the single entry point for ALL device events from ALL scanners.
        """
        if isinstance(event, DeviceDiscoveredEvent):
            await self._handle_discovered(event)
        elif isinstance(event, DeviceLostEvent):
            await self._handle_lost(event)

    async def _handle_discovered(self, event: DeviceDiscoveredEvent) -> None:
        """
        Handle a device discovery event.

        This single method replaces 8 separate discovery handlers.
        """
        # 1. Check if this connection type is enabled
        if not self._selection.is_connection_enabled(event.interface, event.family):
            logger.debug(
                f"Ignoring disabled device: {event.raw_name or event.family.value} "
                f"({event.interface.value}:{event.family.value})"
            )
            return

        # 2. Build display name (consistent pattern for ALL devices)
        display_name = self._catalog.build_device_display_name(
            raw_name=event.raw_name,
            family=event.family,
            interface=event.interface,
            device_id=event.device_id,
            include_interface=True,
        )

        # 3. Determine device flags from metadata
        metadata = event.metadata.copy()
        is_wireless = metadata.pop("is_wireless", False)
        is_network = metadata.pop("is_network", False)
        is_audio = metadata.pop("is_audio", False)
        is_internal = metadata.pop("is_internal", False)
        is_camera = metadata.pop("is_camera", False)
        is_uart = metadata.pop("is_uart", False)

        # 4. Create DeviceInfo
        device_info = DeviceInfo(
            device_id=event.device_id,
            device_type=event.device_type,
            family=event.family,
            interface_type=event.interface,
            display_name=display_name,
            port=event.port,
            baudrate=event.baudrate,
            module_id=event.module_id,
            state=ConnectionState.DISCOVERED,
            is_wireless=is_wireless,
            is_network=is_network,
            is_audio=is_audio,
            is_internal=is_internal,
            is_camera=is_camera,
            is_uart=is_uart,
            metadata=metadata,
        )

        # 5. Store device
        self._devices[event.device_id] = device_info
        logger.info(f"Device discovered: {display_name} ({event.device_id})")

        # 6. Check auto-connect
        # Use device-aware method to support multi-instance modules (DRT, VOG, Cameras)
        # which need to auto-connect ALL devices, not just the first one
        if self._selection.consume_auto_connect_for_device(event.module_id, event.device_id):
            logger.info(f"Auto-connecting device {event.device_id} for module {event.module_id}")
            if self._connect_callback:
                await self._connect_callback(event.device_id)
            return  # notify_changed called by connect callback

        # 7. Notify observers
        self._notify_changed()

    async def _handle_lost(self, event: DeviceLostEvent) -> None:
        """
        Handle a device lost event.

        This single method replaces 8 separate lost handlers.
        """
        device_id = event.device_id

        # 1. Disconnect if connected
        if self._selection.is_device_connected(device_id):
            logger.info(f"Disconnecting lost device: {device_id}")
            if self._disconnect_callback:
                await self._disconnect_callback(device_id)

        # 2. Remove device state from selection model
        self._selection.remove_device_state(device_id)

        # 3. Remove from storage
        device = self._devices.pop(device_id, None)
        if device:
            logger.info(f"Device lost: {device.display_name} ({device_id})")

        # 4. Notify observers
        self._notify_changed()

    # =========================================================================
    # Device Queries
    # =========================================================================

    def get_device(self, device_id: str) -> DeviceInfo | None:
        """Get a device by ID."""
        return self._devices.get(device_id)

    def get_all_devices(self) -> list[DeviceInfo]:
        """Get all tracked devices."""
        return list(self._devices.values())

    def get_devices_by_family(self, family: DeviceFamily) -> list[DeviceInfo]:
        """Get all devices of a specific family."""
        return [d for d in self._devices.values() if d.family == family]

    def get_devices_by_interface(self, interface: InterfaceType) -> list[DeviceInfo]:
        """Get all devices of a specific interface type."""
        return [d for d in self._devices.values() if d.interface_type == interface]

    def get_devices_for_module(self, module_id: str) -> list[DeviceInfo]:
        """Get all devices that belong to a specific module."""
        return [d for d in self._devices.values() if d.module_id == module_id]

    def get_devices_grouped_by_family(self) -> dict[DeviceFamily, list[DeviceInfo]]:
        """
        Get all devices grouped by family.

        Returns:
            Dict mapping DeviceFamily to list of devices, ordered by catalog order.
        """
        result: dict[DeviceFamily, list[DeviceInfo]] = {}
        for family in self._catalog.get_family_order():
            result[family] = []

        for device in self._devices.values():
            if device.family in result:
                result[device.family].append(device)

        return result

    def get_devices_grouped_by_interface(self) -> dict[InterfaceType, list[DeviceInfo]]:
        """Get all devices grouped by interface type."""
        result: dict[InterfaceType, list[DeviceInfo]] = {}
        for interface in self._catalog.get_interface_order():
            result[interface] = []

        for device in self._devices.values():
            if device.interface_type in result:
                result[device.interface_type].append(device)

        return result

    def get_device_interface_map(self) -> dict[str, tuple[InterfaceType, DeviceFamily]]:
        """Get a map of device_id to (interface, family) tuples."""
        return {
            d.device_id: (d.interface_type, d.family)
            for d in self._devices.values()
        }

    # =========================================================================
    # Connection State Management
    # =========================================================================

    def set_device_connected(self, device_id: str, connected: bool) -> None:
        """
        Update device connection state.

        This is called by the application layer when a device actually
        connects or disconnects.
        """
        # Update selection model
        self._selection.set_device_connected(device_id, connected)

        # Update device info state
        device = self._devices.get(device_id)
        if device:
            device.state = ConnectionState.CONNECTED if connected else ConnectionState.DISCOVERED

        self._notify_changed()

    def set_device_connecting(self, device_id: str) -> None:
        """
        Set device to CONNECTING state (yellow indicator).

        Called when user clicks to connect but before module acknowledges ready.
        """
        # Update selection model
        self._selection.set_device_state(device_id, ConnectionState.CONNECTING)

        # Update device info state
        device = self._devices.get(device_id)
        if device:
            device.state = ConnectionState.CONNECTING

        self._notify_changed()

    def get_connected_devices(self) -> list[DeviceInfo]:
        """Get all connected devices."""
        connected_ids = self._selection.get_connected_device_ids()
        return [d for d in self._devices.values() if d.device_id in connected_ids]

    def get_connected_devices_for_connection(
        self,
        interface: InterfaceType,
        family: DeviceFamily
    ) -> list[DeviceInfo]:
        """Get connected devices for a specific connection type."""
        connected_ids = self._selection.get_connected_device_ids()
        return [
            d for d in self._devices.values()
            if d.device_id in connected_ids
            and d.interface_type == interface
            and d.family == family
        ]

    # =========================================================================
    # Callbacks
    # =========================================================================

    def set_connect_callback(self, callback: ConnectCallback) -> None:
        """Set the callback for connecting a device."""
        self._connect_callback = callback

    def set_disconnect_callback(self, callback: DisconnectCallback) -> None:
        """Set the callback for disconnecting a device."""
        self._disconnect_callback = callback

    # =========================================================================
    # Observers
    # =========================================================================

    def add_change_observer(self, observer: DevicesChangedCallback) -> None:
        """Register an observer for device list changes."""
        if observer not in self._change_observers:
            self._change_observers.append(observer)

    def remove_change_observer(self, observer: DevicesChangedCallback) -> None:
        """Unregister a change observer."""
        if observer in self._change_observers:
            self._change_observers.remove(observer)

    def _notify_changed(self) -> None:
        """Notify all observers that the device list changed."""
        for observer in self._change_observers:
            try:
                observer()
            except Exception as e:
                logger.error(f"Error in change observer: {e}")

    # =========================================================================
    # Connection Disable Handling
    # =========================================================================

    def get_devices_to_disconnect_on_disable(
        self,
        interface: InterfaceType,
        family: DeviceFamily
    ) -> list[DeviceInfo]:
        """
        Get devices that should be disconnected when a connection is disabled.

        Returns list of connected devices matching the interface+family.
        """
        return self.get_connected_devices_for_connection(interface, family)

    def remove_devices_for_connection(
        self,
        interface: InterfaceType,
        family: DeviceFamily
    ) -> list[str]:
        """
        Remove all devices for a connection type (when disabled).

        Returns list of removed device IDs.
        """
        to_remove = [
            device_id
            for device_id, device in self._devices.items()
            if device.interface_type == interface and device.family == family
        ]

        for device_id in to_remove:
            self._selection.remove_device_state(device_id)
            del self._devices[device_id]

        if to_remove:
            self._notify_changed()

        return to_remove

    # =========================================================================
    # Bulk Operations (for initialization)
    # =========================================================================

    def clear_all_devices(self) -> None:
        """Remove all tracked devices."""
        self._devices.clear()
        self._notify_changed()
