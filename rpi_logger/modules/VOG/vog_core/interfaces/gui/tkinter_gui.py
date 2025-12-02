"""VOG Tkinter GUI with device tabs and plotter."""

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING, Dict, Any, Optional

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.modules.base import TkinterGUIBase

if TYPE_CHECKING:
    from ...vog_system import VOGSystem


class VOGDeviceTab:
    """Tab widget for a single VOG device."""

    def __init__(self, parent: ttk.Frame, port: str, system: 'VOGSystem'):
        self.port = port
        self.system = system
        self.logger = get_module_logger(f"VOGDeviceTab_{port}")

        self.frame = ttk.Frame(parent)
        self.plotter = None

        self._build_ui()

    def _build_ui(self):
        """Build the device tab UI."""
        # Main container with two columns
        self.frame.columnconfigure(0, weight=1)
        self.frame.columnconfigure(1, weight=2)
        self.frame.rowconfigure(0, weight=1)

        # Left side: controls and results
        control_frame = ttk.LabelFrame(self.frame, text="Controls", padding=10)
        control_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        # Peek buttons
        btn_frame = ttk.Frame(control_frame)
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

        self.config_btn = ttk.Button(
            btn_frame,
            text="Configure",
            command=self._on_configure
        )
        self.config_btn.pack(side=tk.LEFT, padx=2)

        # Results display
        results_frame = ttk.LabelFrame(control_frame, text="Last Trial", padding=5)
        results_frame.pack(fill=tk.BOTH, expand=True, pady=10)

        # Trial number
        ttk.Label(results_frame, text="Trial:").grid(row=0, column=0, sticky="w", pady=2)
        self.trial_var = tk.StringVar(value="-")
        ttk.Label(results_frame, textvariable=self.trial_var).grid(row=0, column=1, sticky="w", pady=2)

        # Shutter open time
        ttk.Label(results_frame, text="Open (ms):").grid(row=1, column=0, sticky="w", pady=2)
        self.open_var = tk.StringVar(value="-")
        ttk.Label(results_frame, textvariable=self.open_var).grid(row=1, column=1, sticky="w", pady=2)

        # Shutter closed time
        ttk.Label(results_frame, text="Closed (ms):").grid(row=2, column=0, sticky="w", pady=2)
        self.closed_var = tk.StringVar(value="-")
        ttk.Label(results_frame, textvariable=self.closed_var).grid(row=2, column=1, sticky="w", pady=2)

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

    def _on_peek_open(self):
        """Handle peek open button."""
        if self.system:
            handler = self.system.get_device_handler(self.port)
            if handler:
                import asyncio
                asyncio.create_task(handler.peek_open())

    def _on_peek_close(self):
        """Handle peek close button."""
        if self.system:
            handler = self.system.get_device_handler(self.port)
            if handler:
                import asyncio
                asyncio.create_task(handler.peek_close())

    def _on_configure(self):
        """Handle configure button."""
        from .config_window import VOGConfigWindow
        VOGConfigWindow(self.frame.winfo_toplevel(), self.port, self.system)

    def update_data(self, data: Dict[str, Any]):
        """Update display with trial data."""
        self.trial_var.set(str(data.get('trial_number', '-')))
        self.open_var.set(str(data.get('shutter_open', '-')))
        self.closed_var.set(str(data.get('shutter_closed', '-')))

        # Update plotter
        if self.plotter:
            shutter_open = data.get('shutter_open', 0)
            shutter_closed = data.get('shutter_closed', 0)
            self.plotter.update_trial_data(self.port, shutter_open, shutter_closed)

    def update_stimulus_state(self, state: int):
        """Update plotter with stimulus state."""
        if self.plotter:
            self.plotter.update_shutter_state(self.port, state == 1)

    def cleanup(self):
        """Clean up resources."""
        if self.plotter:
            self.plotter.remove_device(self.port)


class VOGTkinterGUI(TkinterGUIBase):
    """Main VOG GUI window."""

    def __init__(self, system: 'VOGSystem', args):
        self.system = system
        self.args = args
        self.logger = get_module_logger("VOGTkinterGUI")

        # Device tabs dictionary
        self.device_tabs: Dict[str, VOGDeviceTab] = {}

        # Initialize base class (creates self.root)
        super().__init__(
            args,
            title="VOG - Visual Occlusion Glasses",
            geometry=getattr(args, 'window_geometry', '800x400'),
        )

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

    def on_device_connected(self, port: str):
        """Handle device connection - add tab."""
        self.logger.info("Device connected: %s", port)

        if port in self.device_tabs:
            return

        # Create device tab
        tab = VOGDeviceTab(self.notebook, port, self.system)
        self.notebook.add(tab.frame, text=port.split('/')[-1])

        self.device_tabs[port] = tab
        self._update_status()

    def on_device_disconnected(self, port: str):
        """Handle device disconnection - remove tab."""
        self.logger.info("Device disconnected: %s", port)

        if port in self.device_tabs:
            tab = self.device_tabs.pop(port)
            tab.cleanup()

            # Find and remove the tab from notebook
            for i in range(self.notebook.index("end")):
                if self.notebook.tab(i, "text") == port.split('/')[-1]:
                    self.notebook.forget(i)
                    break

        self._update_status()

    def on_device_data(self, port: str, data_type: str, data: Dict[str, Any]):
        """Handle data from device."""
        self.logger.debug("Data from %s: %s - %s", port, data_type, data)

        if port in self.device_tabs:
            if data_type == 'data':
                self.device_tabs[port].update_data(data)
            elif data_type == 'stimulus':
                state = data.get('state', 0)
                self.device_tabs[port].update_stimulus_state(state)

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
