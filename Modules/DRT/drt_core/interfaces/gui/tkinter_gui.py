import asyncio
import logging
import tkinter as tk
from tkinter import ttk, scrolledtext
from typing import TYPE_CHECKING, Optional, Dict, Any
from collections import deque
from pathlib import Path

from Modules.base import TkinterGUIBase, TkinterMenuBase
from .drt_plotter import DRTPlotter
from .sdrt_config_window import SDRTConfigWindow
from .quick_status_panel import QuickStatusPanel

if TYPE_CHECKING:
    from ...drt_system import DRTSystem

logger = logging.getLogger("TkinterGUI")


class DeviceTab:
    def __init__(self, port: str, parent_frame: tk.Frame):
        self.port = port
        self.frame = parent_frame
        self.plotter: Optional[DRTPlotter] = None

        self.trial_number_var = tk.StringVar(value="0")
        self.reaction_time_var = tk.StringVar(value="-1")
        self.click_count_var = tk.StringVar(value="0")

        self.stim_on_button: Optional[ttk.Button] = None
        self.stim_off_button: Optional[ttk.Button] = None
        self.configure_button: Optional[ttk.Button] = None


class TkinterGUI(TkinterGUIBase, TkinterMenuBase):

    def __init__(self, drt_system: 'DRTSystem', args):
        self.system = drt_system
        self.args = args
        self.async_bridge = None

        self.notebook: Optional[ttk.Notebook] = None
        self.device_tabs: Dict[str, DeviceTab] = {}
        self.empty_state_label: Optional[ttk.Label] = None

        self.stimulus_state: Dict[str, int] = {}
        self.config_window: Optional[SDRTConfigWindow] = None
        self.quick_panel: Optional[QuickStatusPanel] = None
        self.devices_panel_visible_var = None

        self.initialize_gui_framework(
            title="DRT Monitor",
            default_width=800,
            default_height=600,
            menu_bar_kwargs={'include_sources': False}
        )

        self.config_window = None

    def set_close_handler(self, handler):
        self.root.protocol("WM_DELETE_WINDOW", handler)

    def on_start_recording(self):
        self._start_recording()

    def on_stop_recording(self):
        self._stop_recording()

    def _create_widgets(self):
        content_frame = self.create_standard_layout(logger_height=2, content_title="DRT Controls")

        main_frame = content_frame.master
        if main_frame is not None:
            main_frame.columnconfigure(0, weight=1)
            main_frame.rowconfigure(0, weight=1)
            main_frame.rowconfigure(1, weight=0)
            main_frame.rowconfigure(2, weight=0)

        content_frame.columnconfigure(0, weight=1)
        content_frame.rowconfigure(0, weight=1)

        notebook_container = ttk.Frame(content_frame)
        notebook_container.grid(row=0, column=0, sticky='nsew', padx=5, pady=(5, 0))
        notebook_container.columnconfigure(0, weight=1)
        notebook_container.rowconfigure(0, weight=1)

        self.notebook = ttk.Notebook(notebook_container, width=160)
        self.notebook.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)

        self.empty_state_label = ttk.Label(
            notebook_container,
            text="⚠ No sDRT devices connected\n\nPlease connect a device to begin",
            font=('TkDefaultFont', 12),
            justify='center',
            foreground='gray'
        )
        self.empty_state_label.grid(row=0, column=0, sticky='nsew', padx=20, pady=20)
        self.empty_state_label.lift()

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

        if hasattr(self, 'log_frame') and self.log_frame.winfo_manager():
            self.log_frame.grid_configure(row=2, column=0, sticky='ew')

        self.quick_panel = QuickStatusPanel(io_frame)
        self.quick_panel.build(container=io_frame)

    def _create_device_tab(self, port: str) -> DeviceTab:
        tab_frame = ttk.Frame(self.notebook)
        tab = DeviceTab(port, tab_frame)

        tab_frame.columnconfigure(0, weight=1)
        tab_frame.rowconfigure(3, weight=1)

        tab.plotter = DRTPlotter(tab_frame)
        tab.plotter.add_device(port)

        stimulus_frame = ttk.LabelFrame(tab_frame, text="Stimulus", padding=(10, 5))
        stimulus_frame.grid(row=1, column=1, sticky='nsew', padx=5, pady=5)
        stimulus_frame.columnconfigure(0, weight=1)
        stimulus_frame.columnconfigure(1, weight=1)

        tab.stim_on_button = ttk.Button(stimulus_frame, text="ON",
                                        command=lambda: self._on_stimulus_on(port))
        tab.stim_on_button.grid(row=0, column=0, sticky='nsew', padx=2)

        tab.stim_off_button = ttk.Button(stimulus_frame, text="OFF",
                                         command=lambda: self._on_stimulus_off(port))
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
                                         command=lambda: self._on_configure(port), width=25)
        tab.configure_button.grid(row=0, column=0, sticky='nsew')

        tab_label = f"{port}"
        self.notebook.add(tab_frame, text=tab_label)

        return tab

    def _start_recording(self):
        if self.async_bridge:
            self.async_bridge.run_coroutine(self._start_recording_async())
        else:
            logger.error("No async_bridge available to start recording")

    async def _start_recording_async(self):
        if await self.system.start_recording():
            self.sync_recording_state()
            for tab in self.device_tabs.values():
                if tab.plotter:
                    tab.plotter.start_recording()
            logger.info("Recording started")
        else:
            logger.error("Failed to start recording")

    def _stop_recording(self):
        if self.async_bridge:
            self.async_bridge.run_coroutine(self._stop_recording_async())
        else:
            logger.error("No async_bridge available to stop recording")

    async def _stop_recording_async(self):
        if await self.system.stop_recording():
            self.sync_recording_state()
            for tab in self.device_tabs.values():
                if tab.plotter:
                    tab.plotter.stop_recording()
            logger.info("Recording stopped")
        else:
            logger.error("Failed to stop recording")

    def _on_stimulus_on(self, port: str):
        handler = self.system.get_device_handler(port)
        if handler:
            logger.info(f"Stimulus ON button pressed for {port}")

            if self.async_bridge:
                self.async_bridge.run_coroutine(handler.set_stimulus(True))
            else:
                logger.error("No async_bridge available to send command")

            self.stimulus_state[port] = 1
            if port in self.device_tabs and self.device_tabs[port].plotter:
                self.device_tabs[port].plotter.update_stimulus_state(port, 1)
            logger.info(f"Stimulus ON scheduled for {port}")

    def _on_stimulus_off(self, port: str):
        handler = self.system.get_device_handler(port)
        if handler:
            logger.info(f"Stimulus OFF button pressed for {port}")

            if self.async_bridge:
                self.async_bridge.run_coroutine(handler.set_stimulus(False))
            else:
                logger.error("No async_bridge available to send command")

            self.stimulus_state[port] = 0
            if port in self.device_tabs and self.device_tabs[port].plotter:
                self.device_tabs[port].plotter.update_stimulus_state(port, 0)
            logger.info(f"Stimulus OFF scheduled for {port}")

    def _on_configure(self, port: str):
        if not self.config_window:
            self.config_window = SDRTConfigWindow(self.system, self.async_bridge)
        self.config_window.show_for_device(port)

    def on_device_connected(self, port: str):
        try:
            if port not in self.device_tabs:
                tab = self._create_device_tab(port)
                self.device_tabs[port] = tab

            if self.empty_state_label and self.device_tabs:
                self.empty_state_label.grid_remove()
                self.notebook.lift()

            if self.quick_panel:
                self.quick_panel.device_connected(port)
                if not self.system.recording:
                    self.quick_panel.set_module_state("Ready")
        except Exception as e:
            logger.error(f"Error in on_device_connected: {e}", exc_info=True)

    def on_device_disconnected(self, port: str):
        logger.info(f"GUI: Device disconnected from {port}")

        if port in self.device_tabs:
            tab = self.device_tabs[port]

            for idx in range(self.notebook.index("end")):
                if self.notebook.tab(idx, "text") == port:
                    self.notebook.forget(idx)
                    break

            del self.device_tabs[port]
            logger.info(f"Removed tab for device {port}")

        if self.empty_state_label and not self.device_tabs:
            self.empty_state_label.grid(row=0, column=0, sticky='nsew', padx=20, pady=20)
            self.empty_state_label.lift()

        if self.quick_panel:
            self.quick_panel.device_disconnected(port)
            if not self.device_tabs and not self.system.recording:
                self.quick_panel.set_module_state("Idle")

    def on_device_data(self, port: str, data_type: str, data: Dict[str, Any]):
        tab = self.device_tabs.get(port)

        if data_type == 'click' and tab:
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
        if recording:
            self.root.title(f"{base_title} - RECORDING")
        else:
            self.root.title(base_title)

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
        from Modules.base import gui_utils

        config_path = gui_utils.get_module_config_path(Path(__file__))
        gui_utils.save_window_geometry(self.root, config_path)
