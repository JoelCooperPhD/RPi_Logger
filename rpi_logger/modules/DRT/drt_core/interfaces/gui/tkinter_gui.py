import asyncio
from rpi_logger.core.logging_utils import get_module_logger
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from typing import TYPE_CHECKING, Optional, Dict, Any
from collections import deque
from pathlib import Path

from rpi_logger.modules.base import TkinterGUIBase, TkinterMenuBase
from .drt_plotter import DRTPlotter
from .drt_config_window import DRTConfigWindow
from .quick_status_panel import QuickStatusPanel
from .battery_widget import CompactBatteryWidget
from ...device_types import DRTDeviceType

if TYPE_CHECKING:
    from ...drt_system import DRTSystem


class DeviceTab:
    def __init__(self, device_id: str, device_type: DRTDeviceType, parent_frame: tk.Frame):
        self.device_id = device_id
        self.device_type = device_type
        self.frame = parent_frame
        self.plotter: Optional[DRTPlotter] = None

        self.trial_number_var = tk.StringVar(value="0")
        self.reaction_time_var = tk.StringVar(value="-1")
        self.click_count_var = tk.StringVar(value="0")
        self.battery_var = tk.StringVar(value="---%")

        self.stim_on_button: Optional[ttk.Button] = None
        self.stim_off_button: Optional[ttk.Button] = None
        self.configure_button: Optional[ttk.Button] = None
        self.battery_widget: Optional[CompactBatteryWidget] = None


class WirelessDeviceEntry:
    """Entry for a wireless device displayed in the dongle tab."""

    def __init__(self, device_id: str, parent_frame: tk.Frame):
        self.device_id = device_id
        self.frame = parent_frame
        self.battery_percent: Optional[int] = None
        self.connected: bool = True

        # UI elements
        self.row_frame: Optional[ttk.Frame] = None
        self.id_label: Optional[ttk.Label] = None
        self.status_indicator: Optional[tk.Label] = None
        self.battery_widget: Optional[CompactBatteryWidget] = None


class DongleTab:
    """Tab for XBee dongle status and controls."""

    DONGLE_ID = "__xbee_dongle__"

    def __init__(self, parent_frame: tk.Frame):
        self.frame = parent_frame
        self.status_var = tk.StringVar(value="Connected")
        self.port_var = tk.StringVar(value="")
        self.devices_var = tk.StringVar(value="0")
        self.search_button: Optional[ttk.Button] = None
        self.status_label: Optional[ttk.Label] = None
        self.rtc_sync_button: Optional[ttk.Button] = None

        # Wireless devices section
        self.devices_frame: Optional[ttk.LabelFrame] = None
        self.devices_container: Optional[ttk.Frame] = None
        self.no_devices_label: Optional[ttk.Label] = None
        self.wireless_devices: Dict[str, WirelessDeviceEntry] = {}


