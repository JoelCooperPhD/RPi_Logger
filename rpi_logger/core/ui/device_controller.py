"""
Device UI Controller - Transforms domain state into UI-ready data.

This module provides the bridge between the device domain layer and the UI.
It transforms DeviceSelectionModel and DeviceLifecycleManager state into
simple data structures that UI components can render without any domain knowledge.

Key principles:
- UI components receive simple dataclasses, not domain objects
- All domain logic stays in this controller
- UI only needs to render and wire callbacks
- Changes in domain automatically trigger UI updates via observers
"""

from dataclasses import dataclass, field
from typing import Callable

from rpi_logger.core.logging_utils import get_module_logger
from ..devices.catalog import DeviceCatalog
from ..devices.selection import DeviceSelectionModel
from ..devices.lifecycle import DeviceLifecycleManager, DeviceInfo
from ..devices.device_registry import DeviceFamily, InterfaceType

logger = get_module_logger("DeviceUIController")


# =========================================================================
# UI Data Structures - Simple dataclasses for UI rendering
# =========================================================================

@dataclass
class DeviceRowData:
    """
    UI-ready data for a single device row in the panel.

    The UI component just renders this and wires the callbacks.
    """
    device_id: str
    display_name: str
    connected: bool
    connecting: bool
    on_toggle_connect: Callable[[bool], None]


@dataclass
class DeviceSectionData:
    """
    UI-ready data for a device section in the panel.

    Contains the section label, visibility, and device rows.
    """
    label: str
    visible: bool
    devices: list[DeviceRowData] = field(default_factory=list)


# Type alias for UI update callbacks
UIUpdateCallback = Callable[[], None]


