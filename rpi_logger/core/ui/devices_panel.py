"""
Devices panel for main window.

Displays discovered devices in sections matching the Connections menu:
- Internal: Software-only modules (Notes, etc.)
- USB: Direct USB-connected devices (VOG, DRT, Audio, USB cameras)
- XBee: Devices connected via XBee wireless dongles
- Network: Network-discovered devices (eye trackers via mDNS)
- CSI: Raspberry Pi CSI camera devices

Each device is shown as a single-line tile with:
- Round toggle button (green when on, dark when off)
- Device name
- Connect/Disconnect button (also shows/hides module window)
"""

import tkinter as tk
from tkinter import ttk
from typing import Callable, Dict, List, Optional

from rpi_logger.core.logging_utils import get_module_logger
from ..devices import DeviceInfo, XBeeDongleInfo, ConnectionState
from ..devices.device_registry import InterfaceType, DeviceFamily, ConnectionKey
from .theme.colors import Colors
from .theme.widgets import RoundedButton

logger = get_module_logger("DevicesPanel")


class RoundToggle(tk.Canvas):
    """A round toggle button that shows green when active, dark when inactive."""

    def __init__(
        self,
        parent,
        size: int = 20,
        command: Optional[Callable[[bool], None]] = None,
        active: bool = False,
    ):
        super().__init__(
            parent,
            width=size,
            height=size,
            highlightthickness=0,
            bg=Colors.BG_FRAME,
            cursor="hand2"
        )
        self._size = size
        self._command = command
        self._active = active
        self._hovering = False
        self._draw()
        self._bind_events()

    def _draw(self) -> None:
        """Draw the round toggle."""
        self.delete("all")
        padding = 2

        if self._active:
            # Green filled circle when active
            fill_color = Colors.SUCCESS_HOVER if self._hovering else Colors.STATUS_CONNECTED
            self.create_oval(
                padding, padding,
                self._size - padding, self._size - padding,
                fill=fill_color,
                outline=fill_color
            )
        else:
            # Dark circle with border when inactive
            fill_color = Colors.BG_DARKER if self._hovering else Colors.BG_DARK
            self.create_oval(
                padding, padding,
                self._size - padding, self._size - padding,
                fill=fill_color,
                outline=Colors.BORDER_LIGHT if self._hovering else Colors.BORDER,
                width=2
            )

    def _bind_events(self) -> None:
        """Bind mouse events."""
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    def _on_enter(self, event) -> None:
        self._hovering = True
        self._draw()

    def _on_leave(self, event) -> None:
        self._hovering = False
        self._draw()

    def _on_click(self, event) -> None:
        self._active = not self._active
        self._draw()
        if self._command:
            self._command(self._active)

    def set_active(self, active: bool) -> None:
        """Set the toggle state without triggering callback."""
        if self._active != active:
            self._active = active
            self._draw()

    def get_active(self) -> bool:
        """Get the current toggle state."""
        return self._active


