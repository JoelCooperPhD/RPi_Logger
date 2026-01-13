"""
Devices Panel v2 - Clean UI component for device display.

This component renders the Devices panel based on data from
DeviceUIController. It has no domain knowledge - it just renders
DeviceSectionData and wires callbacks.

Structure:
    ┌─ Devices ─────────────────────┐
    │ ▸ VOG                         │
    │   ● VOG (USB)      <- click   │
    │   ○ VOG (XBee)     <- click   │
    │ ▸ DRT                         │
    │   ○ DRT (USB)      <- click   │
    │ ...                           │
    └───────────────────────────────┘

Device cards are clickable - click anywhere on the card to
connect/disconnect. Green indicator shows connected status.
"""

import tkinter as tk
from tkinter import ttk

from rpi_logger.core.logging_utils import get_module_logger
from .device_controller import DeviceUIController, DeviceSectionData, DeviceRowData
from .theme.colors import Colors

logger = get_module_logger("DevicesPanel")


class StatusIndicator(tk.Canvas):
    """A round status indicator: green=connected, yellow=connecting, dark=disconnected."""

    def __init__(
        self,
        parent,
        size: int = 16,
        connected: bool = False,
        connecting: bool = False,
        bg_color: str = Colors.BG_FRAME,
    ):
        super().__init__(
            parent,
            width=size,
            height=size,
            highlightthickness=0,
            bg=bg_color,
        )
        self._size = size
        self._connected = connected
        self._connecting = connecting
        self._bg_color = bg_color
        self._draw()

    def _draw(self) -> None:
        """Draw the status indicator."""
        self.delete("all")
        padding = 2

        if self._connected:
            # Green - connected and ready
            self.create_oval(
                padding, padding,
                self._size - padding, self._size - padding,
                fill=Colors.STATUS_CONNECTED,
                outline=Colors.STATUS_CONNECTED
            )
        elif self._connecting:
            # Yellow/orange - connecting, waiting for acknowledgement
            self.create_oval(
                padding, padding,
                self._size - padding, self._size - padding,
                fill=Colors.STATUS_CONNECTING,
                outline=Colors.STATUS_CONNECTING
            )
        else:
            # Dark - disconnected
            self.create_oval(
                padding, padding,
                self._size - padding, self._size - padding,
                fill=Colors.BG_DARK,
                outline=Colors.BORDER,
                width=2
            )

    def set_state(self, connected: bool, connecting: bool) -> None:
        """Set the indicator state."""
        if self._connected != connected or self._connecting != connecting:
            self._connected = connected
            self._connecting = connecting
            self._draw()

    def set_bg(self, bg_color: str) -> None:
        """Update background color for hover effects."""
        if self._bg_color != bg_color:
            self._bg_color = bg_color
            self.configure(bg=bg_color)
            self._draw()


class DeviceRow(tk.Frame):
    """
    A clickable device card in the panel.

    Layout: [Status Indicator] [Device Name]
    Click anywhere on the card to connect/disconnect.
    """

    def __init__(self, parent, data: DeviceRowData):
        super().__init__(parent, bg=Colors.BG_FRAME, cursor="hand2")
        self._data = data
        self._hovering = False

        self.columnconfigure(1, weight=1)

        # Status indicator (not clickable on its own)
        self._indicator = StatusIndicator(
            self,
            size=16,
            connected=data.connected,
            connecting=data.connecting,
            bg_color=Colors.BG_FRAME,
        )
        self._indicator.grid(row=0, column=0, padx=(4, 6), pady=4)

        # Device name
        self._name_label = tk.Label(
            self,
            text=data.display_name,
            bg=Colors.BG_FRAME,
            fg=Colors.FG_PRIMARY,
            anchor="w",
        )
        self._name_label.grid(row=0, column=1, sticky="ew", pady=4, padx=(0, 4))

        # Bind click and hover events to all widgets
        self._bind_events()

    def _bind_events(self) -> None:
        """Bind click and hover events to the card and all children."""
        widgets = [self, self._indicator, self._name_label]
        for widget in widgets:
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)
            widget.bind("<Button-1>", self._on_click)

    def _on_enter(self, event) -> None:
        """Handle mouse enter - show hover state."""
        self._hovering = True
        self._update_hover_state()

    def _on_leave(self, event) -> None:
        """Handle mouse leave - reset hover state."""
        self._hovering = False
        self._update_hover_state()

    def _update_hover_state(self) -> None:
        """Update visual state based on hover."""
        bg = Colors.BG_DARKER if self._hovering else Colors.BG_FRAME
        self.configure(bg=bg)
        self._name_label.configure(bg=bg)
        self._indicator.set_bg(bg)

    def _on_click(self, event) -> None:
        """Handle click - toggle connection.

        If connected or connecting (green or yellow), clicking disconnects.
        If disconnected (dark), clicking connects.
        """
        # If already connected OR connecting, disconnect
        if self._data.connected or self._data.connecting:
            self._data.on_toggle_connect(False)
        else:
            self._data.on_toggle_connect(True)

    def update_data(self, data: DeviceRowData) -> None:
        """Update the row with new data."""
        self._data = data
        self._indicator.set_state(data.connected, data.connecting)
        self._name_label.configure(text=data.display_name)


