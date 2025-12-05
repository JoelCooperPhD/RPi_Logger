"""
USB Devices panel for main window.

Displays discovered USB devices as distinct tiles with activate/show controls.
"""

import tkinter as tk
from tkinter import ttk
from typing import Callable, Dict, List

from rpi_logger.core.logging_utils import get_module_logger
from ..devices import DeviceInfo, XBeeDongleInfo, ConnectionState
from .theme import Theme, Colors, RoundedButton

logger = get_module_logger("DevicesPanel")


class DeviceTile(ttk.LabelFrame):
    """
    A distinct tile frame for a single device.

    Shows device info with activate checkbox and show/hide window button.
    """

    def __init__(
        self,
        parent,
        device: DeviceInfo,
        on_activate_toggle: Callable[[str, bool], None],
        on_show_hide: Callable[[str], None],
    ):
        # Use device display name as frame title
        super().__init__(parent, text=device.display_name, padding=5)
        self.device = device
        self._on_activate_toggle = on_activate_toggle
        self._on_show_hide = on_show_hide

        self.columnconfigure(0, weight=1)

        # Row 0: Device type and status
        info_frame = ttk.Frame(self)
        info_frame.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        info_frame.columnconfigure(1, weight=1)

        # Device type label
        type_text = self._get_device_type_text()
        self.type_label = ttk.Label(info_frame, text=type_text, style='Secondary.TLabel')
        self.type_label.grid(row=0, column=0, sticky="w")

        # Status label (right-aligned)
        self.status_label = ttk.Label(
            info_frame,
            text=self._get_status_text(),
            foreground=self._get_status_color()
        )
        self.status_label.grid(row=0, column=1, sticky="e")

        # Row 1: Battery (if available)
        if device.battery_percent is not None:
            battery_text = f"Battery: {device.battery_percent}%"
            self.battery_label = ttk.Label(self, text=battery_text)
            self.battery_label.grid(row=1, column=0, sticky="w", pady=(0, 5))
        else:
            self.battery_label = None

        # Row 2: Port info
        if device.port:
            port_text = f"Port: {device.port}"
            if device.is_wireless:
                port_text = f"Via: {device.port} (wireless)"
            self.port_label = ttk.Label(self, text=port_text, style='Secondary.TLabel')
            self.port_label.grid(row=2, column=0, sticky="w", pady=(0, 5))

        # Row 3: Control buttons
        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=3, column=0, sticky="ew")
        btn_frame.columnconfigure(0, weight=1)

        # Activate checkbox
        self.activate_var = tk.BooleanVar(
            value=device.state == ConnectionState.CONNECTED
        )
        self.activate_cb = ttk.Checkbutton(
            btn_frame,
            text="Activate",
            variable=self.activate_var,
            command=self._on_activate_click,
        )
        self.activate_cb.grid(row=0, column=0, sticky="w")

        # Show/Hide button - use RoundedButton for consistent styling
        self.show_btn = RoundedButton(
            btn_frame,
            text="Show",
            command=self._on_show_click,
            width=70,
            height=28,
            style='default',
        )
        self.show_btn.grid(row=0, column=1, sticky="e", padx=(5, 0))

        self._update_button_states()

    def _get_device_type_text(self) -> str:
        """Get human-readable device type."""
        type_map = {
            "sVOG": "Serial VOG",
            "wVOG_USB": "Wireless VOG (USB)",
            "wVOG_Wireless": "Wireless VOG",
            "sDRT": "Serial DRT",
            "wDRT_USB": "Wireless DRT (USB)",
            "wDRT_Wireless": "Wireless DRT",
            "XBee_Coordinator": "XBee Coordinator",
        }
        return type_map.get(self.device.device_type.value, self.device.device_type.value)

    def _get_status_text(self) -> str:
        """Get display text for connection state."""
        state_map = {
            ConnectionState.DISCOVERED: "Ready",
            ConnectionState.CONNECTING: "Connecting...",
            ConnectionState.CONNECTED: "Active",
            ConnectionState.ERROR: "Error",
        }
        return state_map.get(self.device.state, "Unknown")

    def _get_status_color(self) -> str:
        """Get color for status text."""
        color_map = {
            ConnectionState.DISCOVERED: Colors.STATUS_READY,
            ConnectionState.CONNECTING: Colors.STATUS_CONNECTING,
            ConnectionState.CONNECTED: Colors.STATUS_CONNECTED,
            ConnectionState.ERROR: Colors.STATUS_ERROR,
        }
        return color_map.get(self.device.state, Colors.FG_SECONDARY)

    def _on_activate_click(self) -> None:
        self._on_activate_toggle(self.device.device_id, self.activate_var.get())

    def _on_show_click(self) -> None:
        self._on_show_hide(self.device.device_id)

    def _update_button_states(self) -> None:
        """Update button states based on device state."""
        # Show button is always enabled - clicking it will activate if needed
        self.show_btn.configure(state="normal")

    def update_device(self, device: DeviceInfo) -> None:
        """Update tile with new device info."""
        self.device = device

        # Update title
        self.configure(text=device.display_name)

        # Update type
        self.type_label.configure(text=self._get_device_type_text())

        # Update status
        self.status_label.configure(
            text=self._get_status_text(),
            foreground=self._get_status_color()
        )

        # Update battery if present
        if self.battery_label and device.battery_percent is not None:
            self.battery_label.configure(text=f"Battery: {device.battery_percent}%")

        # Update checkbox state
        self.activate_var.set(device.state == ConnectionState.CONNECTED)

        # Update button states
        self._update_button_states()


