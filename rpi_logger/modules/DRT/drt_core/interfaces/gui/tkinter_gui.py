import asyncio
from rpi_logger.core.logging_utils import get_module_logger
import tkinter as tk
from tkinter import ttk, scrolledtext
from typing import TYPE_CHECKING, Optional, Dict, Any
from collections import deque
from pathlib import Path

from rpi_logger.modules.base import TkinterGUIBase, TkinterMenuBase
from .drt_plotter import DRTPlotter
from .sdrt_config_window import SDRTConfigWindow
from .wdrt_config_window import WDRTConfigWindow
from .quick_status_panel import QuickStatusPanel
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
        self.empty_state_label: Optional[ttk.Label] = None

        self.stimulus_state: Dict[str, int] = {}
        self.sdrt_config_window: Optional[SDRTConfigWindow] = None
        self.wdrt_config_window: Optional[WDRTConfigWindow] = None
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

        if tab.device_type == DRTDeviceType.SDRT:
            # Use sDRT config window
            if not self.sdrt_config_window:
                self.sdrt_config_window = SDRTConfigWindow(self.system, self.async_bridge, parent=parent)
            self.sdrt_config_window.show_for_device(device_id)
        else:
            # Use wDRT config window for wDRT USB and wireless
            handler = self.system.get_device_handler(device_id)
            if handler:
                self.wdrt_config_window = WDRTConfigWindow(
                    parent,
                    device_id,
                    on_upload=lambda params: self._on_wdrt_upload(device_id, params),
                    on_iso_preset=lambda: self._on_wdrt_iso(device_id),
                    on_rtc_sync=lambda: self._on_wdrt_rtc_sync(device_id),
                    on_get_config=lambda: self._on_wdrt_get_config(device_id),
                    on_get_battery=lambda: self._on_wdrt_get_battery(device_id),
                )

    def _on_wdrt_upload(self, device_id: str, params: Dict[str, int]):
        handler = self.system.get_device_handler(device_id)
        if handler and self.async_bridge:
            self.async_bridge.run_coroutine(handler.send_command('set', params))

    def _on_wdrt_iso(self, device_id: str):
        handler = self.system.get_device_handler(device_id)
        if handler and self.async_bridge:
            self.async_bridge.run_coroutine(handler.send_command('iso'))

    def _on_wdrt_rtc_sync(self, device_id: str):
        handler = self.system.get_device_handler(device_id)
        if handler and self.async_bridge:
            self.async_bridge.run_coroutine(handler.send_command('set_rtc'))

    def _on_wdrt_get_config(self, device_id: str):
        handler = self.system.get_device_handler(device_id)
        if handler and self.async_bridge:
            self.async_bridge.run_coroutine(handler.send_command('get_config'))

    def _on_wdrt_get_battery(self, device_id: str):
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

            if self.empty_state_label and self.device_tabs:
                self.empty_state_label.grid_remove()
                self.notebook.lift()

            if self.quick_panel:
                self.quick_panel.device_connected(device_id)
                if not self.system.recording:
                    self.quick_panel.set_module_state("Ready")
        except Exception as e:
            self.logger.error("Error in on_device_connected: %s", e, exc_info=True)

    def on_device_disconnected(self, device_id: str, device_type: DRTDeviceType = None):
        self.logger.info("GUI: Device disconnected: %s", device_id)

        if device_id in self.device_tabs:
            tab = self.device_tabs[device_id]

            # Find and remove the tab by matching device_id in the tab text
            for idx in range(self.notebook.index("end")):
                tab_text = self.notebook.tab(idx, "text")
                if device_id in tab_text or device_id.split('/')[-1] in tab_text:
                    self.notebook.forget(idx)
                    break

            del self.device_tabs[device_id]
            self.logger.info("Removed tab for device %s", device_id)

        if self.empty_state_label and not self.device_tabs:
            self.empty_state_label.grid(row=0, column=0, sticky='nsew', padx=20, pady=20)
            self.empty_state_label.lift()

        if self.quick_panel:
            self.quick_panel.device_disconnected(device_id)
            if not self.device_tabs and not self.system.recording:
                self.quick_panel.set_module_state("Idle")

    def on_device_data(self, port: str, data_type: str, data: Dict[str, Any]):
        tab = self.device_tabs.get(port)

        if data_type == 'battery' and tab:
            # Update battery in wDRT config window if open
            percent = data.get('percent')
            if self.wdrt_config_window and percent is not None:
                try:
                    self.wdrt_config_window.update_battery(int(percent))
                except Exception:
                    pass  # Window may have been closed

        elif data_type == 'config' and tab:
            # Update config window if open
            if tab.device_type != DRTDeviceType.SDRT and self.wdrt_config_window:
                try:
                    self.wdrt_config_window.update_config(data)
                except Exception:
                    pass  # Window may have been closed

        elif data_type == 'click' and tab:
            value = data.get('value', '')
            try:
                click_count = int(value) if value else 0
                tab.click_count_var.set(str(click_count))
            except ValueError:
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
            value = data.get('value', '')
            try:
                state = int(value)
                self.stimulus_state[port] = state
            except (ValueError, TypeError):
                if 'on' in value.lower():
                    self.stimulus_state[port] = 1
                elif 'off' in value.lower():
                    self.stimulus_state[port] = 0

            if tab and tab.plotter:
                tab.plotter.update_stimulus_state(port, self.stimulus_state.get(port, 0))

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
