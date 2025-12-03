"""VOG Tkinter GUI with device tabs and plotter.

Supports both sVOG (wired) and wVOG (wireless) devices with adaptive UI.
wVOG devices get dual lens controls (A/B/X) and battery display.
"""

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING, Dict, Any, Optional

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.modules.base import TkinterGUIBase

if TYPE_CHECKING:
    from ...vog_system import VOGSystem


class VOGDeviceTab:
    """Tab widget for a single VOG device.

    Adapts UI based on device type:
    - sVOG: Single peek open/close buttons
    - wVOG: Dual lens controls (A/B/X) + battery display
    """

    def __init__(self, parent: ttk.Frame, port: str, system: 'VOGSystem', device_type: str = 'svog'):
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
        type_label = self.device_type.upper()
        ttk.Label(type_frame, text=f"Device: {type_label}", font=('TkDefaultFont', 9, 'bold')).pack(side=tk.LEFT)

        # Build appropriate controls based on device type
        if self.device_type == 'wvog':
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
        if self.device_type == 'wvog':
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
        """Build wVOG-specific controls (dual lens + battery)."""
        # Battery display
        battery_frame = ttk.Frame(parent)
        battery_frame.pack(fill=tk.X, pady=2)
        ttk.Label(battery_frame, text="Battery:").pack(side=tk.LEFT)
        self._battery_label = ttk.Label(battery_frame, text="---%")
        self._battery_label.pack(side=tk.LEFT, padx=5)

        # Lens selector
        lens_frame = ttk.LabelFrame(parent, text="Lens Control", padding=5)
        lens_frame.pack(fill=tk.X, pady=5)

        self._lens_var = tk.StringVar(value="X")
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
        VOGConfigWindow(self.frame.winfo_toplevel(), self.port, self.system, self.device_type)

    def update_data(self, data: Dict[str, Any]):
        """Update display with trial data."""
        self.trial_var.set(str(data.get('trial_number', '-')))
        self.open_var.set(str(data.get('shutter_open', '-')))
        self.closed_var.set(str(data.get('shutter_closed', '-')))

        # wVOG-specific data
        if self.device_type == 'wvog':
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
        """Update battery display (wVOG only)."""
        if self._battery_label:
            self._battery_label.config(text=f"{percent}%")

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

    def on_device_connected(self, port: str):
        """Handle device connection - add tab."""
        self.logger.info("Device connected: %s", port)

        if port in self.device_tabs:
            return

        # Determine device type from handler
        device_type = 'svog'
        handler = self.system.get_device_handler(port)
        if handler:
            device_type = handler.device_type

        # Create device tab with appropriate type
        tab = VOGDeviceTab(self.notebook, port, self.system, device_type)

        # Tab text shows device type
        tab_text = f"{port.split('/')[-1]} ({device_type.upper()})"
        self.notebook.add(tab.frame, text=tab_text)

        self.device_tabs[port] = tab
        self._update_status()

    def on_device_disconnected(self, port: str):
        """Handle device disconnection - remove tab."""
        self.logger.info("Device disconnected: %s", port)

        if port in self.device_tabs:
            tab = self.device_tabs.pop(port)
            tab.cleanup()

            # Find and remove the tab from notebook
            # Tab text format: "portname (TYPE)"
            port_short = port.split('/')[-1]
            for i in range(self.notebook.index("end")):
                tab_text = self.notebook.tab(i, "text")
                if tab_text.startswith(port_short):
                    self.notebook.forget(i)
                    break

        self._update_status()

    def on_device_data(self, port: str, data_type: str, data: Dict[str, Any]):
        """Handle data from device."""
        self.logger.debug("Data from %s: %s - %s", port, data_type, data)

        if port in self.device_tabs:
            tab = self.device_tabs[port]
            if data_type == 'data':
                tab.update_data(data)
            elif data_type == 'stimulus':
                state = data.get('state', 0)
                tab.update_stimulus_state(state)
            elif data_type == 'battery':
                percent = data.get('percent', 0)
                tab.update_battery(percent)

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
