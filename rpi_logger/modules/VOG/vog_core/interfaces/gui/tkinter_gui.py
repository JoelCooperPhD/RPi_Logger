"""VOG Tkinter GUI with device tabs, dongle tab, and plotter.

Supports sVOG (wired), wVOG USB (direct USB), and wVOG Wireless (via XBee) devices.
- sVOG: Single peek open/close buttons
- wVOG USB: Dual lens controls (A/B/X) + battery display in device tab
- wVOG Wireless: Dual lens controls, battery/status in XBee dongle tab
"""

import tkinter as tk
from tkinter import ttk, messagebox
from typing import TYPE_CHECKING, Dict, Any, Optional

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.modules.base import TkinterGUIBase

from ...device_types import VOGDeviceType, device_type_to_legacy_string

if TYPE_CHECKING:
    from ...vog_system import VOGSystem


class WirelessDeviceEntry:
    """Entry for a wireless wVOG device displayed in the dongle tab."""

    def __init__(self, device_id: str, parent_frame: tk.Frame):
        self.device_id = device_id
        self.frame = parent_frame
        self.battery_percent: Optional[int] = None
        self.connected: bool = True

        # UI elements (created when build() is called)
        self.row_frame: Optional[ttk.Frame] = None
        self.id_label: Optional[ttk.Label] = None
        self.status_indicator: Optional[tk.Label] = None
        self.battery_label: Optional[ttk.Label] = None

    def build(self, row: int) -> ttk.Frame:
        """Build the entry UI."""
        self.row_frame = ttk.Frame(self.frame)
        self.row_frame.grid(row=row, column=0, sticky='ew', pady=2, padx=5)
        self.row_frame.columnconfigure(1, weight=1)

        # Status indicator (green=connected, gray=disconnected)
        self.status_indicator = tk.Label(
            self.row_frame,
            text="\u25cf",  # Filled circle
            fg='green',
            font=('TkDefaultFont', 10)
        )
        self.status_indicator.grid(row=0, column=0, padx=(0, 5))

        # Device ID
        self.id_label = ttk.Label(
            self.row_frame,
            text=self.device_id,
            font=('TkDefaultFont', 9, 'bold')
        )
        self.id_label.grid(row=0, column=1, sticky='w')

        # Battery percentage
        self.battery_label = ttk.Label(
            self.row_frame,
            text="---%",
            width=6
        )
        self.battery_label.grid(row=0, column=2, padx=(10, 0))

        return self.row_frame

    def update_battery(self, percent: int) -> None:
        """Update the battery display."""
        self.battery_percent = percent
        if self.battery_label:
            self.battery_label.config(text=f"{percent}%")

    def set_connected(self, connected: bool) -> None:
        """Set connected status."""
        self.connected = connected
        if self.status_indicator:
            self.status_indicator.config(fg='green' if connected else 'gray')

    def destroy(self) -> None:
        """Destroy the entry UI."""
        if self.row_frame:
            self.row_frame.destroy()
            self.row_frame = None


