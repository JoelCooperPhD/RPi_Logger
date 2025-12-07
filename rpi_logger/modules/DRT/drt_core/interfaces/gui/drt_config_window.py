"""DRT configuration dialog for device settings.

Supports all DRT device types (sDRT, wDRT USB, wDRT wireless) with adaptive UI.
Uses the modern dark theme styling consistent with VOG module.
"""

import tkinter as tk
from tkinter import ttk
from typing import Optional, Dict, Any, Callable
from pathlib import Path

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.core.ui.theme.styles import Theme
from rpi_logger.core.ui.theme.colors import Colors
from rpi_logger.core.ui.theme.widgets import RoundedButton
from rpi_logger.modules.base import ConfigLoader

from ...device_types import DRTDeviceType


class DRTConfigWindow:
    """Modal dialog for configuring DRT device settings.

    Features:
    - Parameter configuration (ISI, stimulus duration, intensity)
    - ISO standard preset button
    - Read from device / Upload to device
    - Works for sDRT, wDRT USB, and wDRT wireless
    - Position persistence in config file
    """

    # Config key for saving dialog position
    CONFIG_DIALOG_GEOMETRY_KEY = "config_dialog_geometry"

    def __init__(
        self,
        parent: tk.Widget,
        device_id: str,
        device_type: DRTDeviceType = DRTDeviceType.SDRT,
        on_upload: Optional[Callable[[Dict[str, int]], None]] = None,
        on_iso_preset: Optional[Callable[[], None]] = None,
        on_get_config: Optional[Callable[[], None]] = None,
        **kwargs
    ):
        """Initialize the configuration window.

        Args:
            parent: Parent widget
            device_id: Device identifier for title
            device_type: Type of DRT device
            on_upload: Callback when uploading config (receives dict of params)
            on_iso_preset: Callback to set ISO preset
            on_get_config: Callback to request config from device
            **kwargs: Additional toplevel options
        """
        self.device_id = device_id
        self.device_type = device_type
        self.on_upload = on_upload
        self.on_iso_preset = on_iso_preset
        self.on_get_config = on_get_config
        self.logger = get_module_logger("DRTConfigWindow")
        self._config_path = Path(__file__).parent.parent.parent.parent / "config.txt"

        # Determine device type label
        type_prefix = {
            DRTDeviceType.SDRT: "DRT-USB",
            DRTDeviceType.WDRT_USB: "DRT-USB",
            DRTDeviceType.WDRT_WIRELESS: "DRT-XB",
        }.get(device_type, "DRT")

        # Extract short port name (e.g., "ACM1" from "/dev/ttyACM1")
        short_port = device_id.split('/')[-1].replace('tty', '') if '/' in device_id else device_id

        # Window dimensions
        width, height = 265, 255

        # Calculate position before creating dialog
        saved_pos = self._load_saved_position_static()
        if saved_pos:
            x, y = saved_pos
        else:
            # Center on parent
            x = parent.winfo_x() + (parent.winfo_width() - width) // 2
            y = parent.winfo_y() + (parent.winfo_height() - height) // 2

        # Create modal dialog with full geometry (size + position) immediately
        self.dialog = tk.Toplevel(parent)
        self.dialog.geometry(f"{width}x{height}+{x}+{y}")
        self.dialog.title(f"{type_prefix}:{short_port}")
        self.dialog.resizable(False, False)
        self.dialog.transient(parent)
        self.dialog.grab_set()
        Theme.configure_toplevel(self.dialog)

        # Variables for entry fields
        self._vars = {
            'lowerISI': tk.StringVar(value="3000"),
            'upperISI': tk.StringVar(value="5000"),
            'stimDur': tk.StringVar(value="1000"),
            'intensity': tk.StringVar(value="100"),
        }

        self._loading = False
        self._build_ui()

        # Register close handler to clean up and save position
        self.dialog.protocol("WM_DELETE_WINDOW", self._on_close)

        # Request current config
        if self.on_get_config:
            self.dialog.after(100, self.on_get_config)

    def _build_ui(self) -> None:
        """Create the window widgets."""
        # Main container with padding
        main_frame = ttk.Frame(self.dialog, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Runtime Parameters LabelFrame
        params_lf = ttk.LabelFrame(main_frame, text="Runtime Parameters")
        params_lf.pack(fill=tk.X, pady=(0, 5))
        params_lf.columnconfigure(1, weight=1)

        # Parameter entries (order matches RS_Logger: Upper, Lower, Duration, Intensity)
        params = [
            ("Upper ISI (ms):", 'upperISI'),
            ("Lower ISI (ms):", 'lowerISI'),
            ("Stimulus Duration (ms):", 'stimDur'),
            ("Stimulus Intensity (%):", 'intensity'),
        ]

        for row_idx, (label_text, key) in enumerate(params):
            ttk.Label(params_lf, text=label_text, style='Inframe.TLabel').grid(
                row=row_idx, column=0, sticky="w", padx=5, pady=1)
            ttk.Entry(params_lf, textvariable=self._vars[key], width=7).grid(
                row=row_idx, column=2, sticky="w", padx=5, pady=1)

        # Buttons frame (inside Runtime Parameters frame)
        btn_frame = tk.Frame(params_lf, bg=Colors.BG_DARKER)
        btn_frame.grid(row=len(params), column=0, columnspan=3, sticky="ew", padx=10, pady=(10, 10))

        # Upload Custom button
        RoundedButton(
            btn_frame, text="Upload Custom",
            command=self._on_upload,
            width=195, height=32, style='default',
            bg=Colors.BG_DARKER
        ).pack(anchor=tk.CENTER, pady=(5, 5))

        # Upload ISO button
        RoundedButton(
            btn_frame, text="Upload ISO",
            command=self._on_iso_preset,
            width=195, height=32, style='default',
            bg=Colors.BG_DARKER
        ).pack(anchor=tk.CENTER, pady=(0, 5))

    def _load_saved_position_static(self) -> Optional[tuple]:
        """Load saved dialog position from config file.

        Returns:
            Tuple of (x, y) coordinates or None if not found.
        """
        try:
            if not self._config_path.exists():
                return None
            config = ConfigLoader.load(self._config_path, defaults={}, strict=False)
            geometry = config.get(self.CONFIG_DIALOG_GEOMETRY_KEY, "")
            if geometry and "+" in geometry:
                # Parse "+x+y" format
                parts = geometry.split("+")
                if len(parts) >= 3:
                    x = int(parts[1])
                    y = int(parts[2])
                    return (x, y)
        except Exception:
            pass
        return None

    def _save_position(self):
        """Save current dialog position to config file."""
        try:
            if not self._config_path.exists():
                return
            geometry = self.dialog.geometry()
            # Extract just the position part (+x+y)
            if "+" in geometry:
                pos_start = geometry.index("+")
                position = geometry[pos_start:]  # e.g., "+100+200"
                ConfigLoader.update_config_values(
                    self._config_path,
                    {self.CONFIG_DIALOG_GEOMETRY_KEY: position}
                )
                self.logger.debug("Saved config dialog position: %s", position)
        except Exception as e:
            self.logger.debug("Could not save position: %s", e)

    def _on_close(self):
        """Handle dialog close."""
        self._save_position()
        self.dialog.destroy()

    def _validate_inputs(self) -> Optional[Dict[str, int]]:
        """Validate input values.

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

        except ValueError:
            return None

    def _filter_value(
        self,
        value: str,
        default: int,
        min_val: int,
        max_val: int
    ) -> int:
        """Filter and validate a numeric value.

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
            self._clear_fields()

    def _on_iso_preset(self) -> None:
        """Handle ISO preset button click."""
        # Send ISO preset to device if callback available
        if self.on_iso_preset:
            self.on_iso_preset()
        self._clear_fields()

    def _clear_fields(self) -> None:
        """Clear all input fields."""
        for var in self._vars.values():
            var.set("")

    def _on_get_config(self) -> None:
        """Handle get config button click."""
        if self.on_get_config:
            self.on_get_config()

    def update_config(self, config: Dict[str, Any]) -> None:
        """Update the displayed configuration.

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
