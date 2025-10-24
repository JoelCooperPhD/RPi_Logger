import asyncio
import logging
import tkinter as tk
from tkinter import ttk, scrolledtext
from typing import TYPE_CHECKING, Optional, Dict, Any
from collections import deque

from Modules.base import TkinterGUIBase, TkinterMenuBase
from .drt_plotter import DRTPlotter
from .sdrt_config_window import SDRTConfigWindow

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

        self.notebook: Optional[ttk.Notebook] = None
        self.device_tabs: Dict[str, DeviceTab] = {}

        self.stimulus_state: Dict[str, int] = {}
        self.config_window: Optional[SDRTConfigWindow] = None

        self.initialize_gui_framework(
            title="DRT Monitor",
            default_width=800,
            default_height=600,
            menu_bar_kwargs={'include_sources': False}
        )

        self.config_window = SDRTConfigWindow(self.system)

    def set_close_handler(self, handler):
        self.root.protocol("WM_DELETE_WINDOW", handler)

    def on_start_recording(self):
        self._start_recording()

    def on_stop_recording(self):
        self._stop_recording()

    def _create_widgets(self):
        content_frame = self.create_standard_layout(logger_height=2, content_title="sDRT Monitor")

        content_frame.columnconfigure(0, weight=1)
        content_frame.rowconfigure(0, weight=1)

        self.notebook = ttk.Notebook(content_frame, width=160)
        self.notebook.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)

    def _create_device_tab(self, port: str) -> DeviceTab:
        tab_frame = tk.Frame(self.notebook)
        tab = DeviceTab(port, tab_frame)

        tab_frame.columnconfigure(0, weight=1)
        tab_frame.rowconfigure(3, weight=1)

        tab.plotter = DRTPlotter(tab_frame)
        tab.plotter.add_device(port)

        stimulus_frame = tk.LabelFrame(tab_frame, text="Stimulus", padx=10, pady=5)
        stimulus_frame.grid(row=1, column=1, sticky='nsew', padx=5, pady=5)
        stimulus_frame.columnconfigure(0, weight=1)
        stimulus_frame.columnconfigure(1, weight=1)

        tab.stim_on_button = ttk.Button(stimulus_frame, text="ON",
                                        command=lambda: self._on_stimulus_on(port))
        tab.stim_on_button.grid(row=0, column=0, sticky='nsew', padx=2)

        tab.stim_off_button = ttk.Button(stimulus_frame, text="OFF",
                                         command=lambda: self._on_stimulus_off(port))
        tab.stim_off_button.grid(row=0, column=1, sticky='nsew', padx=2)

        results_frame = tk.LabelFrame(tab_frame, text="Results", padx=10, pady=5)
        results_frame.grid(row=4, column=1, sticky='nsew', padx=5, pady=5)
        results_frame.columnconfigure(0, weight=0)
        results_frame.columnconfigure(1, weight=1)

        tk.Label(results_frame, text="Trial Number:", anchor='w').grid(row=0, column=0, sticky='w', pady=2)
        tk.Label(results_frame, textvariable=tab.trial_number_var, anchor='e').grid(row=0, column=1, sticky='e', pady=2)

        tk.Label(results_frame, text="Reaction Time:", anchor='w').grid(row=1, column=0, sticky='w', pady=2)
        tk.Label(results_frame, textvariable=tab.reaction_time_var, anchor='e').grid(row=1, column=1, sticky='e', pady=2)

        tk.Label(results_frame, text="Response Count:", anchor='w').grid(row=2, column=0, sticky='w', pady=2)
        tk.Label(results_frame, textvariable=tab.click_count_var, anchor='e').grid(row=2, column=1, sticky='e', pady=2)

        configure_frame = tk.Frame(tab_frame)
        configure_frame.grid(row=5, column=1, sticky='nsew', padx=5, pady=5)
        configure_frame.columnconfigure(0, weight=1)

        tab.configure_button = ttk.Button(configure_frame, text="Configure Unit",
                                         command=lambda: self._on_configure(port), width=25)
        tab.configure_button.grid(row=0, column=0, sticky='nsew')

        tab_label = f"{port}"
        self.notebook.add(tab_frame, text=tab_label)

        return tab

    def _start_recording(self):
        asyncio.create_task(self._start_recording_async())

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
        asyncio.create_task(self._stop_recording_async())

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
            asyncio.create_task(handler.set_stimulus(True))
            self.stimulus_state[port] = 1
            if port in self.device_tabs and self.device_tabs[port].plotter:
                self.device_tabs[port].plotter.update_stimulus_state(port, 1)
            logger.info(f"Stimulus ON for {port}")

    def _on_stimulus_off(self, port: str):
        handler = self.system.get_device_handler(port)
        if handler:
            asyncio.create_task(handler.set_stimulus(False))
            self.stimulus_state[port] = 0
            if port in self.device_tabs and self.device_tabs[port].plotter:
                self.device_tabs[port].plotter.update_stimulus_state(port, 0)
            logger.info(f"Stimulus OFF for {port}")

    def _on_configure(self, port: str):
        if self.config_window:
            self.config_window.show_for_device(port)
        else:
            logger.warning("Config window not available")

    def on_device_connected(self, port: str):
        logger.info(f"GUI: Device connected on {port}")

        if port not in self.device_tabs:
            tab = self._create_device_tab(port)
            self.device_tabs[port] = tab
            logger.info(f"Created tab for device {port}")

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

    def on_device_data(self, port: str, data_type: str, data: Dict[str, Any]):
        if port not in self.device_tabs:
            return

        tab = self.device_tabs[port]

        if data_type == 'click':
            value = data.get('value', '')
            try:
                click_count = int(value) if value else 0
                tab.click_count_var.set(str(click_count))
            except ValueError:
                pass

        elif data_type == 'trial':
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

        elif data_type == 'stimulus':
            value = data.get('value', '')
            try:
                state = int(value)
                self.stimulus_state[port] = state
            except (ValueError, TypeError):
                if 'on' in value.lower():
                    self.stimulus_state[port] = 1
                elif 'off' in value.lower():
                    self.stimulus_state[port] = 0

            if tab.plotter:
                tab.plotter.update_stimulus_state(port, self.stimulus_state.get(port, 0))

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