class DongleTab:
    """Tab for XBee dongle status and wireless device management."""

    def __init__(self, parent_frame: tk.Frame):
        self.frame = parent_frame
        self.status_label: Optional[ttk.Label] = None
        self.port_label: Optional[ttk.Label] = None
        self.rtc_sync_button: Optional[ttk.Button] = None
        self.rescan_button: Optional[ttk.Button] = None
        self.devices_frame: Optional[ttk.LabelFrame] = None
        self.devices_container: Optional[ttk.Frame] = None
        self.no_devices_label: Optional[ttk.Label] = None
        self.wireless_devices: Dict[str, WirelessDeviceEntry] = {}

    def build(self) -> ttk.Frame:
        """Build the dongle tab UI."""
        tab_frame = ttk.Frame(self.frame, padding=10)
        tab_frame.columnconfigure(0, weight=1)

        # Dongle Status Section
        status_frame = ttk.LabelFrame(tab_frame, text="XBee Dongle Status", padding=10)
        status_frame.grid(row=0, column=0, sticky='ew', pady=(0, 10))
        status_frame.columnconfigure(1, weight=1)

        ttk.Label(status_frame, text="Status:").grid(row=0, column=0, sticky='w', padx=(0, 10))
        self.status_label = ttk.Label(status_frame, text="Not Connected", foreground='gray')
        self.status_label.grid(row=0, column=1, sticky='w')

        ttk.Label(status_frame, text="Port:").grid(row=1, column=0, sticky='w', padx=(0, 10))
        self.port_label = ttk.Label(status_frame, text="-")
        self.port_label.grid(row=1, column=1, sticky='w')

        # Buttons frame
        btn_frame = ttk.Frame(status_frame)
        btn_frame.grid(row=2, column=0, columnspan=2, pady=(10, 0), sticky='w')

        self.rescan_button = ttk.Button(
            btn_frame,
            text="Rescan Network",
            state='disabled'
        )
        self.rescan_button.pack(side=tk.LEFT, padx=(0, 5))

        self.rtc_sync_button = ttk.Button(
            btn_frame,
            text="Sync RTC on All Devices",
            state='disabled'
        )
        self.rtc_sync_button.pack(side=tk.LEFT)

        # Wireless Devices Section
        self.devices_frame = ttk.LabelFrame(tab_frame, text="Wireless wVOG Devices", padding=10)
        self.devices_frame.grid(row=1, column=0, sticky='nsew', pady=(0, 10))
        self.devices_frame.columnconfigure(0, weight=1)
        tab_frame.rowconfigure(1, weight=1)

        self.devices_container = ttk.Frame(self.devices_frame)
        self.devices_container.grid(row=0, column=0, sticky='nsew')
        self.devices_container.columnconfigure(0, weight=1)

        self.no_devices_label = ttk.Label(
            self.devices_container,
            text="No wireless devices connected",
            foreground='gray'
        )
        self.no_devices_label.grid(row=0, column=0, pady=20)

        return tab_frame

    def update_status(self, connected: bool, port: Optional[str] = None) -> None:
        """Update dongle connection status."""
        if connected:
            self.status_label.config(text="Connected", foreground='green')
            self.port_label.config(text=port or "-")
            self.rescan_button.config(state='normal')
            self.rtc_sync_button.config(state='normal' if self.wireless_devices else 'disabled')
        else:
            self.status_label.config(text="Not Connected", foreground='gray')
            self.port_label.config(text="-")
            self.rescan_button.config(state='disabled')
            self.rtc_sync_button.config(state='disabled')

    def add_device(self, device_id: str) -> None:
        """Add a wireless device to the list."""
        if device_id in self.wireless_devices:
            return

        # Hide "no devices" label
        if self.no_devices_label:
            self.no_devices_label.grid_remove()

        # Create entry
        entry = WirelessDeviceEntry(device_id, self.devices_container)
        row = len(self.wireless_devices)
        entry.build(row)
        self.wireless_devices[device_id] = entry

        # Enable RTC sync button
        if self.rtc_sync_button:
            self.rtc_sync_button.config(state='normal')

    def remove_device(self, device_id: str) -> None:
        """Remove a wireless device from the list."""
        entry = self.wireless_devices.pop(device_id, None)
        if entry:
            entry.destroy()

        # Show "no devices" label if empty
        if not self.wireless_devices and self.no_devices_label:
            self.no_devices_label.grid()

        # Disable RTC sync button if no devices
        if not self.wireless_devices and self.rtc_sync_button:
            self.rtc_sync_button.config(state='disabled')

    def update_device_battery(self, device_id: str, percent: int) -> None:
        """Update battery for a wireless device."""
        entry = self.wireless_devices.get(device_id)
        if entry:
            entry.update_battery(percent)