class DongleTile(ttk.LabelFrame):
    """
    A tile frame for an XBee dongle.

    Shows dongle info and contains nested child device tiles.
    """

    def __init__(
        self,
        parent,
        dongle: XBeeDongleInfo,
        on_activate_toggle: Callable[[str, bool], None],
        on_show_hide: Callable[[str], None],
    ):
        super().__init__(parent, text=f"XBee Dongle ({dongle.port})", padding=5)
        self.dongle = dongle
        self._on_activate_toggle = on_activate_toggle
        self._on_show_hide = on_show_hide
        self._child_tiles: Dict[str, DeviceTile] = {}

        self.columnconfigure(0, weight=1)

        # Row 0: Status
        status_frame = ttk.Frame(self)
        status_frame.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        status_frame.columnconfigure(1, weight=1)

        ttk.Label(status_frame, text="XBee Coordinator", style='Secondary.TLabel').grid(
            row=0, column=0, sticky="w"
        )

        status_text, status_color = self._get_status()
        self.status_label = ttk.Label(
            status_frame, text=status_text, foreground=status_color
        )
        self.status_label.grid(row=0, column=1, sticky="e")

        # Row 1: Child devices container (indented)
        self.children_frame = ttk.Frame(self)
        self.children_frame.grid(row=1, column=0, sticky="ew", padx=(15, 0))
        self.children_frame.columnconfigure(0, weight=1)

        # Empty state for no child devices
        self.no_children_label = ttk.Label(
            self.children_frame,
            text="No wireless devices found",
            style='Muted.TLabel',
            font=("TkDefaultFont", 9, "italic"),
        )
        self._update_children()

    def _get_status(self) -> tuple:
        """Get status text and color."""
        state_map = {
            ConnectionState.DISCOVERED: ("Scanning...", Colors.STATUS_CONNECTING),
            ConnectionState.CONNECTING: ("Connecting...", Colors.STATUS_CONNECTING),
            ConnectionState.CONNECTED: ("Connected", Colors.STATUS_CONNECTED),
            ConnectionState.ERROR: ("Error", Colors.STATUS_ERROR),
        }
        return state_map.get(self.dongle.state, ("Unknown", Colors.FG_SECONDARY))

    def _update_children(self) -> None:
        """Update child device tiles incrementally to avoid flashing."""
        if not self.dongle.child_devices:
            # No children - show empty label and clear tiles
            self.no_children_label.grid(row=0, column=0, sticky="w", pady=5)
            for tile in self._child_tiles.values():
                tile.destroy()
            self._child_tiles.clear()
            return

        self.no_children_label.grid_remove()

        # Build set of current child IDs
        current_child_ids = set(self.dongle.child_devices.keys())

        # Remove tiles for children that no longer exist
        removed_child_ids = set(self._child_tiles.keys()) - current_child_ids
        for child_id in removed_child_ids:
            self._child_tiles[child_id].destroy()
            del self._child_tiles[child_id]

        # Update or create tiles for current children
        for idx, device in enumerate(self.dongle.child_devices.values()):
            if device.device_id in self._child_tiles:
                # Update existing tile in-place
                self._child_tiles[device.device_id].update_device(device)
                self._child_tiles[device.device_id].grid(
                    row=idx, column=0, sticky="ew", pady=(0, 5)
                )
            else:
                # Create new tile
                tile = DeviceTile(
                    self.children_frame,
                    device,
                    self._on_activate_toggle,
                    self._on_show_hide,
                )
                tile.grid(row=idx, column=0, sticky="ew", pady=(0, 5))
                self._child_tiles[device.device_id] = tile

    def update_dongle(self, dongle: XBeeDongleInfo) -> None:
        """Update dongle tile with new info."""
        self.dongle = dongle
        self.configure(text=f"XBee Dongle ({dongle.port})")

        status_text, status_color = self._get_status()
        self.status_label.configure(text=status_text, foreground=status_color)

        self._update_children()