class XBeeBanner(tk.Frame):
    """
    Banner showing wireless bridge (XBee dongle) connection status.

    Appears at the top of the devices panel when an XBee coordinator
    is connected. Styled similar to section headers but with muted blue.
    Includes a rescan button on the right side.
    """

    # Muted/desaturated blue for the banner background
    BANNER_BG = "#2d4a5e"

    def __init__(self, parent, on_rescan: callable = None):
        super().__init__(parent, bg=self.BANNER_BG)
        self.columnconfigure(0, weight=1)

        self._on_rescan = on_rescan
        self._device_count = 0
        self._scanning = False

        self._label = tk.Label(
            self,
            text="Wireless Devices: 0",
            bg=self.BANNER_BG,
            fg=Colors.FG_PRIMARY,
            font=('TkDefaultFont', 8, 'bold'),
            anchor="w",
        )
        self._label.grid(row=0, column=0, sticky="w", padx=6, pady=2)

        # Rescan button - small rounded button on the right
        from .theme.widgets import RoundedButton
        self._rescan_btn = RoundedButton(
            self,
            text="Rescan",
            command=self._handle_rescan,
            width=60,
            height=20,
            corner_radius=4,
            style='default',
            bg=self.BANNER_BG,  # Match parent background
        )
        self._rescan_btn.grid(row=0, column=1, padx=(0, 4), pady=2)

        # Start hidden
        self._visible = False

    def _handle_rescan(self) -> None:
        """Handle rescan button click."""
        if self._on_rescan:
            self._on_rescan()

    def set_rescan_callback(self, callback: callable) -> None:
        """Set the rescan callback."""
        self._on_rescan = callback

    def set_device_count(self, count: int) -> None:
        """Update the wireless device count displayed."""
        self._device_count = count
        if not self._scanning:
            self._label.configure(text=f"Wireless Devices: {count}")

    def set_scanning(self, scanning: bool) -> None:
        """Update the scanning state."""
        self._scanning = scanning
        if scanning:
            self._label.configure(text="Wireless Devices: Scanning...")
        else:
            self._label.configure(text=f"Wireless Devices: {self._device_count}")

    def set_visible(self, visible: bool) -> None:
        """Show or hide the banner."""
        self._visible = visible
        # Actual grid management is done by parent panel

    @property
    def is_visible(self) -> bool:
        """Check if banner should be visible."""
        return self._visible

    def set_rescan_enabled(self, enabled: bool) -> None:
        """Enable or disable the rescan button.

        Disabling prevents rescans during active sessions to avoid
        disrupting wireless device communications.
        """
        self._rescan_btn.set_enabled(enabled)