class VOGDeviceTab:
    """Tab widget for a single VOG device.

    Adapts UI based on device type:
    - sVOG: Single peek open/close buttons
    - wVOG USB: Dual lens controls (A/B/X) + battery display
    - wVOG Wireless: Dual lens controls (battery in dongle tab)
    """

    def __init__(
        self,
        parent: ttk.Frame,
        port: str,
        system: 'VOGSystem',
        device_type: VOGDeviceType = VOGDeviceType.SVOG
    ):
        self.port = port
        self.system = system
        self.device_type = device_type
        self.logger = get_module_logger(f"VOGDeviceTab_{port}")

        self.frame = ttk.Frame(parent)
        self.plotter = None

        # wVOG-specific UI elements
        self._battery_label: Optional[ttk.Label] = None
        self._lens_var: Optional[tk.StringVar] = None

        self._build_ui()

    @property
    def is_wvog(self) -> bool:
        """Check if this is any type of wVOG device."""
        return self.device_type in (VOGDeviceType.WVOG_USB, VOGDeviceType.WVOG_WIRELESS)

    @property
    def is_wireless(self) -> bool:
        """Check if this is a wireless wVOG device."""
        return self.device_type == VOGDeviceType.WVOG_WIRELESS

    def _build_ui(self):
        """Build the device tab UI."""
        # Main container with two columns
        self.frame.columnconfigure(0, weight=1)
        self.frame.columnconfigure(1, weight=2)
        self.frame.rowconfigure(0, weight=1)

        # Left side: controls and results
        control_frame = ttk.LabelFrame(self.frame, text="Controls", padding=10)
        control_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        # Device type indicator
        type_frame = ttk.Frame(control_frame)
        type_frame.pack(fill=tk.X, pady=2)
        type_label = self.device_type.value
        ttk.Label(type_frame, text=f"Device: {type_label}", font=('TkDefaultFont', 9, 'bold')).pack(side=tk.LEFT)

        # Build appropriate controls based on device type
        if self.is_wvog:
            self._build_wvog_controls(control_frame)
        else:
            self._build_svog_controls(control_frame)

        # Configure button (common to both)
        config_frame = ttk.Frame(control_frame)
        config_frame.pack(fill=tk.X, pady=5)
        self.config_btn = ttk.Button(
            config_frame,
            text="Configure",
            command=self._on_configure
        )
        self.config_btn.pack(side=tk.LEFT, padx=2)

        # Results display
        results_frame = ttk.LabelFrame(control_frame, text="Last Trial", padding=5)
        results_frame.pack(fill=tk.BOTH, expand=True, pady=10)

        # Trial number
        row = 0
        ttk.Label(results_frame, text="Trial:").grid(row=row, column=0, sticky="w", pady=2)
        self.trial_var = tk.StringVar(value="-")
        ttk.Label(results_frame, textvariable=self.trial_var).grid(row=row, column=1, sticky="w", pady=2)

        # Shutter open time
        row += 1
        ttk.Label(results_frame, text="Open (ms):").grid(row=row, column=0, sticky="w", pady=2)
        self.open_var = tk.StringVar(value="-")
        ttk.Label(results_frame, textvariable=self.open_var).grid(row=row, column=1, sticky="w", pady=2)

        # Shutter closed time
        row += 1
        ttk.Label(results_frame, text="Closed (ms):").grid(row=row, column=0, sticky="w", pady=2)
        self.closed_var = tk.StringVar(value="-")
        ttk.Label(results_frame, textvariable=self.closed_var).grid(row=row, column=1, sticky="w", pady=2)

        # wVOG-specific results
        if self.is_wvog:
            # Total time
            row += 1
            ttk.Label(results_frame, text="Total (ms):").grid(row=row, column=0, sticky="w", pady=2)
            self.total_var = tk.StringVar(value="-")
            ttk.Label(results_frame, textvariable=self.total_var).grid(row=row, column=1, sticky="w", pady=2)

            # Lens
            row += 1
            ttk.Label(results_frame, text="Lens:").grid(row=row, column=0, sticky="w", pady=2)
            self.lens_result_var = tk.StringVar(value="-")
            ttk.Label(results_frame, textvariable=self.lens_result_var).grid(row=row, column=1, sticky="w", pady=2)

        # Right side: plotter
        plot_frame = ttk.LabelFrame(self.frame, text="Shutter Timeline", padding=5)
        plot_frame.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
        plot_frame.columnconfigure(0, weight=1)
        plot_frame.rowconfigure(0, weight=1)

        # Create plotter
        try:
            from .vog_plotter import VOGPlotter
            self.plotter = VOGPlotter(plot_frame)
            self.plotter.add_device(self.port)
        except ImportError as e:
            self.logger.warning("Could not create plotter: %s", e)
            ttk.Label(plot_frame, text="Plotter unavailable").pack(expand=True)

    def _build_svog_controls(self, parent: ttk.Frame):
        """Build sVOG-specific controls (simple peek open/close)."""
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill=tk.X, pady=5)

        self.peek_open_btn = ttk.Button(
            btn_frame,
            text="Peek Open",
            command=self._on_peek_open
        )
        self.peek_open_btn.pack(side=tk.LEFT, padx=2)

        self.peek_close_btn = ttk.Button(
            btn_frame,
            text="Peek Close",
            command=self._on_peek_close
        )
        self.peek_close_btn.pack(side=tk.LEFT, padx=2)

    def _build_wvog_controls(self, parent: ttk.Frame):
        """Build wVOG-specific controls (dual lens + battery for USB wVOG)."""
        # Battery display - only for USB wVOG (wireless shows in dongle tab)
        if self.device_type == VOGDeviceType.WVOG_USB:
            battery_frame = ttk.Frame(parent)
            battery_frame.pack(fill=tk.X, pady=2)
            ttk.Label(battery_frame, text="Battery:").pack(side=tk.LEFT)
            self._battery_label = ttk.Label(battery_frame, text="---%")
            self._battery_label.pack(side=tk.LEFT, padx=5)

        # Lens selector
        lens_frame = ttk.LabelFrame(parent, text="Lens Control", padding=5)
        lens_frame.pack(fill=tk.X, pady=5)

        self._lens_var = tk.StringVar(value="x")
        lens_select_frame = ttk.Frame(lens_frame)
        lens_select_frame.pack(fill=tk.X, pady=2)

        ttk.Radiobutton(lens_select_frame, text="Both (X)", variable=self._lens_var, value="x").pack(side=tk.LEFT)
        ttk.Radiobutton(lens_select_frame, text="Left (A)", variable=self._lens_var, value="a").pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(lens_select_frame, text="Right (B)", variable=self._lens_var, value="b").pack(side=tk.LEFT)

        # Open/Close buttons for selected lens
        btn_frame = ttk.Frame(lens_frame)
        btn_frame.pack(fill=tk.X, pady=5)

        self.peek_open_btn = ttk.Button(
            btn_frame,
            text="Open",
            command=self._on_peek_open
        )
        self.peek_open_btn.pack(side=tk.LEFT, padx=2)

        self.peek_close_btn = ttk.Button(
            btn_frame,
            text="Close",
            command=self._on_peek_close
        )
        self.peek_close_btn.pack(side=tk.LEFT, padx=2)

        # Quick buttons for both lenses
        quick_frame = ttk.Frame(lens_frame)
        quick_frame.pack(fill=tk.X, pady=2)

        ttk.Button(
            quick_frame,
            text="Open Both",
            command=lambda: self._on_peek_open_lens('x')
        ).pack(side=tk.LEFT, padx=2)

        ttk.Button(
            quick_frame,
            text="Close Both",
            command=lambda: self._on_peek_close_lens('x')
        ).pack(side=tk.LEFT, padx=2)

    def _on_peek_open(self):
        """Handle peek open button."""
        lens = self._lens_var.get() if self._lens_var else 'x'
        self._on_peek_open_lens(lens)

    def _on_peek_close(self):
        """Handle peek close button."""
        lens = self._lens_var.get() if self._lens_var else 'x'
        self._on_peek_close_lens(lens)

    def _on_peek_open_lens(self, lens: str):
        """Handle peek open for specific lens."""
        if self.system:
            handler = self.system.get_device_handler(self.port)
            if handler:
                import asyncio
                asyncio.create_task(handler.peek_open(lens))

    def _on_peek_close_lens(self, lens: str):
        """Handle peek close for specific lens."""
        if self.system:
            handler = self.system.get_device_handler(self.port)
            if handler:
                import asyncio
                asyncio.create_task(handler.peek_close(lens))

    def _on_configure(self):
        """Handle configure button."""
        from .config_window import VOGConfigWindow
        # Pass legacy string type for backward compatibility
        legacy_type = device_type_to_legacy_string(self.device_type)
        VOGConfigWindow(self.frame.winfo_toplevel(), self.port, self.system, legacy_type)

    def update_data(self, data: Dict[str, Any]):
        """Update display with trial data."""
        self.trial_var.set(str(data.get('trial_number', '-')))
        self.open_var.set(str(data.get('shutter_open', '-')))
        self.closed_var.set(str(data.get('shutter_closed', '-')))

        # wVOG-specific data
        if self.is_wvog:
            if hasattr(self, 'total_var'):
                self.total_var.set(str(data.get('shutter_total', '-')))
            if hasattr(self, 'lens_result_var'):
                self.lens_result_var.set(str(data.get('lens', '-')))

        # Update plotter
        if self.plotter:
            shutter_open = data.get('shutter_open', 0)
            shutter_closed = data.get('shutter_closed', 0)
            self.plotter.update_trial_data(self.port, shutter_open, shutter_closed)

    def update_stimulus_state(self, state: int):
        """Update plotter with stimulus state."""
        if self.plotter:
            self.plotter.update_shutter_state(self.port, state == 1)

    def update_battery(self, percent: int):
        """Update battery display (USB wVOG only)."""
        if self._battery_label:
            self._battery_label.config(text=f"{percent}%")

    def cleanup(self):
        """Clean up resources."""
        if self.plotter:
            self.plotter.remove_device(self.port)


