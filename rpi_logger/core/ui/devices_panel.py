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
    """A round status indicator that shows green when connected, dark when disconnected."""

    def __init__(
        self,
        parent,
        size: int = 16,
        active: bool = False,
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
        self._active = active
        self._bg_color = bg_color
        self._draw()

    def _draw(self) -> None:
        """Draw the status indicator."""
        self.delete("all")
        padding = 2

        if self._active:
            self.create_oval(
                padding, padding,
                self._size - padding, self._size - padding,
                fill=Colors.STATUS_CONNECTED,
                outline=Colors.STATUS_CONNECTED
            )
        else:
            self.create_oval(
                padding, padding,
                self._size - padding, self._size - padding,
                fill=Colors.BG_DARK,
                outline=Colors.BORDER,
                width=2
            )

    def set_active(self, active: bool) -> None:
        """Set the indicator state."""
        if self._active != active:
            self._active = active
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
            active=data.connected,
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
        """Handle click - toggle connection."""
        self._data.on_toggle_connect(not self._data.connected)

    def update_data(self, data: DeviceRowData) -> None:
        """Update the row with new data."""
        self._data = data
        self._indicator.set_active(data.connected)
        self._name_label.configure(text=data.display_name)


class DeviceSection(ttk.Frame):
    """
    A section containing devices of a single family.

    Has a header banner and device rows.
    """

    def __init__(self, parent, label: str):
        super().__init__(parent, style='Inframe.TFrame')
        self._label = label
        self._rows: dict[str, DeviceRow] = {}

        self.columnconfigure(0, weight=1)

        # Header
        self._header = ttk.Frame(self, style='SectionHeader.TFrame')
        self._header.grid(row=0, column=0, sticky="ew")
        self._header.columnconfigure(0, weight=1)

        self._header_label = ttk.Label(
            self._header,
            text=label,
            style='SectionHeader.TLabel',
            font=('TkDefaultFont', 8, 'bold')
        )
        self._header_label.grid(row=0, column=0, sticky="w", padx=6, pady=2)

        # Content frame
        self._content = ttk.Frame(self, style='Inframe.TFrame')
        self._content.grid(row=1, column=0, sticky="ew", padx=2, pady=(0, 2))
        self._content.columnconfigure(0, weight=1)

        # Empty state label
        self._empty_label = ttk.Label(
            self._content,
            text="No devices",
            style='Inframe.Secondary.TLabel',
            font=('TkDefaultFont', 8, 'italic')
        )
        self._empty_label.grid(row=0, column=0, sticky="w", padx=6, pady=2)

    def update_devices(self, devices: list[DeviceRowData]) -> None:
        """Update the section with device data."""
        if not devices:
            self._empty_label.grid(row=0, column=0, sticky="w", padx=6, pady=2)
            for row in self._rows.values():
                row.destroy()
            self._rows.clear()
            return

        self._empty_label.grid_remove()

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
            lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all"))
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

    def _on_mousewheel(self, event) -> None:
        """Handle mouse wheel scrolling."""
        if event.num == 4 or event.delta > 0:
            self._canvas.yview_scroll(-1, "units")
        elif event.num == 5 or event.delta < 0:
            self._canvas.yview_scroll(1, "units")

    def _build(self) -> None:
        """Build the panel from controller data."""
        sections_data = self._controller.get_panel_data()

        # Create sections
        for section_data in sections_data:
            section = DeviceSection(self._scrollable, section_data.label)
            self._sections[section_data.label] = section

        # Update with current data
        self._update_sections(sections_data)

    def _update_sections(self, sections_data: list[DeviceSectionData]) -> None:
        """Update all sections with new data."""
        has_any_visible = any(s.visible for s in sections_data)

        if has_any_visible:
            self._empty_label.grid_remove()

            row_idx = 0
            for section_data in sections_data:
                section = self._sections.get(section_data.label)
                if not section:
                    continue

                if section_data.visible:
                    section.update_devices(section_data.devices)
                    section.grid(row=row_idx, column=0, sticky="ew", pady=(0, 4))
                    row_idx += 1
                else:
                    section.grid_remove()
        else:
            for section in self._sections.values():
                section.grid_remove()
            self._empty_label.grid(row=0, column=0, pady=20)

    def _on_data_changed(self) -> None:
        """Called when controller data changes."""
        sections_data = self._controller.get_panel_data()
        self._update_sections(sections_data)

    def destroy(self) -> None:
        """Clean up the panel."""
        self._controller.remove_ui_observer(self._on_data_changed)
        super().destroy()
