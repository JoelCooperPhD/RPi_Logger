"""
wDRT Configuration Window

Configuration dialog for wDRT devices.
Allows setting stimulus parameters, viewing battery status, and syncing RTC.
"""

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional, Dict, Any, Callable
from math import ceil
import logging

from .battery_widget import BatteryWidget

logger = logging.getLogger(__name__)


class WDRTConfigWindow(tk.Toplevel):
    """
    Configuration window for wDRT devices.

    Features:
    - Parameter configuration (ISI, stimulus duration, intensity)
    - ISO standard preset button
    - Battery status display
    - RTC synchronization button
    - Real-time config display from device
    """

    def __init__(
        self,
        parent: tk.Widget,
        device_id: str,
        on_upload: Optional[Callable[[Dict[str, int]], None]] = None,
        on_iso_preset: Optional[Callable[[], None]] = None,
        on_rtc_sync: Optional[Callable[[], None]] = None,
        on_get_config: Optional[Callable[[], None]] = None,
        on_get_battery: Optional[Callable[[], None]] = None,
        **kwargs
    ):
        """
        Initialize the configuration window.

        Args:
            parent: Parent widget
            device_id: Device identifier for title
            on_upload: Callback when uploading config (receives dict of params)
            on_iso_preset: Callback to set ISO preset
            on_rtc_sync: Callback to sync RTC
            on_get_config: Callback to request config from device
            on_get_battery: Callback to request battery status
            **kwargs: Additional toplevel options
        """
        super().__init__(parent, **kwargs)

        self.device_id = device_id
        self.on_upload = on_upload
        self.on_iso_preset = on_iso_preset
        self.on_rtc_sync = on_rtc_sync
        self.on_get_config = on_get_config
        self.on_get_battery = on_get_battery

        # Window setup
        self.title(f"wDRT Configuration - {device_id}")
        self.geometry("400x450")
        self.resizable(False, False)

        # Make modal
        self.transient(parent)
        self.grab_set()

        # Variables for entry fields
        self._vars = {
            'lowerISI': tk.StringVar(value="3000"),
            'upperISI': tk.StringVar(value="5000"),
            'stimDur': tk.StringVar(value="1000"),
            'intensity': tk.StringVar(value="100"),
        }

        self._create_widgets()

        # Request current config
        if self.on_get_config:
            self.after(100, self.on_get_config)
        if self.on_get_battery:
            self.after(200, self.on_get_battery)

    def _create_widgets(self) -> None:
        """Create the window widgets."""
        # Main container with padding
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Device info section
        info_frame = ttk.LabelFrame(main_frame, text="Device Info", padding="5")
        info_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(info_frame, text=f"Device: {self.device_id}").pack(anchor=tk.W)

        # Battery display
        battery_frame = ttk.Frame(info_frame)
        battery_frame.pack(fill=tk.X, pady=(5, 0))
        ttk.Label(battery_frame, text="Battery:").pack(side=tk.LEFT)
        self._battery_widget = BatteryWidget(battery_frame, width=100, height=20)
        self._battery_widget.pack(side=tk.LEFT, padx=(5, 0))

        refresh_btn = ttk.Button(
            battery_frame,
            text="Refresh",
            width=8,
            command=self._on_refresh_battery
        )
        refresh_btn.pack(side=tk.RIGHT)

        # Configuration section
        config_frame = ttk.LabelFrame(main_frame, text="Stimulus Configuration", padding="5")
        config_frame.pack(fill=tk.X, pady=(0, 10))

        # Parameter entries
        params = [
            ("Lower ISI (ms):", 'lowerISI', "Minimum inter-stimulus interval"),
            ("Upper ISI (ms):", 'upperISI', "Maximum inter-stimulus interval"),
            ("Stimulus Duration (ms):", 'stimDur', "How long stimulus stays on"),
            ("Intensity (%):", 'intensity', "Stimulus brightness (0-100)"),
        ]

        for label_text, key, tooltip in params:
            row = ttk.Frame(config_frame)
            row.pack(fill=tk.X, pady=2)

            label = ttk.Label(row, text=label_text, width=20, anchor=tk.W)
            label.pack(side=tk.LEFT)

            entry = ttk.Entry(row, textvariable=self._vars[key], width=10)
            entry.pack(side=tk.LEFT, padx=(5, 0))

            # Tooltip/hint
            hint = ttk.Label(row, text=f"({tooltip})", foreground='gray')
            hint.pack(side=tk.LEFT, padx=(10, 0))

        # Validation hints
        hint_label = ttk.Label(
            config_frame,
            text="Valid ranges: ISI 0-65535ms, Duration 0-65535ms, Intensity 0-100%",
            foreground='gray',
            font=('TkDefaultFont', 8)
        )
        hint_label.pack(anchor=tk.W, pady=(5, 0))

        # Buttons section
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(0, 10))

        # ISO Preset button
        iso_btn = ttk.Button(
            button_frame,
            text="Load ISO Preset",
            command=self._on_iso_preset
        )
        iso_btn.pack(side=tk.LEFT, padx=(0, 5))

        # Get Config button
        get_btn = ttk.Button(
            button_frame,
            text="Read from Device",
            command=self._on_get_config
        )
        get_btn.pack(side=tk.LEFT, padx=(0, 5))

        # Upload button
        upload_btn = ttk.Button(
            button_frame,
            text="Upload to Device",
            command=self._on_upload
        )
        upload_btn.pack(side=tk.LEFT)

        # RTC section
        rtc_frame = ttk.LabelFrame(main_frame, text="Real-Time Clock", padding="5")
        rtc_frame.pack(fill=tk.X, pady=(0, 10))

        rtc_info = ttk.Label(
            rtc_frame,
            text="Sync the device's clock with your computer's time."
        )
        rtc_info.pack(anchor=tk.W)

        sync_btn = ttk.Button(
            rtc_frame,
            text="Sync RTC Now",
            command=self._on_rtc_sync
        )
        sync_btn.pack(anchor=tk.W, pady=(5, 0))

    def _validate_inputs(self) -> Optional[Dict[str, int]]:
        """
        Validate input values.

        Returns:
            Dict of validated values, or None if validation failed
        """
        try:
            lower_isi = self._filter_value(
                self._vars['lowerISI'].get(), 3000, 0, 65535
            )
            upper_isi = self._filter_value(
                self._vars['upperISI'].get(), 5000, lower_isi, 65535
            )
            stim_dur = self._filter_value(
                self._vars['stimDur'].get(), 1000, 0, 65535
            )
            intensity = self._filter_value(
                self._vars['intensity'].get(), 100, 0, 100
            )

            # Update vars with validated values
            self._vars['lowerISI'].set(str(lower_isi))
            self._vars['upperISI'].set(str(upper_isi))
            self._vars['stimDur'].set(str(stim_dur))
            self._vars['intensity'].set(str(intensity))

            return {
                'lowerISI': lower_isi,
                'upperISI': upper_isi,
                'stimDur': stim_dur,
                'intensity': intensity,
            }

        except ValueError as e:
            messagebox.showerror("Validation Error", str(e))
            return None

    def _filter_value(
        self,
        value: str,
        default: int,
        min_val: int,
        max_val: int
    ) -> int:
        """
        Filter and validate a numeric value.

        Args:
            value: String value to parse
            default: Default if empty or invalid
            min_val: Minimum allowed value
            max_val: Maximum allowed value

        Returns:
            Validated integer value
        """
        try:
            val = int(value) if value.strip() else default
            return max(min_val, min(max_val, val))
        except ValueError:
            return default

    def _on_upload(self) -> None:
        """Handle upload button click."""
        params = self._validate_inputs()
        if params and self.on_upload:
            self.on_upload(params)
            messagebox.showinfo("Success", "Configuration uploaded to device")

    def _on_iso_preset(self) -> None:
        """Handle ISO preset button click."""
        # Set ISO values in fields
        self._vars['lowerISI'].set("3000")
        self._vars['upperISI'].set("5000")
        self._vars['stimDur'].set("1000")
        self._vars['intensity'].set("100")

        # Also send to device if callback available
        if self.on_iso_preset:
            self.on_iso_preset()

    def _on_get_config(self) -> None:
        """Handle get config button click."""
        if self.on_get_config:
            self.on_get_config()

    def _on_rtc_sync(self) -> None:
        """Handle RTC sync button click."""
        if self.on_rtc_sync:
            self.on_rtc_sync()
            messagebox.showinfo("Success", "RTC synchronized with host time")

    def _on_refresh_battery(self) -> None:
        """Handle battery refresh button click."""
        if self.on_get_battery:
            self.on_get_battery()

    def update_config(self, config: Dict[str, Any]) -> None:
        """
        Update the displayed configuration.

        Args:
            config: Configuration dict from device
        """
        if 'lowerISI' in config:
            self._vars['lowerISI'].set(str(config['lowerISI']))
        if 'upperISI' in config:
            self._vars['upperISI'].set(str(config['upperISI']))
        if 'stimDur' in config:
            self._vars['stimDur'].set(str(config['stimDur']))
        if 'intensity' in config:
            # Convert from 0-255 to percentage if needed
            intensity = int(config['intensity'])
            if intensity > 100:
                intensity = int(intensity / 2.55)
            self._vars['intensity'].set(str(intensity))

    def update_battery(self, percent: int) -> None:
        """
        Update the battery display.

        Args:
            percent: Battery percentage (0-100)
        """
        self._battery_widget.set_percent(percent)