class USBDevicesPanel(ttk.LabelFrame):
    """Panel showing all discovered USB devices as tiles."""

    def __init__(
        self,
        parent,
        on_connect_toggle: Callable[[str, bool], None],
        on_show_window: Callable[[str], None],
    ):
        super().__init__(parent, text="Devices")
        self._on_connect_toggle = on_connect_toggle
        self._on_show_window = on_show_window

        self._device_tiles: Dict[str, DeviceTile] = {}
        self._dongle_tiles: Dict[str, DongleTile] = {}

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        # Scrollable device list
        container = ttk.Frame(self)
        container.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        # Create canvas with scrollbar
        self.canvas = tk.Canvas(container, height=150, highlightthickness=0)
        Theme.configure_canvas(self.canvas, use_dark_bg=True)
        self.scrollbar = ttk.Scrollbar(
            container, orient="vertical", command=self.canvas.yview
        )
        self.scrollable_frame = ttk.Frame(self.canvas)
        self.scrollable_frame.columnconfigure(0, weight=1)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas_window = self.canvas.create_window(
            (0, 0), window=self.scrollable_frame, anchor="nw"
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        # Bind canvas resize to update inner frame width
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")

        # Mouse wheel scrolling
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Button-4>", self._on_mousewheel)
        self.canvas.bind_all("<Button-5>", self._on_mousewheel)

        # Empty state label
        self.empty_label = ttk.Label(
            self.scrollable_frame,
            text="No devices detected.\nConnect a supported device.",
            style='Muted.TLabel',
            justify="center",
        )
        self.empty_label.grid(row=0, column=0, pady=20)

    def _on_canvas_configure(self, event) -> None:
        """Update scrollable frame width when canvas resizes."""
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    def _on_mousewheel(self, event) -> None:
        """Handle mouse wheel scrolling."""
        if event.num == 4 or event.delta > 0:
            self.canvas.yview_scroll(-1, "units")
        elif event.num == 5 or event.delta < 0:
            self.canvas.yview_scroll(1, "units")

    def update_devices(
        self,
        devices: List[DeviceInfo],
        dongles: List[XBeeDongleInfo],
    ) -> None:
        """Update the device list display with tiles.

        Layout:
        - USB devices (direct connection) as top-level tiles
        - XBee dongles as tiles with nested child devices indented beneath

        This method performs incremental updates to avoid flashing:
        - Existing tiles are updated in-place
        - New tiles are created only for new devices
        - Tiles are destroyed only when devices are removed
        """
        has_any = bool(devices) or bool(dongles)

        # Show/hide empty label
        if has_any:
            self.empty_label.grid_remove()
        else:
            self.empty_label.grid(row=0, column=0, pady=20)
            # Clear all tiles when no devices
            for tile in self._device_tiles.values():
                tile.destroy()
            self._device_tiles.clear()
            for tile in self._dongle_tiles.values():
                tile.destroy()
            self._dongle_tiles.clear()
            return

        # Build sets of current IDs for comparison
        current_device_ids = {d.device_id for d in devices}
        current_dongle_ports = {d.port for d in dongles}

        # Remove tiles for devices that no longer exist
        removed_device_ids = set(self._device_tiles.keys()) - current_device_ids
        for device_id in removed_device_ids:
            self._device_tiles[device_id].destroy()
            del self._device_tiles[device_id]

        removed_dongle_ports = set(self._dongle_tiles.keys()) - current_dongle_ports
        for port in removed_dongle_ports:
            self._dongle_tiles[port].destroy()
            del self._dongle_tiles[port]

        row_idx = 0

        # First: USB devices (non-dongle)
        for device in devices:
            if device.device_id in self._device_tiles:
                # Update existing tile in-place
                self._device_tiles[device.device_id].update_device(device)
                self._device_tiles[device.device_id].grid(
                    row=row_idx, column=0, sticky="ew", pady=(0, 5), padx=2
                )
            else:
                # Create new tile
                tile = DeviceTile(
                    self.scrollable_frame,
                    device,
                    self._on_connect_toggle,
                    self._on_show_window,
                )
                tile.grid(row=row_idx, column=0, sticky="ew", pady=(0, 5), padx=2)
                self._device_tiles[device.device_id] = tile
            row_idx += 1

        # Second: XBee dongles with nested child devices
        for dongle in dongles:
            if dongle.port in self._dongle_tiles:
                # Update existing dongle tile in-place
                self._dongle_tiles[dongle.port].update_dongle(dongle)
                self._dongle_tiles[dongle.port].grid(
                    row=row_idx, column=0, sticky="ew", pady=(0, 5), padx=2
                )
            else:
                # Create new dongle tile
                dongle_tile = DongleTile(
                    self.scrollable_frame,
                    dongle,
                    self._on_connect_toggle,
                    self._on_show_window,
                )
                dongle_tile.grid(row=row_idx, column=0, sticky="ew", pady=(0, 5), padx=2)
                self._dongle_tiles[dongle.port] = dongle_tile
            row_idx += 1

        total_devices = len(devices) + sum(
            len(d.child_devices) for d in dongles
        )
        logger.debug(
            "Updated devices panel: %d USB devices, %d dongles, %d total devices",
            len(devices), len(dongles), total_devices
        )