class DeviceSection(ttk.Frame):
    """
    A section containing devices of a single family.

    Has a header banner and device rows.
    """

    def __init__(self, parent, label: str):
        super().__init__(parent, style='Inframe.TFrame')
        self._label = label
        self._rows: dict[str, DeviceRow] = {}
        self._has_devices = False

        self.columnconfigure(0, weight=1)

        # Header
        self._header = ttk.Frame(self, style='SectionHeader.TFrame')
        self._header.grid(row=0, column=0, sticky="ew")
        self._header.columnconfigure(0, weight=1)

        # Header label shows "VOG" or "VOG: No Devices"
        self._header_label = ttk.Label(
            self._header,
            text=f"{label}: No Devices",
            style='SectionHeader.TLabel',
            font=('TkDefaultFont', 8, 'bold')
        )
        self._header_label.grid(row=0, column=0, sticky="w", padx=6, pady=2)

        # Content frame for device rows
        self._content = ttk.Frame(self, style='Inframe.TFrame')
        self._content.grid(row=1, column=0, sticky="ew", padx=2, pady=(0, 2))
        self._content.columnconfigure(0, weight=1)

    def update_devices(self, devices: list[DeviceRowData]) -> None:
        """Update the section with device data."""
        if not devices:
            # Show "VOG: No Devices" in header
            if self._has_devices:
                self._header_label.configure(text=f"{self._label}: No Devices")
                self._has_devices = False
            for row in self._rows.values():
                row.destroy()
            self._rows.clear()
            return

        # Show just "VOG" when devices exist
        if not self._has_devices:
            self._header_label.configure(text=self._label)
            self._has_devices = True

        # Track current device IDs
        current_ids = {d.device_id for d in devices}

        # Remove rows for devices that no longer exist
        for device_id in list(self._rows.keys()):
            if device_id not in current_ids:
                self._rows[device_id].destroy()
                del self._rows[device_id]

        # Update or create rows
        for idx, data in enumerate(devices):
            if data.device_id in self._rows:
                self._rows[data.device_id].update_data(data)
                self._rows[data.device_id].grid(
                    row=idx, column=0, sticky="ew", padx=4, pady=1
                )
            else:
                row = DeviceRow(self._content, data)
                row.grid(row=idx, column=0, sticky="ew", padx=4, pady=1)
                self._rows[data.device_id] = row