class DeviceRow(ttk.Frame):
    """
    A single-line row for a device.

    Layout: [Round Toggle] [Device Name] [Connect/Disconnect Button]

    Single State Model:
    - Connected: Device is connected, module is running, and window is visible
    - Disconnected: Device is not connected, module is not running, window is hidden

    Behavior:
    - Dot click: Toggle connection state (connect shows window, disconnect hides it)
    - Connect button: Connect device, start module, show window
    - Disconnect button: Hide window, stop module, disconnect device
    """

    def __init__(
        self,
        parent,
        device: DeviceInfo,
        on_connect_change: Callable[[str, bool], None],
    ):
        super().__init__(parent, style='Inframe.TFrame')
        self.device = device
        self._on_connect_change = on_connect_change
        self._is_connected = device.state == ConnectionState.CONNECTED

        self.columnconfigure(1, weight=1)  # Device name expands

        # Round toggle button (column 0) - reflects connection state
        self.toggle_btn = RoundToggle(
            self,
            size=16,
            command=self._on_toggle_click,
            active=self._is_connected
        )
        self.toggle_btn.grid(row=0, column=0, padx=(4, 6), pady=2)

        # Device name (column 1)
        self.name_label = ttk.Label(
            self,
            text=device.display_name,
            style='Inframe.TLabel'
        )
        self.name_label.grid(row=0, column=1, sticky="w", pady=2)

        # Connect/Disconnect button (column 2)
        self.connect_btn = RoundedButton(
            self,
            text="Disconnect" if self._is_connected else "Connect",
            command=self._on_connect_click,
            width=70,
            height=20,
            corner_radius=5,
            style='default',
            bg=Colors.BG_FRAME
        )
        self.connect_btn.grid(row=0, column=2, padx=(4, 4), pady=2)

    def _on_toggle_click(self, active: bool) -> None:
        """Handle dot toggle click - toggle connection."""
        # Revert visual state until confirmed by callback
        self.toggle_btn.set_active(self._is_connected)
        self._on_connect_change(self.device.device_id, active)

    def _on_connect_click(self) -> None:
        """Handle connect/disconnect button click."""
        self._on_connect_change(self.device.device_id, not self._is_connected)

    def set_connected(self, connected: bool) -> None:
        """Set the connection state (called by callback)."""
        self._is_connected = connected
        self.toggle_btn.set_active(connected)
        self.connect_btn.configure(text="Disconnect" if connected else "Connect")

    def update_device(self, device: DeviceInfo) -> None:
        """Update with new device info."""
        self.device = device
        self.name_label.configure(text=device.display_name)
        # Sync connection state from device
        connected = device.state == ConnectionState.CONNECTED
        self.set_connected(connected)


class DeviceSection(ttk.Frame):
    """
    A section frame containing devices of a certain type.

    Has a banner header and contains device rows.
    """

    def __init__(
        self,
        parent,
        title: str,
        on_connect_change: Callable[[str, bool], None],
    ):
        super().__init__(parent, style='Inframe.TFrame')
        self._title = title
        self._on_connect_change = on_connect_change
        self._device_rows: Dict[str, DeviceRow] = {}

        self.columnconfigure(0, weight=1)

        # Banner header
        self.header = ttk.Frame(self, style='SectionHeader.TFrame')
        self.header.grid(row=0, column=0, sticky="ew")
        self.header.columnconfigure(0, weight=1)

        self.header_label = ttk.Label(
            self.header,
            text=title,
            style='SectionHeader.TLabel',
            font=('TkDefaultFont', 8, 'bold')
        )
        self.header_label.grid(row=0, column=0, sticky="w", padx=6, pady=2)

        # Content frame for device rows
        self.content = ttk.Frame(self, style='Inframe.TFrame')
        self.content.grid(row=1, column=0, sticky="ew", padx=2, pady=(0, 2))
        self.content.columnconfigure(0, weight=1)

        # Empty state label
        self.empty_label = ttk.Label(
            self.content,
            text="No devices",
            style='Inframe.Secondary.TLabel',
            font=('TkDefaultFont', 8, 'italic')
        )
        self.empty_label.grid(row=0, column=0, sticky="w", padx=6, pady=2)

    def update_devices(self, devices: List[DeviceInfo]) -> None:
        """Update the section with a list of devices."""
        if not devices:
            # Show empty state
            self.empty_label.grid(row=0, column=0, sticky="w", padx=6, pady=2)
            for row in self._device_rows.values():
                row.destroy()
            self._device_rows.clear()
            return

        # Hide empty label
        self.empty_label.grid_remove()

        # Build set of current device IDs
        current_ids = {d.device_id for d in devices}

        # Remove rows for devices that no longer exist
        removed_ids = set(self._device_rows.keys()) - current_ids
        for device_id in removed_ids:
            self._device_rows[device_id].destroy()
            del self._device_rows[device_id]

        # Update or create rows
        for idx, device in enumerate(devices):
            if device.device_id in self._device_rows:
                # Update existing row
                self._device_rows[device.device_id].update_device(device)
                self._device_rows[device.device_id].grid(
                    row=idx, column=0, sticky="ew", padx=4, pady=1
                )
            else:
                # Create new row
                row = DeviceRow(
                    self.content,
                    device,
                    self._on_connect_change,
                )
                row.grid(row=idx, column=0, sticky="ew", padx=4, pady=1)
                self._device_rows[device.device_id] = row

    def set_device_connected(self, device_id: str, connected: bool) -> bool:
        """Set device connection state. Returns True if device was found."""
        if device_id in self._device_rows:
            self._device_rows[device_id].set_connected(connected)
            return True
        return False