class TkinterGUI(TkinterGUIBase, TkinterMenuBase):

    def __init__(
        self,
        drt_system: 'DRTSystem',
        args,
        *,
        master: Optional[tk.Widget] = None,
        quick_panel: Optional[QuickStatusPanel] = None,
    ):
        self.system = drt_system
        self.args = args
        self.async_bridge = None
        if not hasattr(self, "logger"):
            self.logger = get_module_logger("DRTTkinterGUI")

        self.notebook: Optional[ttk.Notebook] = None
        self.device_tabs: Dict[str, DeviceTab] = {}
        self.dongle_tab: Optional[DongleTab] = None
        self.empty_state_label: Optional[ttk.Label] = None

        self.stimulus_state: Dict[str, int] = {}
        self.config_window: Optional[DRTConfigWindow] = None
        self.quick_panel: Optional[QuickStatusPanel] = quick_panel
        self.devices_panel_visible_var = None

        self.initialize_gui_framework(
            title="DRT Monitor",
            default_width=800,
            default_height=600,
            menu_bar_kwargs={'include_sources': False},
            master=master,
        )

    def set_close_handler(self, handler):
        protocol_target = getattr(self.root, "protocol", None)
        if callable(protocol_target):
            protocol_target("WM_DELETE_WINDOW", handler)
            return
        resolver = getattr(self.root, "winfo_toplevel", None)
        if callable(resolver):
            try:
                window = resolver()
            except Exception:
                return
            protocol_target = getattr(window, "protocol", None)
            if callable(protocol_target):
                protocol_target("WM_DELETE_WINDOW", handler)

    def on_start_recording(self):
        self._start_recording()

    def on_stop_recording(self):
        self._stop_recording()

    def _create_widgets(self):
        if getattr(self, "_embedded_mode", False):
            container = self.root
            container.columnconfigure(0, weight=1)
            container.rowconfigure(0, weight=1)
            self._build_main_controls(container)
            return

        content_frame = self.create_standard_layout(logger_height=4, content_title="DRT Controls", enable_content_toggle=False)
        target = getattr(self, "module_content_frame", None) or content_frame
        self._build_main_controls(target)

        io_frame = self.create_io_view_frame(
            title="Session Output",
            default_visible=True,
            menu_label="Show Session Output",
            config_key="gui_show_session_output",
            padding="3",
        )
        self.devices_panel_visible_var = getattr(self, 'io_view_visible_var', None)
        if io_frame is not None:
            io_frame.grid_configure(padx=0, pady=(0, 0), sticky='ew')
            if self.devices_panel_visible_var and not self.devices_panel_visible_var.get():
                io_frame.grid_remove()

        if hasattr(self, 'log_frame') and self.log_frame.winfo_manager():
            self.log_frame.grid_configure(row=2, column=0, sticky='ew')
            if hasattr(self, 'logger_visible_var') and not self.logger_visible_var.get():
                self.log_frame.grid_remove()

        if self.quick_panel is None and io_frame is not None:
            self.quick_panel = QuickStatusPanel(io_frame)
        if self.quick_panel and io_frame is not None:
            self.quick_panel.parent = io_frame
            self.quick_panel.build(container=io_frame)

    def _build_main_controls(self, container: tk.Misc) -> None:
        self.logger.debug("Building DRT controls (embedded=%s)", getattr(self, "_embedded_mode", False))
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        notebook_container = ttk.Frame(container)
        notebook_container.grid(row=0, column=0, sticky='nsew', padx=5, pady=(5, 0))
        notebook_container.columnconfigure(0, weight=1)
        notebook_container.rowconfigure(0, weight=1)

        self.notebook = ttk.Notebook(notebook_container, width=160)
        self.notebook.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)

        self.empty_state_label = ttk.Label(
            notebook_container,
            text="⚠ No DRT devices connected\n\nConnect sDRT, wDRT USB, or wDRT wireless to begin",
            font=('TkDefaultFont', 12),
            justify='center',
            foreground='gray'
        )
        self.empty_state_label.grid(row=0, column=0, sticky='nsew', padx=20, pady=20)
        self.empty_state_label.lift()


    def _create_device_tab(self, device_id: str, device_type: DRTDeviceType) -> DeviceTab:
        tab_frame = ttk.Frame(self.notebook)
        tab = DeviceTab(device_id, device_type, tab_frame)

        tab_frame.columnconfigure(0, weight=1)
        tab_frame.rowconfigure(3, weight=1)

        tab.plotter = DRTPlotter(tab_frame)
        tab.plotter.add_device(device_id)

        stimulus_frame = ttk.LabelFrame(tab_frame, text="Stimulus", padding=(10, 5))
        stimulus_frame.grid(row=1, column=1, sticky='nsew', padx=5, pady=5)
        stimulus_frame.columnconfigure(0, weight=1)
        stimulus_frame.columnconfigure(1, weight=1)

        tab.stim_on_button = ttk.Button(stimulus_frame, text="ON",
                                        command=lambda: self._on_stimulus_on(device_id))
        tab.stim_on_button.grid(row=0, column=0, sticky='nsew', padx=2)

        tab.stim_off_button = ttk.Button(stimulus_frame, text="OFF",
                                         command=lambda: self._on_stimulus_off(device_id))
        tab.stim_off_button.grid(row=0, column=1, sticky='nsew', padx=2)

        results_frame = ttk.LabelFrame(tab_frame, text="Results", padding=(10, 5))
        results_frame.grid(row=4, column=1, sticky='nsew', padx=5, pady=5)
        results_frame.columnconfigure(0, weight=0)
        results_frame.columnconfigure(1, weight=1)

        ttk.Label(results_frame, text="Trial Number:", anchor='w').grid(row=0, column=0, sticky='w', pady=2)
        ttk.Label(results_frame, textvariable=tab.trial_number_var, anchor='e').grid(row=0, column=1, sticky='e', pady=2)

        ttk.Label(results_frame, text="Reaction Time:", anchor='w').grid(row=1, column=0, sticky='w', pady=2)
        ttk.Label(results_frame, textvariable=tab.reaction_time_var, anchor='e').grid(row=1, column=1, sticky='e', pady=2)

        ttk.Label(results_frame, text="Response Count:", anchor='w').grid(row=2, column=0, sticky='w', pady=2)
        ttk.Label(results_frame, textvariable=tab.click_count_var, anchor='e').grid(row=2, column=1, sticky='e', pady=2)

        # Add battery display for USB wDRT devices
        if device_type == DRTDeviceType.WDRT_USB:
            battery_frame = ttk.LabelFrame(tab_frame, text="Battery", padding=(10, 5))
            battery_frame.grid(row=2, column=1, sticky='nsew', padx=5, pady=5)
            battery_frame.columnconfigure(1, weight=1)

            ttk.Label(battery_frame, text="Level:", anchor='w').grid(row=0, column=0, sticky='w', pady=2)

            # Add compact battery widget
            tab.battery_widget = CompactBatteryWidget(battery_frame, segment_size=8)
            tab.battery_widget.grid(row=0, column=1, sticky='w', padx=(5, 0), pady=2)
            tab.battery_widget.set_percent(None)  # Unknown initially

            ttk.Label(battery_frame, textvariable=tab.battery_var, anchor='e', width=5).grid(
                row=0, column=2, sticky='e', pady=2, padx=(5, 0)
            )

            # Add refresh button
            refresh_btn = ttk.Button(
                battery_frame,
                text="Refresh",
                width=8,
                command=lambda: self._on_refresh_battery(device_id)
            )
            refresh_btn.grid(row=0, column=3, sticky='e', padx=(10, 0), pady=2)

        configure_frame = ttk.Frame(tab_frame)
        configure_frame.grid(row=5, column=1, sticky='nsew', padx=5, pady=5)
        configure_frame.columnconfigure(0, weight=1)

        tab.configure_button = ttk.Button(configure_frame, text="Configure Unit",
                                         command=lambda: self._on_configure(device_id), width=25)
        tab.configure_button.grid(row=0, column=0, sticky='nsew')

        # Create tab label with device type indicator
        type_prefix = {
            DRTDeviceType.SDRT: "sDRT",
            DRTDeviceType.WDRT_USB: "wDRT",
            DRTDeviceType.WDRT_WIRELESS: "wDRT-W",
        }.get(device_type, "DRT")

        # Use short device ID for tab label
        short_id = device_id.split('/')[-1] if '/' in device_id else device_id
        tab_label = f"{type_prefix}: {short_id}"
        self.notebook.add(tab_frame, text=tab_label)

        return tab

    def _create_dongle_tab(self, port: str = "") -> DongleTab:
        """Create a tab for the XBee dongle."""
        tab_frame = ttk.Frame(self.notebook)
        tab = DongleTab(tab_frame)
        tab.port_var.set(port)

        tab_frame.columnconfigure(0, weight=1)
        tab_frame.rowconfigure(3, weight=1)

        # Status frame
        status_frame = ttk.LabelFrame(tab_frame, text="Dongle Status", padding=(15, 10))
        status_frame.grid(row=0, column=0, sticky='ew', padx=10, pady=(10, 5))
        status_frame.columnconfigure(1, weight=1)

        ttk.Label(status_frame, text="Status:", anchor='w').grid(row=0, column=0, sticky='w', pady=3)
        tab.status_label = ttk.Label(status_frame, textvariable=tab.status_var, anchor='w', foreground='green')
        tab.status_label.grid(row=0, column=1, sticky='w', pady=3, padx=(10, 0))

        ttk.Label(status_frame, text="Port:", anchor='w').grid(row=1, column=0, sticky='w', pady=3)
        ttk.Label(status_frame, textvariable=tab.port_var, anchor='w').grid(row=1, column=1, sticky='w', pady=3, padx=(10, 0))

        # Wireless devices section
        tab.devices_frame = ttk.LabelFrame(tab_frame, text="Connected Wireless Devices", padding=(15, 10))
        tab.devices_frame.grid(row=1, column=0, sticky='nsew', padx=10, pady=5)
        tab.devices_frame.columnconfigure(0, weight=1)

        # Container for device entries
        tab.devices_container = ttk.Frame(tab.devices_frame)
        tab.devices_container.pack(fill=tk.BOTH, expand=True)
        tab.devices_container.columnconfigure(0, weight=1)

        # No devices label (shown when no wireless devices connected)
        tab.no_devices_label = ttk.Label(
            tab.devices_container,
            text="No wireless devices discovered yet.\nUse 'Search for Devices' to scan the network.",
            foreground='gray',
            justify='center'
        )
        tab.no_devices_label.pack(pady=20)

        # RTC sync section
        rtc_frame = ttk.LabelFrame(tab_frame, text="Real-Time Clock Sync", padding=(15, 10))
        rtc_frame.grid(row=2, column=0, sticky='ew', padx=10, pady=5)
        rtc_frame.columnconfigure(0, weight=1)

        rtc_info = ttk.Label(
            rtc_frame,
            text="Synchronize the clock on all connected wireless wDRT devices\nwith your computer's time.",
            wraplength=350,
            justify='left',
            foreground='gray'
        )
        rtc_info.pack(anchor=tk.W, pady=(0, 5))

        tab.rtc_sync_button = ttk.Button(
            rtc_frame,
            text="Sync RTC on All Devices",
            command=self._on_sync_all_rtc,
            width=25
        )
        tab.rtc_sync_button.pack(anchor=tk.W, pady=5)

        # Search controls frame
        controls_frame = ttk.LabelFrame(tab_frame, text="Network Discovery", padding=(15, 10))
        controls_frame.grid(row=3, column=0, sticky='ew', padx=10, pady=5)
        controls_frame.columnconfigure(0, weight=1)

        info_label = ttk.Label(
            controls_frame,
            text="Search for wireless wDRT devices on the XBee network.\n"
                 "This will disconnect existing wireless devices and start a new search.",
            wraplength=350,
            justify='left',
            foreground='gray'
        )
        info_label.pack(anchor=tk.W, pady=(0, 5))

        tab.search_button = ttk.Button(
            controls_frame,
            text="Search for Devices",
            command=self._on_rescan_xbee,
            width=25
        )
        tab.search_button.pack(anchor=tk.W, pady=5)

        # Spacer frame to push content up
        spacer = ttk.Frame(tab_frame)
        spacer.grid(row=4, column=0, sticky='nsew')

        # Add dongle tab - insert at beginning if other tabs exist, otherwise just add
        if self.notebook.index("end") > 0:
            self.notebook.insert(0, tab_frame, text="XBee Dongle")
        else:
            self.notebook.add(tab_frame, text="XBee Dongle")
        self.notebook.select(0)  # Select the dongle tab

        return tab

    def _remove_dongle_tab(self) -> None:
        """Remove the dongle tab from the notebook."""
        if self.dongle_tab is None:
            return

        # Find and remove the dongle tab
        for idx in range(self.notebook.index("end")):
            tab_text = self.notebook.tab(idx, "text")
            if tab_text == "XBee Dongle":
                self.notebook.forget(idx)
                break

        self.dongle_tab = None
        self.logger.info("Removed XBee dongle tab")

    def _update_dongle_device_count(self) -> None:
        """Update the device count shown in the dongle tab."""
        if self.dongle_tab is None:
            return

        # Count wireless devices from the dongle tab's device list
        wireless_count = len(self.dongle_tab.wireless_devices)
        self.dongle_tab.devices_var.set(str(wireless_count))

    def _on_rescan_xbee(self) -> None:
        """Handle the rescan button click."""
        self.logger.info("Rescanning XBee network...")

        if self.dongle_tab and self.dongle_tab.search_button:
            self.dongle_tab.search_button.config(state='disabled', text='Searching...')

        if self.async_bridge:
            self.async_bridge.run_coroutine(self._rescan_xbee_async())
        else:
            self.logger.error("No async_bridge available for XBee rescan")

    async def _rescan_xbee_async(self) -> None:
        """Async implementation of XBee rescan."""
        try:
            await self.system.rescan_xbee_network()
        except Exception as e:
            self.logger.error("Error during XBee rescan: %s", e, exc_info=True)
        finally:
            # Re-enable button after a short delay
            if self.dongle_tab and self.dongle_tab.search_button:
                self.root.after(2000, self._reset_search_button)

    def _reset_search_button(self) -> None:
        """Reset the search button state."""
        if self.dongle_tab and self.dongle_tab.search_button:
            self.dongle_tab.search_button.config(state='normal', text='Search for Devices')

    def _on_sync_all_rtc(self) -> None:
        """Sync RTC on all connected wireless devices."""
        if not self.dongle_tab:
            return

        wireless_device_ids = list(self.dongle_tab.wireless_devices.keys())
        if not wireless_device_ids:
            messagebox.showinfo("No Devices", "No wireless devices connected to sync.")
            return

        self.logger.info("Syncing RTC on %d wireless devices", len(wireless_device_ids))

        if self.dongle_tab.rtc_sync_button:
            self.dongle_tab.rtc_sync_button.config(state='disabled', text='Syncing...')

        if self.async_bridge:
            self.async_bridge.run_coroutine(self._sync_all_rtc_async(wireless_device_ids))
        else:
            self.logger.error("No async_bridge available for RTC sync")

    async def _sync_all_rtc_async(self, device_ids: list) -> None:
        """Async implementation of RTC sync for all wireless devices."""
        success_count = 0
        fail_count = 0

        for device_id in device_ids:
            handler = self.system.get_device_handler(device_id)
            if handler:
                try:
                    await handler.sync_rtc()
                    success_count += 1
                    self.logger.info("RTC synced on %s", device_id)
                except Exception as e:
                    self.logger.error("Failed to sync RTC on %s: %s", device_id, e)
                    fail_count += 1
            else:
                fail_count += 1

        # Reset button and show result
        if self.dongle_tab and self.dongle_tab.rtc_sync_button:
            self.root.after(0, lambda: self._finish_rtc_sync(success_count, fail_count))

    def _finish_rtc_sync(self, success_count: int, fail_count: int) -> None:
        """Finish RTC sync and show result."""
        if self.dongle_tab and self.dongle_tab.rtc_sync_button:
            self.dongle_tab.rtc_sync_button.config(state='normal', text='Sync RTC on All Devices')

        if fail_count == 0:
            messagebox.showinfo("Success", f"RTC synchronized on {success_count} device(s)")
        else:
            messagebox.showwarning("Partial Success",
                                   f"RTC sync completed.\nSuccess: {success_count}\nFailed: {fail_count}")

    def _add_wireless_device_entry(self, device_id: str) -> None:
        """Add a wireless device entry to the dongle tab."""
        if not self.dongle_tab or device_id in self.dongle_tab.wireless_devices:
            return

        # Hide the "no devices" label
        if self.dongle_tab.no_devices_label:
            self.dongle_tab.no_devices_label.pack_forget()

        container = self.dongle_tab.devices_container
        entry = WirelessDeviceEntry(device_id, container)

        # Create row frame
        entry.row_frame = ttk.Frame(container)
        entry.row_frame.pack(fill=tk.X, pady=2)
        entry.row_frame.columnconfigure(1, weight=1)

        # Status indicator (green circle for connected)
        entry.status_indicator = tk.Label(
            entry.row_frame,
            text="●",
            fg='green',
            font=('TkDefaultFont', 10)
        )
        entry.status_indicator.grid(row=0, column=0, padx=(0, 5))

        # Device ID label
        short_id = device_id.split('/')[-1] if '/' in device_id else device_id
        entry.id_label = ttk.Label(entry.row_frame, text=short_id, width=15, anchor='w')
        entry.id_label.grid(row=0, column=1, sticky='w')

        # Battery widget
        entry.battery_widget = CompactBatteryWidget(entry.row_frame, segment_size=6)
        entry.battery_widget.grid(row=0, column=2, padx=(10, 0))
        entry.battery_widget.set_percent(None)  # Unknown initially

        # Battery percentage label
        entry.battery_label = ttk.Label(entry.row_frame, text="---%", width=5)
        entry.battery_label.grid(row=0, column=3, padx=(5, 0))

        self.dongle_tab.wireless_devices[device_id] = entry
        self._update_dongle_device_count()
        self.logger.info("Added wireless device entry: %s", device_id)

    def _remove_wireless_device_entry(self, device_id: str) -> None:
        """Remove a wireless device entry from the dongle tab."""
        if not self.dongle_tab or device_id not in self.dongle_tab.wireless_devices:
            return

        entry = self.dongle_tab.wireless_devices.pop(device_id)
        if entry.row_frame:
            entry.row_frame.destroy()

        # Show "no devices" label if no devices left
        if not self.dongle_tab.wireless_devices and self.dongle_tab.no_devices_label:
            self.dongle_tab.no_devices_label.pack(pady=20)

        self._update_dongle_device_count()
        self.logger.info("Removed wireless device entry: %s", device_id)

    def _update_wireless_device_battery(self, device_id: str, percent: int) -> None:
        """Update the battery display for a wireless device in the dongle tab."""
        if not self.dongle_tab or device_id not in self.dongle_tab.wireless_devices:
            return

        entry = self.dongle_tab.wireless_devices[device_id]
        entry.battery_percent = percent

        if entry.battery_widget:
            entry.battery_widget.set_percent(percent)

        if hasattr(entry, 'battery_label') and entry.battery_label:
            entry.battery_label.config(text=f"{percent}%")

    def on_xbee_dongle_status_change(self, status: str, detail: str) -> None:
        """Handle XBee dongle status changes."""
        self.logger.info("=== GUI ON_XBEE_DONGLE_STATUS_CHANGE ===")
        self.logger.info("Status: %s, Detail: %s", status, detail)
        self.logger.info("Current dongle_tab: %s", self.dongle_tab)
        self.logger.info("Notebook: %s", self.notebook)

        if status == 'connected':
            # Create dongle tab if not exists
            if self.dongle_tab is None:
                self.logger.info("Creating dongle tab...")
                try:
                    self.dongle_tab = self._create_dongle_tab(detail)
                    self.logger.info("SUCCESS: Created XBee dongle tab for port %s", detail)
                except Exception as e:
                    self.logger.error("FAILED to create dongle tab: %s", e, exc_info=True)
            else:
                self.logger.info("Dongle tab already exists")

            # Update status
            self.dongle_tab.status_var.set("Connected")
            self.dongle_tab.port_var.set(detail)
            if self.dongle_tab.status_label:
                self.dongle_tab.status_label.config(foreground='green')

            # Hide empty state if visible
            if self.empty_state_label:
                self.empty_state_label.grid_remove()
                self.notebook.lift()

        elif status == 'disconnected':
            # Remove dongle tab
            self._remove_dongle_tab()

            # Show empty state if no devices remain
            if self.empty_state_label and not self.device_tabs:
                self.empty_state_label.grid(row=0, column=0, sticky='nsew', padx=20, pady=20)
                self.empty_state_label.lift()

        elif status == 'disabled':
            # XBee disabled due to USB wDRT connection
            if self.dongle_tab:
                self.dongle_tab.status_var.set("Disabled (USB wDRT connected)")
                if self.dongle_tab.status_label:
                    self.dongle_tab.status_label.config(foreground='orange')
                if self.dongle_tab.search_button:
                    self.dongle_tab.search_button.config(state='disabled')

        elif status == 'enabled':
            # XBee re-enabled
            if self.dongle_tab:
                self.dongle_tab.status_var.set("Connected")
                if self.dongle_tab.status_label:
                    self.dongle_tab.status_label.config(foreground='green')
                if self.dongle_tab.search_button:
                    self.dongle_tab.search_button.config(state='normal')

    def _start_recording(self):
        if self.async_bridge:
            self.async_bridge.run_coroutine(self._start_recording_async())
        else:
            self.logger.error("No async_bridge available to start recording")

    async def _start_recording_async(self):
        if await self.system.start_recording():
            self.sync_recording_state()
            for tab in self.device_tabs.values():
                if tab.plotter:
                    tab.plotter.start_recording()
            self.logger.info("Recording started")
        else:
            self.logger.error("Failed to start recording")

    def _stop_recording(self):
        if self.async_bridge:
            self.async_bridge.run_coroutine(self._stop_recording_async())
        else:
            self.logger.error("No async_bridge available to stop recording")

    async def _stop_recording_async(self):
        if await self.system.stop_recording():
            self.sync_recording_state()
            for tab in self.device_tabs.values():
                if tab.plotter:
                    tab.plotter.stop_recording()
            self.logger.info("Recording stopped")
        else:
            self.logger.error("Failed to stop recording")

    def _on_stimulus_on(self, port: str):
        handler = self.system.get_device_handler(port)
        if handler:
            self.logger.info("Stimulus ON button pressed for %s", port)

            if self.async_bridge:
                self.async_bridge.run_coroutine(handler.set_stimulus(True))
            else:
                self.logger.error("No async_bridge available to send command")

            self.stimulus_state[port] = 1
            if port in self.device_tabs and self.device_tabs[port].plotter:
                self.device_tabs[port].plotter.update_stimulus_state(port, 1)
            self.logger.info("Stimulus ON scheduled for %s", port)
        else:
            self.logger.error("No handler found for device %s (system=%s)", port, type(self.system).__name__)

    def _on_stimulus_off(self, port: str):
        handler = self.system.get_device_handler(port)
        if handler:
            self.logger.info("Stimulus OFF button pressed for %s", port)

            if self.async_bridge:
                self.async_bridge.run_coroutine(handler.set_stimulus(False))
            else:
                self.logger.error("No async_bridge available to send command")

            self.stimulus_state[port] = 0
            if port in self.device_tabs and self.device_tabs[port].plotter:
                self.device_tabs[port].plotter.update_stimulus_state(port, 0)
            self.logger.info("Stimulus OFF scheduled for %s", port)
        else:
            self.logger.error("No handler found for device %s (system=%s)", port, type(self.system).__name__)

    def _on_configure(self, device_id: str):
        tab = self.device_tabs.get(device_id)
        if not tab:
            return

        parent = getattr(self, 'root', None)

        # Use unified config window for all device types
        handler = self.system.get_device_handler(device_id)
        if handler:
            self.config_window = DRTConfigWindow(
                parent,
                device_id,
                device_type=tab.device_type,
                on_upload=lambda params: self._on_config_upload(device_id, params),
                on_iso_preset=lambda: self._on_config_iso(device_id),
                on_get_config=lambda: self._on_config_get(device_id),
            )

    def _on_config_upload(self, device_id: str, params: Dict[str, int]):
        """Handle config upload for any DRT device type."""
        handler = self.system.get_device_handler(device_id)
        if handler and self.async_bridge:
            tab = self.device_tabs.get(device_id)
            if tab and tab.device_type == DRTDeviceType.SDRT:
                # sDRT uses individual commands
                self.async_bridge.run_coroutine(self._upload_sdrt_config(handler, params))
            else:
                # wDRT uses single 'set' command
                self.async_bridge.run_coroutine(handler.send_command('set', params))

    async def _upload_sdrt_config(self, handler, params: Dict[str, int]) -> None:
        """Upload config to sDRT device using individual commands."""
        try:
            if 'lowerISI' in params:
                await handler.set_lower_isi(params['lowerISI'])
            if 'upperISI' in params:
                await handler.set_upper_isi(params['upperISI'])
            if 'stimDur' in params:
                await handler.set_stimulus_duration(params['stimDur'])
            if 'intensity' in params:
                # Convert percentage to 0-255 range for sDRT
                intensity = int(params['intensity'] * 2.55)
                await handler.set_intensity(intensity)
            self.logger.info("sDRT config uploaded successfully")
        except Exception as e:
            self.logger.error("Failed to upload sDRT config: %s", e)

    def _on_config_iso(self, device_id: str):
        """Handle ISO preset for any DRT device type."""
        handler = self.system.get_device_handler(device_id)
        if handler and self.async_bridge:
            tab = self.device_tabs.get(device_id)
            if tab and tab.device_type == DRTDeviceType.SDRT:
                self.async_bridge.run_coroutine(handler.set_iso_params())
            else:
                self.async_bridge.run_coroutine(handler.send_command('iso'))

    def _on_config_get(self, device_id: str):
        """Handle get config for any DRT device type."""
        handler = self.system.get_device_handler(device_id)
        if handler and self.async_bridge:
            tab = self.device_tabs.get(device_id)
            if tab and tab.device_type == DRTDeviceType.SDRT:
                self.async_bridge.run_coroutine(self._get_sdrt_config(handler, device_id))
            else:
                self.async_bridge.run_coroutine(handler.send_command('get_config'))

    async def _get_sdrt_config(self, handler, device_id: str) -> None:
        """Get config from sDRT device."""
        try:
            config = await handler.get_device_config()
            if config and self.config_window:
                self.root.after(0, lambda: self.config_window.update_config(config))
        except Exception as e:
            self.logger.error("Failed to get sDRT config: %s", e)

    def _update_device_tab_battery(self, device_id: str, percent: int) -> None:
        """Update battery display for USB wDRT device in its tab."""
        tab = self.device_tabs.get(device_id)
        if not tab:
            return

        tab.battery_var.set(f"{percent}%")

        # Update the battery widget if it exists
        if hasattr(tab, 'battery_widget') and tab.battery_widget:
            tab.battery_widget.set_percent(percent)

    def _on_refresh_battery(self, device_id: str) -> None:
        """Request battery update for a device."""
        handler = self.system.get_device_handler(device_id)
        if handler and self.async_bridge:
            self.async_bridge.run_coroutine(handler.send_command('get_battery'))

    def on_device_connected(self, device_id: str, device_type: DRTDeviceType = None):
        try:
            # Handle legacy calls without device_type
            if device_type is None:
                device_type = self.system.get_device_type(device_id) or DRTDeviceType.SDRT

            if device_id not in self.device_tabs:
                tab = self._create_device_tab(device_id, device_type)
                self.device_tabs[device_id] = tab

            if self.empty_state_label and (self.device_tabs or self.dongle_tab):
                self.empty_state_label.grid_remove()
                self.notebook.lift()

            # Add wireless devices to the dongle tab's device list
            if device_type == DRTDeviceType.WDRT_WIRELESS:
                self._add_wireless_device_entry(device_id)
                # Request initial battery status
                handler = self.system.get_device_handler(device_id)
                if handler and self.async_bridge:
                    self.async_bridge.run_coroutine(handler.send_command('get_battery'))

            # Request initial battery for USB wDRT devices
            elif device_type == DRTDeviceType.WDRT_USB:
                handler = self.system.get_device_handler(device_id)
                if handler and self.async_bridge:
                    self.async_bridge.run_coroutine(handler.send_command('get_battery'))

            if self.quick_panel:
                self.quick_panel.device_connected(device_id)
                if not self.system.recording:
                    self.quick_panel.set_module_state("Ready")
        except Exception as e:
            self.logger.error("Error in on_device_connected: %s", e, exc_info=True)

    def on_device_disconnected(self, device_id: str, device_type: DRTDeviceType = None):
        self.logger.info("GUI: Device disconnected: %s", device_id)

        # Get device type before removing from tabs
        was_wireless = False
        if device_id in self.device_tabs:
            tab = self.device_tabs[device_id]
            was_wireless = tab.device_type == DRTDeviceType.WDRT_WIRELESS

            # Find and remove the tab by matching device_id in the tab text
            for idx in range(self.notebook.index("end")):
                tab_text = self.notebook.tab(idx, "text")
                if device_id in tab_text or device_id.split('/')[-1] in tab_text:
                    self.notebook.forget(idx)
                    break

            del self.device_tabs[device_id]
            self.logger.info("Removed tab for device %s", device_id)

        # Remove wireless devices from the dongle tab's device list
        if was_wireless:
            self._remove_wireless_device_entry(device_id)

        # Show empty state only if no devices and no dongle tab
        if self.empty_state_label and not self.device_tabs and not self.dongle_tab:
            self.empty_state_label.grid(row=0, column=0, sticky='nsew', padx=20, pady=20)
            self.empty_state_label.lift()

        if self.quick_panel:
            self.quick_panel.device_disconnected(device_id)
            if not self.device_tabs and not self.system.recording:
                self.quick_panel.set_module_state("Idle")

    def on_device_data(self, port: str, data_type: str, data: Dict[str, Any]):
        tab = self.device_tabs.get(port)

        if data_type == 'battery':
            percent = data.get('percent')
            if percent is not None:
                # Route battery data based on device type
                if tab and tab.device_type == DRTDeviceType.WDRT_WIRELESS:
                    # Update battery in dongle tab for wireless devices
                    self._update_wireless_device_battery(port, int(percent))
                elif tab and tab.device_type == DRTDeviceType.WDRT_USB:
                    # Update battery in device tab for USB wDRT
                    self._update_device_tab_battery(port, int(percent))

        elif data_type == 'config' and tab:
            # Update config window if open
            if self.config_window:
                try:
                    self.config_window.update_config(data)
                except Exception:
                    pass  # Window may have been closed

        elif data_type == 'click' and tab:
            # Handle both 'value' (legacy) and 'count' (new format) keys
            value = data.get('count', data.get('value', ''))
            try:
                click_count = int(value) if value != '' else 0
                tab.click_count_var.set(str(click_count))
            except (ValueError, TypeError):
                pass

        elif data_type == 'trial' and tab:
            trial_num = data.get('trial_number')
            rt = data.get('reaction_time')

            if trial_num is not None:
                tab.trial_number_var.set(str(trial_num))
            if rt is not None:
                tab.reaction_time_var.set(f"{rt:.0f}")

            if rt is not None and tab.plotter:
                is_hit = rt >= 0
                if is_hit:
                    tab.plotter.update_trial(port, rt, is_hit=True)
                else:
                    tab.plotter.update_trial(port, abs(rt), is_hit=False)

        elif data_type == 'stimulus' and tab:
            # Handle both 'value' (legacy) and 'state' (new format) keys
            state_val = data.get('state', data.get('value', ''))
            try:
                # Handle boolean or int
                if isinstance(state_val, bool):
                    state = 1 if state_val else 0
                elif isinstance(state_val, int):
                    state = state_val
                else:
                    state = int(state_val)
                self.stimulus_state[port] = state
            except (ValueError, TypeError):
                if isinstance(state_val, str):
                    if 'on' in state_val.lower():
                        self.stimulus_state[port] = 1
                    elif 'off' in state_val.lower():
                        self.stimulus_state[port] = 0

            if tab and tab.plotter:
                tab.plotter.update_stimulus_state(port, self.stimulus_state.get(port, 0))

        elif data_type == 'data' and tab:
            # Full trial data packet from wDRT (contains trial_number, clicks, reaction_time, battery)
            trial_num = data.get('trial_number')
            rt = data.get('reaction_time')
            clicks = data.get('clicks')
            battery = data.get('battery')

            if trial_num is not None:
                tab.trial_number_var.set(str(trial_num))
            if clicks is not None:
                tab.click_count_var.set(str(clicks))
            if rt is not None:
                # RT of -1 means timeout/miss
                if rt >= 0:
                    tab.reaction_time_var.set(f"{rt}")
                else:
                    tab.reaction_time_var.set("Miss")

            # Update plotter with trial data
            if rt is not None and tab.plotter:
                is_hit = rt >= 0
                if is_hit:
                    tab.plotter.update_trial(port, rt, is_hit=True)
                else:
                    tab.plotter.update_trial(port, 0, is_hit=False)

            # Update battery based on device type
            if battery is not None and tab:
                if tab.device_type == DRTDeviceType.WDRT_WIRELESS:
                    self._update_wireless_device_battery(port, int(battery))
                elif tab.device_type == DRTDeviceType.WDRT_USB:
                    self._update_device_tab_battery(port, int(battery))

        elif data_type == 'reaction_time' and tab:
            # Standalone RT event
            rt = data.get('reaction_time')
            if rt is not None:
                if rt >= 0:
                    tab.reaction_time_var.set(f"{rt}")
                else:
                    tab.reaction_time_var.set("Miss")

        elif data_type == 'experiment_end':
            pass

        elif data_type == 'trial_logged':
            if self.quick_panel:
                self.quick_panel.update_logged_trial(port, data)

    def update_display(self):
        pass

    def update_window_title(self, recording: bool = False):
        base_title = "DRT Monitor"
        target = getattr(self.root, "title", None)
        if not callable(target):
            resolver = getattr(self.root, "winfo_toplevel", None)
            if callable(resolver):
                try:
                    window = resolver()
                except Exception:
                    window = None
                if window:
                    target = getattr(window, "title", None)
        if not callable(target):
            return
        if recording:
            target(f"{base_title} - RECORDING")
        else:
            target(base_title)

    def sync_recording_state(self):
        if self.system.recording:
            self.update_window_title(recording=True)
        else:
            self.update_window_title(recording=False)

        if self.quick_panel:
            if self.system.recording:
                self.quick_panel.set_module_state("Recording")
            elif self.device_tabs:
                self.quick_panel.set_module_state("Ready")
            else:
                self.quick_panel.set_module_state("Idle")

    def save_window_geometry_to_config(self):
        from rpi_logger.modules.base import gui_utils

        if getattr(self, "_embedded_mode", False):
            return

        config_path = gui_utils.get_module_config_path(Path(__file__))
        gui_utils.save_window_geometry(self.root, config_path)