class DevicesPanel(ttk.LabelFrame):
    """
    Panel showing devices organized by family.

    This component:
    - Gets data from DeviceUIController
    - Renders sections and device rows
    - Wires callbacks for connect/disconnect
    - Re-renders when controller notifies of changes

    No domain logic - just UI rendering.
    """

    def __init__(self, parent, controller: DeviceUIController):
        super().__init__(parent, text="Devices")
        self._controller = controller
        self._sections: dict[str, DeviceSection] = {}

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        # Container with scrolling
        self._container = ttk.Frame(self, style='Inframe.TFrame')
        self._container.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        self._container.columnconfigure(0, weight=1)
        self._container.rowconfigure(0, weight=1)

        # Canvas and scrollbar
        self._canvas = tk.Canvas(
            self._container,
            height=150,
            highlightthickness=0,
            bd=0,
            bg=Colors.BG_FRAME
        )

        self._scrollbar = ttk.Scrollbar(
            self._container,
            orient="vertical",
            command=self._canvas.yview
        )

        self._scrollable = ttk.Frame(self._canvas, style='Inframe.TFrame')
        self._scrollable.columnconfigure(0, weight=1)

        self._scrollable.bind(
            "<Configure>",
            self._on_scrollable_configure
        )

        self._canvas_window = self._canvas.create_window(
            (0, 0),
            window=self._scrollable,
            anchor="nw"
        )
        self._canvas.configure(yscrollcommand=self._scrollbar.set)
        self._canvas.bind("<Configure>", self._on_canvas_configure)

        self._canvas.grid(row=0, column=0, sticky="nsew")
        self._scrollbar.grid(row=0, column=1, sticky="ns")

        # Mouse wheel scrolling
        self._canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self._canvas.bind_all("<Button-4>", self._on_mousewheel)
        self._canvas.bind_all("<Button-5>", self._on_mousewheel)

        # XBee dongle banner (shown when XBee coordinator connected)
        self._xbee_banner = XBeeBanner(
            self._scrollable,
            on_rescan=self._handle_xbee_rescan
        )

        # Empty state label
        self._empty_label = ttk.Label(
            self._scrollable,
            text="No devices detected.\nConnect a supported device.",
            style='Inframe.Secondary.TLabel',
            justify="center",
        )

        # Register for updates
        controller.add_ui_observer(self._on_data_changed)

        # Initial build
        self._build()

    def _on_canvas_configure(self, event) -> None:
        """Update scrollable frame width when canvas resizes."""
        self._canvas.itemconfig(self._canvas_window, width=event.width)
        # Also update scroll region to ensure content stays at top
        self._update_scroll_region()

    def _on_scrollable_configure(self, event) -> None:
        """Update scroll region when scrollable frame content changes."""
        self._update_scroll_region()

    def _update_scroll_region(self) -> None:
        """Update scroll region to fit content while keeping it anchored to top.

        When content is shorter than the canvas viewport, we set the scroll
        region height to match the canvas height. This prevents the content
        from floating or centering within the viewport.
        """
        bbox = self._canvas.bbox("all")
        if bbox:
            x1, y1, x2, y2 = bbox
            canvas_height = self._canvas.winfo_height()
            # Scroll region should be at least as tall as the canvas
            scroll_height = max(y2, canvas_height)
            self._canvas.configure(scrollregion=(0, 0, x2, scroll_height))

    def _on_mousewheel(self, event) -> None:
        """Handle mouse wheel scrolling."""
        if event.num == 4 or event.delta > 0:
            self._canvas.yview_scroll(-1, "units")
        elif event.num == 5 or event.delta < 0:
            self._canvas.yview_scroll(1, "units")

    def _build(self) -> None:
        """Build the panel from controller data."""
        sections_data = self._controller.get_panel_data()

        # Update with current data (sections created on-demand)
        self._update_sections(sections_data)

        # Ensure canvas starts at top
        self._canvas.yview_moveto(0)

    def _update_sections(self, sections_data: list[DeviceSectionData]) -> None:
        """Update all sections with new data.

        Sections are created on-demand when they become visible for the first
        time, rather than pre-creating all sections upfront. This ensures only
        visible sections exist as children of the scrollable frame, preventing
        layout issues from invisible widgets.
        """
        has_any_visible = any(s.visible for s in sections_data)

        # Start row index - XBee banner takes row 0 if visible
        row_idx = 0

        # XBee banner always first if visible
        if self._xbee_banner.is_visible:
            self._xbee_banner.grid(row=row_idx, column=0, sticky="ew", pady=(0, 4))
            row_idx += 1
        else:
            self._xbee_banner.grid_remove()

        if has_any_visible:
            self._empty_label.grid_remove()

            for section_data in sections_data:
                if section_data.visible:
                    # Create section on-demand if it doesn't exist
                    section = self._sections.get(section_data.label)
                    if not section:
                        section = DeviceSection(self._scrollable, section_data.label)
                        self._sections[section_data.label] = section

                    section.update_devices(section_data.devices)
                    section.grid(row=row_idx, column=0, sticky="ew", pady=(0, 4))
                    row_idx += 1
                else:
                    # Remove from grid if exists but not visible
                    section = self._sections.get(section_data.label)
                    if section:
                        section.grid_remove()
        else:
            for section in self._sections.values():
                section.grid_remove()
            # Show empty label only if XBee banner also not visible
            if not self._xbee_banner.is_visible:
                self._empty_label.grid(row=row_idx, column=0, pady=20)
            else:
                self._empty_label.grid_remove()

    def _on_data_changed(self) -> None:
        """Called when controller data changes."""
        # Update XBee banner state from controller
        self._xbee_banner.set_visible(self._controller.xbee_dongle_connected)
        self._xbee_banner.set_scanning(self._controller.xbee_scanning)
        self._xbee_banner.set_device_count(self._controller.wireless_device_count)
        # Disable rescan during active sessions to avoid disrupting wireless comms
        self._xbee_banner.set_rescan_enabled(not self._controller.session_active)

        sections_data = self._controller.get_panel_data()
        self._update_sections(sections_data)

    def set_xbee_connected(self, connected: bool) -> None:
        """
        Set XBee dongle connection state.

        Shows or hides the blue "XBee Connected" banner at the top
        of the devices panel.

        Args:
            connected: True if XBee dongle is connected
        """
        self._xbee_banner.set_visible(connected)
        # Trigger re-render to update layout
        self._on_data_changed()

    def _handle_xbee_rescan(self) -> None:
        """Handle XBee rescan button click."""
        logger.info("XBee rescan requested from UI")
        self._controller.request_xbee_rescan()

    def destroy(self) -> None:
        """Clean up the panel."""
        self._controller.remove_ui_observer(self._on_data_changed)
        super().destroy()