class VOGTkinterGUI(TkinterGUIBase):
    """Main VOG GUI window with device tabs and XBee dongle tab."""

    def __init__(self, system: 'VOGSystem', args):
        self.system = system
        self.args = args
        self.logger = get_module_logger("VOGTkinterGUI")

        # Device tabs dictionary
        self.device_tabs: Dict[str, VOGDeviceTab] = {}

        # Dongle tab (created when XBee is detected)
        self.dongle_tab: Optional[DongleTab] = None
        self._dongle_tab_created = False

        # Async bridge for running coroutines from Tk thread
        self.async_bridge = None

        # Initialize base class using the standard framework method
        self.initialize_gui_framework(
            title="VOG - Visual Occlusion Glasses",
            default_width=800,
            default_height=400,
        )

    def _create_widgets(self):
        """Create VOG-specific widgets (called by initialize_gui_framework)."""
        self._setup_ui()

    def _setup_ui(self):
        """Set up the main UI."""
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=0)
        self.root.rowconfigure(1, weight=1)
        self.root.rowconfigure(2, weight=0)

        # Status bar at top
        status_frame = ttk.Frame(self.root)
        status_frame.grid(row=0, column=0, sticky="ew", padx=5, pady=2)

        self.status_label = ttk.Label(
            status_frame,
            text="VOG Module - Waiting for devices..."
        )
        self.status_label.pack(side=tk.LEFT)

        self.recording_label = ttk.Label(
            status_frame,
            text="",
            foreground="red"
        )
        self.recording_label.pack(side=tk.RIGHT)

        # Device notebook (tabs)
        self.notebook = ttk.Notebook(self.root)
        self.notebook.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)

        # Bottom status bar
        bottom_frame = ttk.Frame(self.root)
        bottom_frame.grid(row=2, column=0, sticky="ew", padx=5, pady=2)

        self.device_count_label = ttk.Label(bottom_frame, text="Devices: 0")
        self.device_count_label.pack(side=tk.LEFT)

    def _ensure_dongle_tab(self) -> DongleTab:
        """Ensure the XBee dongle tab exists."""
        if not self._dongle_tab_created:
            dongle_frame = ttk.Frame(self.notebook)
            self.dongle_tab = DongleTab(dongle_frame)
            tab_content = self.dongle_tab.build()
            tab_content.pack(fill=tk.BOTH, expand=True)
            self.notebook.insert(0, dongle_frame, text="XBee Dongle")
            self._dongle_tab_created = True

            # Wire up buttons
            if self.dongle_tab.rescan_button:
                self.dongle_tab.rescan_button.config(command=self._on_rescan_network)
            if self.dongle_tab.rtc_sync_button:
                self.dongle_tab.rtc_sync_button.config(command=self._on_sync_all_rtc)

        return self.dongle_tab

    def _on_rescan_network(self):
        """Handle rescan network button."""
        if self.async_bridge and hasattr(self.system, 'rescan_xbee_network'):
            self.async_bridge.run_coroutine(self.system.rescan_xbee_network())

    def _on_sync_all_rtc(self):
        """Handle sync all RTC button."""
        if not self.dongle_tab:
            return

        wireless_device_ids = list(self.dongle_tab.wireless_devices.keys())
        if not wireless_device_ids:
            messagebox.showinfo("No Devices", "No wireless devices connected to sync.")
            return

        if self.async_bridge:
            # Disable button during sync
            if self.dongle_tab.rtc_sync_button:
                self.dongle_tab.rtc_sync_button.config(state='disabled')

            async def sync_and_restore():
                try:
                    for device_id in wireless_device_ids:
                        handler = self.system.get_device_handler(device_id)
                        if handler:
                            # Send RTC sync command
                            from ...utils.rtc import format_rtc_sync
                            rtc_string = format_rtc_sync()
                            await handler.send_command('set_rtc', rtc_string)
                finally:
                    # Re-enable button
                    if self.dongle_tab and self.dongle_tab.rtc_sync_button:
                        self.root.after(0, lambda: self.dongle_tab.rtc_sync_button.config(state='normal'))

            self.async_bridge.run_coroutine(sync_and_restore())

    def on_device_connected(self, port: str, device_type: VOGDeviceType = None):
        """Handle device connection - add tab."""
        self.logger.info("Device connected: %s (type=%s)", port, device_type)

        if port in self.device_tabs:
            return

        # Determine device type from handler if not provided
        if device_type is None:
            handler = self.system.get_device_handler(port)
            if handler:
                device_type = handler.device_type_enum
            else:
                device_type = VOGDeviceType.SVOG

        # For wireless devices, add to dongle tab device list
        if device_type == VOGDeviceType.WVOG_WIRELESS:
            dongle_tab = self._ensure_dongle_tab()
            dongle_tab.add_device(port)

        # Create device tab with appropriate type
        tab = VOGDeviceTab(self.notebook, port, self.system, device_type)

        # Tab text shows device type
        port_short = port.split('/')[-1] if '/' in port else port
        tab_text = f"{port_short} ({device_type.value})"
        self.notebook.add(tab.frame, text=tab_text)

        self.device_tabs[port] = tab
        self._update_status()

    def on_device_disconnected(self, port: str, device_type: VOGDeviceType = None):
        """Handle device disconnection - remove tab."""
        self.logger.info("Device disconnected: %s", port)

        if port in self.device_tabs:
            tab = self.device_tabs.pop(port)

            # Remove from dongle tab if wireless
            if tab.device_type == VOGDeviceType.WVOG_WIRELESS and self.dongle_tab:
                self.dongle_tab.remove_device(port)

            tab.cleanup()

            # Find and remove the tab from notebook
            port_short = port.split('/')[-1] if '/' in port else port
            for i in range(self.notebook.index("end")):
                tab_text = self.notebook.tab(i, "text")
                if tab_text.startswith(port_short):
                    self.notebook.forget(i)
                    break

        self._update_status()

    def on_device_data(self, port: str, data_type: str, data: Dict[str, Any]):
        """Handle data from device."""
        self.logger.debug("Data from %s: %s - %s", port, data_type, data)

        tab = self.device_tabs.get(port)

        if data_type == 'data':
            if tab:
                tab.update_data(data)
        elif data_type == 'stimulus':
            if tab:
                state = data.get('state', 0)
                tab.update_stimulus_state(state)
        elif data_type == 'battery':
            percent = data.get('percent', 0)
            if tab:
                if tab.device_type == VOGDeviceType.WVOG_WIRELESS:
                    # Update in dongle tab
                    if self.dongle_tab:
                        self.dongle_tab.update_device_battery(port, int(percent))
                elif tab.device_type == VOGDeviceType.WVOG_USB:
                    # Update in device tab
                    tab.update_battery(int(percent))

    def on_xbee_dongle_status_change(self, status: str, detail: str):
        """Handle XBee dongle status changes."""
        self.logger.info("XBee dongle status: %s %s", status, detail)

        dongle_tab = self._ensure_dongle_tab()

        if status == 'connected':
            dongle_tab.update_status(True, detail)
        elif status == 'disconnected':
            dongle_tab.update_status(False)
        elif status == 'disabled':
            dongle_tab.update_status(False)
            dongle_tab.status_label.config(text="Disabled (USB wVOG connected)")

    def update_display(self):
        """Update display (called periodically)."""
        pass

    def sync_recording_state(self):
        """Sync recording state with system."""
        if self.system.recording:
            self.recording_label.config(text="RECORDING", foreground="red")
            for tab in self.device_tabs.values():
                if tab.plotter:
                    tab.plotter.start_recording()
        else:
            self.recording_label.config(text="")
            for tab in self.device_tabs.values():
                if tab.plotter:
                    tab.plotter.stop_recording()

    def _update_status(self):
        """Update status labels."""
        device_count = len(self.device_tabs)
        self.device_count_label.config(text=f"Devices: {device_count}")

        if device_count == 0:
            self.status_label.config(text="VOG Module - Waiting for devices...")
        else:
            self.status_label.config(text=f"VOG Module - {device_count} device(s) connected")

    def save_window_geometry_to_config(self):
        """Save window geometry to config file."""
        from pathlib import Path
        from rpi_logger.modules.base import gui_utils

        config_path = gui_utils.get_module_config_path(Path(__file__))
        gui_utils.save_window_geometry(self.root, config_path)