class DeviceUIController:
    """
    Controller that transforms domain state into UI-ready data.

    This class:
    - Observes DeviceSelectionModel and DeviceLifecycleManager for changes
    - Transforms domain state into simple UI data structures
    - Provides callbacks that UI components can wire to buttons/checkboxes
    - Notifies UI components when they need to re-render

    UI components should:
    1. Call get_panel_data() to get render data
    2. Register via add_ui_observer() to know when to re-render
    3. Wire callbacks from the data structures to their widgets
    """

    def __init__(
        self,
        selection_model: DeviceSelectionModel,
        lifecycle_manager: DeviceLifecycleManager,
        catalog: type[DeviceCatalog] | None = None,
    ):
        """
        Initialize the controller.

        Args:
            selection_model: The selection model for connection state
            lifecycle_manager: The lifecycle manager for device state
            catalog: Device catalog for metadata (uses DeviceCatalog if None)
        """
        self._selection = selection_model
        self._lifecycle = lifecycle_manager
        self._catalog = catalog or DeviceCatalog

        # UI observers
        self._ui_observers: list[UIUpdateCallback] = []

        # Connection action callbacks (set by application layer)
        self._on_connect_device: Callable[[str], None] | None = None
        self._on_disconnect_device: Callable[[str], None] | None = None
        self._on_connection_changed: Callable[[InterfaceType, DeviceFamily, bool], None] | None = None

        # XBee dongle state
        self._xbee_dongle_connected = False
        self._wireless_device_count = 0

        # Subscribe to model changes
        selection_model.add_connection_observer(self._on_model_changed)
        selection_model.add_device_state_observer(self._on_model_changed)
        lifecycle_manager.add_change_observer(self._on_model_changed)

    # =========================================================================
    # Action Callbacks (set by application layer)
    # =========================================================================

    def set_connect_device_callback(self, callback: Callable[[str], None]) -> None:
        """Set callback for when user wants to connect a device."""
        self._on_connect_device = callback

    def set_disconnect_device_callback(self, callback: Callable[[str], None]) -> None:
        """Set callback for when user wants to disconnect a device."""
        self._on_disconnect_device = callback

    def set_connection_changed_callback(
        self,
        callback: Callable[[InterfaceType, DeviceFamily, bool], None]
    ) -> None:
        """Set callback for when user toggles a connection type."""
        self._on_connection_changed = callback

    # =========================================================================
    # Connection Toggle Handling
    # =========================================================================

    def _handle_connection_toggle(
        self,
        interface: InterfaceType,
        family: DeviceFamily,
        enabled: bool
    ) -> None:
        """Handle a connection toggle from the UI."""
        logger.info(
            f"Connection toggle: {interface.value}:{family.value} -> {enabled}"
        )

        # Update selection model
        self._selection.set_connection_enabled(interface, family, enabled)

        # Notify application layer
        if self._on_connection_changed:
            self._on_connection_changed(interface, family, enabled)

    # =========================================================================
    # Panel Data
    # =========================================================================

    def get_panel_data(self) -> list[DeviceSectionData]:
        """
        Get UI-ready data for the Devices panel.

        Returns device sections organized by family, with visibility
        based on enabled connections.
        """
        devices_by_family = self._lifecycle.get_devices_grouped_by_family()
        sections: list[DeviceSectionData] = []

        for family_meta in self._catalog.families_ordered():
            family = family_meta.family
            is_visible = self._selection.is_family_enabled(family)

            devices = devices_by_family.get(family, [])
            device_rows = [
                self._make_device_row_data(device)
                for device in devices
            ]

            sections.append(DeviceSectionData(
                label=family_meta.display_name,
                visible=is_visible,
                devices=device_rows,
            ))

        return sections

    def _make_device_row_data(self, device: DeviceInfo) -> DeviceRowData:
        """Create UI-ready data for a device row."""
        is_connected = self._selection.is_device_connected(device.device_id)
        is_connecting = self._selection.is_device_connecting(device.device_id)

        return DeviceRowData(
            device_id=device.device_id,
            display_name=device.display_name,
            connected=is_connected,
            connecting=is_connecting,
            on_toggle_connect=self._make_device_connect_callback(device.device_id),
        )

    def _make_device_connect_callback(self, device_id: str) -> Callable[[bool], None]:
        """Create a callback for toggling device connection."""
        def toggle(connect: bool) -> None:
            self._handle_device_connect_toggle(device_id, connect)
        return toggle

    def _handle_device_connect_toggle(self, device_id: str, connect: bool) -> None:
        """Handle a device connect/disconnect toggle from the UI."""
        logger.info(f"Device toggle: {device_id} -> {'connect' if connect else 'disconnect'}")

        if connect:
            if self._on_connect_device:
                self._on_connect_device(device_id)
        else:
            if self._on_disconnect_device:
                self._on_disconnect_device(device_id)

    # =========================================================================
    # UI Observers
    # =========================================================================

    def add_ui_observer(self, observer: UIUpdateCallback) -> None:
        """
        Register a UI component to be notified when data changes.

        UI components should call this and re-render when notified.
        """
        if observer not in self._ui_observers:
            self._ui_observers.append(observer)

    def remove_ui_observer(self, observer: UIUpdateCallback) -> None:
        """Unregister a UI observer."""
        if observer in self._ui_observers:
            self._ui_observers.remove(observer)

    def _on_model_changed(self) -> None:
        """Called when underlying models change."""
        self._notify_ui_observers()

    def _notify_ui_observers(self) -> None:
        """Notify all UI observers that they should re-render."""
        for observer in self._ui_observers:
            try:
                observer()
            except Exception as e:
                logger.error(f"Error in UI observer: {e}")

    # =========================================================================
    # Convenience Methods
    # =========================================================================

    def get_enabled_connections_string(self) -> str:
        """Get enabled connections as a serialized string (for config)."""
        return self._selection.serialize_connections()

    def set_enabled_connections_string(self, data: str) -> None:
        """Set enabled connections from a serialized string (from config)."""
        self._selection.deserialize_connections(data)

    def has_any_enabled_connection(self) -> bool:
        """Check if any connection is enabled."""
        return bool(self._selection.get_enabled_connections())

    def has_any_device(self) -> bool:
        """Check if any device is tracked."""
        return bool(self._lifecycle.get_all_devices())

    def get_device_count(self) -> int:
        """Get total number of tracked devices."""
        return len(self._lifecycle.get_all_devices())

    def get_connected_device_count(self) -> int:
        """Get number of connected devices."""
        return len(self._lifecycle.get_connected_devices())

    # =========================================================================
    # XBee Dongle State
    # =========================================================================

    @property
    def xbee_dongle_connected(self) -> bool:
        """Check if XBee dongle is connected."""
        return self._xbee_dongle_connected

    def set_xbee_dongle_connected(self, connected: bool) -> None:
        """
        Update XBee dongle connection state.

        This triggers a UI update so the XBee banner can be shown/hidden.

        Args:
            connected: True if XBee dongle is connected
        """
        if self._xbee_dongle_connected != connected:
            self._xbee_dongle_connected = connected
            self._notify_ui_observers()

    def set_xbee_rescan_callback(self, callback: Callable[[], None]) -> None:
        """Set callback for XBee network rescan requests."""
        self._on_xbee_rescan = callback

    def request_xbee_rescan(self) -> None:
        """Request an XBee network rescan."""
        if hasattr(self, '_on_xbee_rescan') and self._on_xbee_rescan:
            logger.info("Requesting XBee network rescan")
            self._on_xbee_rescan()

    @property
    def wireless_device_count(self) -> int:
        """Get the number of wireless devices discovered."""
        return self._wireless_device_count

    def set_wireless_device_count(self, count: int) -> None:
        """Update the wireless device count."""
        if self._wireless_device_count != count:
            self._wireless_device_count = count
            self._notify_ui_observers()