class USBDevicesPanel(ttk.LabelFrame):
    """Panel showing all discovered devices organized by connection type.

    Single Callback:
    - on_connect_change: Called when connection state should change (dot, Connect button)
      Connect=True: Connects device, starts module, shows window
      Connect=False: Hides window, stops module, disconnects device
    """

    def __init__(
        self,
        parent,
        on_connect_change: Callable[[str, bool], None],
    ):
        super().__init__(parent, text="Devices")
        self._on_connect_change = on_connect_change

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        # Main container with scrolling
        container = ttk.Frame(self, style='Inframe.TFrame')
        container.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        # Create canvas with scrollbar
        self.canvas = tk.Canvas(container, height=150, highlightthickness=0, bd=0)
        self.canvas.configure(bg=Colors.BG_FRAME)

        self.scrollbar = ttk.Scrollbar(
            container, orient="vertical", command=self.canvas.yview
        )
        self.scrollable_frame = ttk.Frame(self.canvas, style='Inframe.TFrame')
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

        # Create sections - names match Connections menu for clarity
        self.internal_section = DeviceSection(
            self.scrollable_frame,
            "Internal",
            self._on_connect_change,
        )
        self.internal_section.grid(row=0, column=0, sticky="ew", pady=(0, 4))

        self.usb_section = DeviceSection(
            self.scrollable_frame,
            "USB",
            self._on_connect_change,
        )
        self.usb_section.grid(row=1, column=0, sticky="ew", pady=(0, 4))

        self.wireless_section = DeviceSection(
            self.scrollable_frame,
            "XBee",
            self._on_connect_change,
        )
        self.wireless_section.grid(row=2, column=0, sticky="ew", pady=(0, 4))

        self.network_section = DeviceSection(
            self.scrollable_frame,
            "Network",
            self._on_connect_change,
        )
        self.network_section.grid(row=3, column=0, sticky="ew", pady=(0, 4))

        self.csi_section = DeviceSection(
            self.scrollable_frame,
            "CSI",
            self._on_connect_change,
        )
        self.csi_section.grid(row=4, column=0, sticky="ew")

        # Empty state (shown when no devices at all)
        self.empty_label = ttk.Label(
            self.scrollable_frame,
            text="No devices detected.\nConnect a supported device.",
            style='Inframe.Secondary.TLabel',
            justify="center",
        )

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
        network_devices: Optional[List[DeviceInfo]] = None,
        audio_devices: Optional[List[DeviceInfo]] = None,
        internal_devices: Optional[List[DeviceInfo]] = None,
        camera_devices: Optional[List[DeviceInfo]] = None,
        enabled_connections: Optional[set] = None,
    ) -> None:
        """Update the device list display.

        Args:
            devices: List of USB-connected devices (non-wireless)
            dongles: List of XBee dongles with their child wireless devices
            network_devices: List of network-discovered devices (e.g., eye trackers)
            audio_devices: List of audio devices (e.g., USB microphones)
            internal_devices: List of internal/virtual devices (e.g., Notes)
            camera_devices: List of camera devices (USB and Pi cameras)
            enabled_connections: Set of (InterfaceType, DeviceFamily) tuples that are enabled.
                Sections are shown if their connection type is enabled, even if no devices exist.
        """
        if network_devices is None:
            network_devices = []
        if audio_devices is None:
            audio_devices = []
        if internal_devices is None:
            internal_devices = []
        if camera_devices is None:
            camera_devices = []
        if enabled_connections is None:
            enabled_connections = set()

        # Collect all wireless devices from dongles
        wireless_devices = []
        for dongle in dongles:
            wireless_devices.extend(dongle.child_devices.values())

        # Merge audio and USB camera devices into USB section
        all_usb_devices = list(devices) + list(audio_devices or [])
        # USB cameras go in USB section, CSI cameras go in CSI section
        usb_cameras = [d for d in (camera_devices or [])
                       if getattr(d, 'interface_type', None) == InterfaceType.USB]
        csi_cameras = [d for d in (camera_devices or [])
                       if getattr(d, 'interface_type', None) != InterfaceType.USB]
        all_usb_devices.extend(usb_cameras)

        # Check which sections should be visible based on enabled connections
        # INTERNAL section: shown if Internal:Internal is enabled
        internal_enabled = (InterfaceType.INTERNAL, DeviceFamily.INTERNAL) in enabled_connections

        # USB section: shown if any USB connection is enabled
        usb_enabled = any(
            interface == InterfaceType.USB
            for interface, family in enabled_connections
        )

        # WIRELESS section: shown if any XBee connection is enabled
        wireless_enabled = any(
            interface == InterfaceType.XBEE
            for interface, _ in enabled_connections
        )

        # NETWORK section: shown if any Network connection is enabled
        network_enabled = any(
            interface == InterfaceType.NETWORK
            for interface, _ in enabled_connections
        )

        # CSI section: shown if CSI:Camera is enabled
        csi_enabled = (InterfaceType.CSI, DeviceFamily.CAMERA) in enabled_connections

        # Any section enabled means we should show the panel content
        has_any_enabled = (
            internal_enabled or usb_enabled or wireless_enabled
            or network_enabled or csi_enabled
        )

        # Show/hide sections based on enabled connections (not just device presence)
        if has_any_enabled:
            self.empty_label.grid_remove()

            # Track row index for visible sections
            row_idx = 0

            # INTERNAL section
            if internal_enabled:
                self.internal_section.update_devices(internal_devices)
                self.internal_section.grid(row=row_idx, column=0, sticky="ew", pady=(0, 4))
                row_idx += 1
            else:
                self.internal_section.grid_remove()

            # USB section (includes Audio and USB cameras)
            if usb_enabled:
                self.usb_section.update_devices(all_usb_devices)
                self.usb_section.grid(row=row_idx, column=0, sticky="ew", pady=(0, 4))
                row_idx += 1
            else:
                self.usb_section.grid_remove()

            # WIRELESS section
            if wireless_enabled:
                self.wireless_section.update_devices(wireless_devices)
                self.wireless_section.grid(row=row_idx, column=0, sticky="ew", pady=(0, 4))
                row_idx += 1
            else:
                self.wireless_section.grid_remove()

            # NETWORK section
            if network_enabled:
                self.network_section.update_devices(network_devices)
                self.network_section.grid(row=row_idx, column=0, sticky="ew", pady=(0, 4))
                row_idx += 1
            else:
                self.network_section.grid_remove()

            # CSI section
            if csi_enabled:
                self.csi_section.update_devices(csi_cameras)
                self.csi_section.grid(row=row_idx, column=0, sticky="ew")
            else:
                self.csi_section.grid_remove()
        else:
            self.internal_section.grid_remove()
            self.usb_section.grid_remove()
            self.wireless_section.grid_remove()
            self.network_section.grid_remove()
            self.csi_section.grid_remove()
            self.empty_label.grid(row=0, column=0, pady=20)
            return

        total_devices = (
            len(all_usb_devices) + len(wireless_devices) + len(network_devices)
            + len(internal_devices) + len(csi_cameras)
        )
        logger.debug(
            "Updated devices panel: %d internal, %d USB, %d wireless, %d network, %d CSI, %d total",
            len(internal_devices), len(all_usb_devices), len(wireless_devices),
            len(network_devices), len(csi_cameras), total_devices
        )

    def set_device_connected(self, device_id: str, connected: bool) -> None:
        """Set device connection state (called by callback).

        This searches all sections for the device.
        """
        logger.info("set_device_connected: device=%s connected=%s", device_id, connected)
        if self.internal_section.set_device_connected(device_id, connected):
            logger.info("  -> found in internal_section")
            return
        if self.usb_section.set_device_connected(device_id, connected):
            logger.info("  -> found in usb_section")
            return
        if self.wireless_section.set_device_connected(device_id, connected):
            logger.info("  -> found in wireless_section")
            return
        if self.network_section.set_device_connected(device_id, connected):
            logger.info("  -> found in network_section")
            return
        if self.csi_section.set_device_connected(device_id, connected):
            logger.info("  -> found in csi_section")
            return
        logger.warning("  -> device NOT FOUND in any section!")
