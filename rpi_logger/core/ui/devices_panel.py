"""
Devices panel for main window.

Displays discovered devices in sections:
- INTERNAL: Software-only modules (Notes, etc.) - always available
- USB: Direct USB-connected devices
- WIRELESS: Devices connected via XBee dongles
- NETWORK: Network-discovered devices (eye trackers via mDNS)
- AUDIO: Audio input devices (microphones)
- CAMERA: USB cameras and Pi CSI cameras

Each device is shown as a single-line tile with:
- Round toggle button (green when on, dark when off)
- Device name
- Connect/Disconnect button
- Show/Hide button
"""

import tkinter as tk
from tkinter import ttk
from typing import Callable, Dict, List, Optional

from rpi_logger.core.logging_utils import get_module_logger
from ..devices import DeviceInfo, XBeeDongleInfo, ConnectionState
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

    Layout: [Round Toggle] [Device Name] [Connect/Disconnect Button] [Show/Hide Button]

    Two Independent States:
    - Connected: Device is connected and module is running (green dot, "Disconnect" button)
    - Window Visible: Module window is shown ("Hide" button) vs hidden ("Show" button)

    Behavior:
    - Dot and Connect button: Toggle connection state
    - Show button when disconnected: Connects first, then shows window
    - Show button when connected: Just shows window
    - Hide button or window X: Just hides window, keeps module running
    - Disconnect: Stops module (window goes away too)
    """

    def __init__(
        self,
        parent,
        device: DeviceInfo,
        on_connect_change: Callable[[str, bool], None],
        on_visibility_change: Callable[[str, bool], None],
    ):
        super().__init__(parent, style='Inframe.TFrame')
        self.device = device
        self._on_connect_change = on_connect_change
        self._on_visibility_change = on_visibility_change
        self._is_connected = device.state == ConnectionState.CONNECTED
        self._is_visible = False  # Window visibility, updated via callback

        self.columnconfigure(1, weight=1)  # Device name expands

        # Round toggle button (column 0) - reflects connection state
        self.toggle_btn = RoundToggle(
            self,
            size=20,
            command=self._on_toggle_click,
            active=self._is_connected
        )
        self.toggle_btn.grid(row=0, column=0, padx=(4, 10), pady=4)

        # Device name (column 1)
        self.name_label = ttk.Label(
            self,
            text=device.display_name,
            style='Inframe.TLabel'
        )
        self.name_label.grid(row=0, column=1, sticky="w", pady=4)

        # Connect/Disconnect button (column 2)
        self.connect_btn = RoundedButton(
            self,
            text="Disconnect" if self._is_connected else "Connect",
            command=self._on_connect_click,
            width=80,
            height=24,
            corner_radius=6,
            style='default',
            bg=Colors.BG_FRAME
        )
        self.connect_btn.grid(row=0, column=2, padx=(8, 4), pady=4)

        # Show/Hide button (column 3)
        self.show_btn = RoundedButton(
            self,
            text="Hide" if self._is_visible else "Show",
            command=self._on_show_click,
            width=80,
            height=24,
            corner_radius=6,
            style='default',
            bg=Colors.BG_FRAME
        )
        self.show_btn.grid(row=0, column=3, padx=(0, 4), pady=4)

    def _on_toggle_click(self, active: bool) -> None:
        """Handle dot toggle click - toggle connection."""
        # Revert visual state until confirmed by callback
        self.toggle_btn.set_active(self._is_connected)
        self._on_connect_change(self.device.device_id, active)

    def _on_connect_click(self) -> None:
        """Handle connect/disconnect button click."""
        self._on_connect_change(self.device.device_id, not self._is_connected)

    def _on_show_click(self) -> None:
        """Handle show/hide button click."""
        self._on_visibility_change(self.device.device_id, not self._is_visible)

    def set_connected(self, connected: bool) -> None:
        """Set the connection state (called by callback)."""
        self._is_connected = connected
        self.toggle_btn.set_active(connected)
        self.connect_btn.configure(text="Disconnect" if connected else "Connect")
        # If disconnected, window is also not visible
        if not connected:
            self._is_visible = False
            self.show_btn.configure(text="Show")

    def set_visible(self, visible: bool) -> None:
        """Set the window visibility state (called by callback)."""
        self._is_visible = visible
        self.show_btn.configure(text="Hide" if visible else "Show")

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
        on_visibility_change: Callable[[str, bool], None],
    ):
        super().__init__(parent, style='Inframe.TFrame')
        self._title = title
        self._on_connect_change = on_connect_change
        self._on_visibility_change = on_visibility_change
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
            font=('TkDefaultFont', 9, 'bold')
        )
        self.header_label.grid(row=0, column=0, sticky="w", padx=8, pady=4)

        # Content frame for device rows
        self.content = ttk.Frame(self, style='Inframe.TFrame')
        self.content.grid(row=1, column=0, sticky="ew", padx=4, pady=(0, 4))
        self.content.columnconfigure(0, weight=1)

        # Empty state label
        self.empty_label = ttk.Label(
            self.content,
            text="No devices",
            style='Inframe.Secondary.TLabel',
            font=('TkDefaultFont', 9, 'italic')
        )
        self.empty_label.grid(row=0, column=0, sticky="w", padx=8, pady=4)

    def update_devices(self, devices: List[DeviceInfo]) -> None:
        """Update the section with a list of devices."""
        if not devices:
            # Show empty state
            self.empty_label.grid(row=0, column=0, sticky="w", padx=8, pady=4)
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
                    self._on_visibility_change,
                )
                row.grid(row=idx, column=0, sticky="ew", padx=4, pady=1)
                self._device_rows[device.device_id] = row

    def set_device_connected(self, device_id: str, connected: bool) -> bool:
        """Set device connection state. Returns True if device was found."""
        if device_id in self._device_rows:
            self._device_rows[device_id].set_connected(connected)
            return True
        return False

    def set_device_visible(self, device_id: str, visible: bool) -> bool:
        """Set device window visibility. Returns True if device was found."""
        if device_id in self._device_rows:
            self._device_rows[device_id].set_visible(visible)
            return True
        return False


class USBDevicesPanel(ttk.LabelFrame):
    """Panel showing all discovered devices organized by connection type.

    Two Independent Callbacks:
    - on_connect_change: Called when connection state should change (dot, Connect button)
    - on_visibility_change: Called when window visibility should change (Show/Hide button)
    """

    def __init__(
        self,
        parent,
        on_connect_change: Callable[[str, bool], None],
        on_visibility_change: Callable[[str, bool], None],
    ):
        super().__init__(parent, text="Devices")
        self._on_connect_change = on_connect_change
        self._on_visibility_change = on_visibility_change

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

        # Create sections - INTERNAL first since it's always available
        self.internal_section = DeviceSection(
            self.scrollable_frame,
            "INTERNAL",
            self._on_connect_change,
            self._on_visibility_change,
        )
        self.internal_section.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        self.usb_section = DeviceSection(
            self.scrollable_frame,
            "USB",
            self._on_connect_change,
            self._on_visibility_change,
        )
        self.usb_section.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        self.wireless_section = DeviceSection(
            self.scrollable_frame,
            "WIRELESS",
            self._on_connect_change,
            self._on_visibility_change,
        )
        self.wireless_section.grid(row=2, column=0, sticky="ew", pady=(0, 8))

        self.network_section = DeviceSection(
            self.scrollable_frame,
            "NETWORK",
            self._on_connect_change,
            self._on_visibility_change,
        )
        self.network_section.grid(row=3, column=0, sticky="ew", pady=(0, 8))

        self.audio_section = DeviceSection(
            self.scrollable_frame,
            "AUDIO",
            self._on_connect_change,
            self._on_visibility_change,
        )
        self.audio_section.grid(row=4, column=0, sticky="ew", pady=(0, 8))

        self.camera_section = DeviceSection(
            self.scrollable_frame,
            "CAMERA",
            self._on_connect_change,
            self._on_visibility_change,
        )
        self.camera_section.grid(row=5, column=0, sticky="ew")

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
    ) -> None:
        """Update the device list display.

        Args:
            devices: List of USB-connected devices (non-wireless)
            dongles: List of XBee dongles with their child wireless devices
            network_devices: List of network-discovered devices (e.g., eye trackers)
            audio_devices: List of audio devices (e.g., USB microphones)
            internal_devices: List of internal/virtual devices (e.g., Notes)
            camera_devices: List of camera devices (USB and Pi cameras)
        """
        if network_devices is None:
            network_devices = []
        if audio_devices is None:
            audio_devices = []
        if internal_devices is None:
            internal_devices = []
        if camera_devices is None:
            camera_devices = []

        # Collect all wireless devices from dongles
        wireless_devices = []
        for dongle in dongles:
            wireless_devices.extend(dongle.child_devices.values())

        has_any = (
            bool(devices) or bool(wireless_devices) or bool(network_devices)
            or bool(audio_devices) or bool(internal_devices) or bool(camera_devices)
        )

        # Show/hide sections based on content
        if has_any:
            self.empty_label.grid_remove()
            self.internal_section.grid(row=0, column=0, sticky="ew", pady=(0, 8))
            self.usb_section.grid(row=1, column=0, sticky="ew", pady=(0, 8))
            self.wireless_section.grid(row=2, column=0, sticky="ew", pady=(0, 8))
            self.network_section.grid(row=3, column=0, sticky="ew", pady=(0, 8))
            self.audio_section.grid(row=4, column=0, sticky="ew", pady=(0, 8))
            self.camera_section.grid(row=5, column=0, sticky="ew")
        else:
            self.internal_section.grid_remove()
            self.usb_section.grid_remove()
            self.wireless_section.grid_remove()
            self.network_section.grid_remove()
            self.audio_section.grid_remove()
            self.camera_section.grid_remove()
            self.empty_label.grid(row=0, column=0, pady=20)
            return

        # Update sections
        self.internal_section.update_devices(internal_devices)
        self.usb_section.update_devices(devices)
        self.wireless_section.update_devices(wireless_devices)
        self.network_section.update_devices(network_devices)
        self.audio_section.update_devices(audio_devices)
        self.camera_section.update_devices(camera_devices)

        total_devices = (
            len(devices) + len(wireless_devices) + len(network_devices)
            + len(audio_devices) + len(internal_devices) + len(camera_devices)
        )
        logger.debug(
            "Updated devices panel: %d internal, %d USB, %d wireless, %d network, %d audio, %d camera, %d total",
            len(internal_devices), len(devices), len(wireless_devices),
            len(network_devices), len(audio_devices), len(camera_devices), total_devices
        )

    def set_device_connected(self, device_id: str, connected: bool) -> None:
        """Set device connection state (called by callback).

        This searches all sections for the device.
        """
        if self.internal_section.set_device_connected(device_id, connected):
            return
        if self.usb_section.set_device_connected(device_id, connected):
            return
        if self.wireless_section.set_device_connected(device_id, connected):
            return
        if self.network_section.set_device_connected(device_id, connected):
            return
        if self.audio_section.set_device_connected(device_id, connected):
            return
        self.camera_section.set_device_connected(device_id, connected)

    def set_device_visible(self, device_id: str, visible: bool) -> None:
        """Set device window visibility (called by callback).

        This searches all sections for the device.
        """
        if self.internal_section.set_device_visible(device_id, visible):
            return
        if self.usb_section.set_device_visible(device_id, visible):
            return
        if self.wireless_section.set_device_visible(device_id, visible):
            return
        if self.network_section.set_device_visible(device_id, visible):
            return
        if self.audio_section.set_device_visible(device_id, visible):
            return
        self.camera_section.set_device_visible(device_id, visible)
