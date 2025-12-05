"""DRT configuration dialog for device settings.

Supports all DRT device types (sDRT, wDRT USB, wDRT wireless) with adaptive UI.
Uses the modern dark theme styling consistent with VOG module.
"""

import tkinter as tk
from tkinter import ttk, messagebox
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
        type_label = {
            DRTDeviceType.SDRT: "sDRT",
            DRTDeviceType.WDRT_USB: "wDRT USB",
            DRTDeviceType.WDRT_WIRELESS: "wDRT Wireless",
        }.get(device_type, "DRT")

        # Window dimensions
        width, height = 380, 340

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
        self.dialog.title(f"{type_label} Configuration - {device_id}")
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

        # Device info section
        short_id = self.device_id.split('/')[-1] if '/' in self.device_id else self.device_id
        type_label = {
            DRTDeviceType.SDRT: "sDRT",
            DRTDeviceType.WDRT_USB: "wDRT USB",
            DRTDeviceType.WDRT_WIRELESS: "wDRT Wireless",
        }.get(self.device_type, "DRT")

        # Configuration section
        config_frame = ttk.LabelFrame(main_frame, text="Configuration")
        config_frame.pack(fill=tk.X, pady=(0, 10))
        config_frame.columnconfigure(1, weight=1)

        # Parameter entries
        params = [
            ("Lower ISI (ms):", 'lowerISI', "3000-5000"),
            ("Upper ISI (ms):", 'upperISI', "3000-5000"),
            ("Stimulus Duration (ms):", 'stimDur', "1000"),
            ("Intensity (%):", 'intensity', "0-100"),
        ]

        for row_idx, (label_text, key, hint) in enumerate(params):
            ttk.Label(config_frame, text=label_text, style='Inframe.TLabel').grid(
                row=row_idx, column=0, sticky="w", padx=5, pady=2)
            ttk.Entry(config_frame, textvariable=self._vars[key], width=10).grid(
                row=row_idx, column=1, sticky="e", padx=5, pady=2)

        # Separator
        ttk.Separator(config_frame, orient=tk.HORIZONTAL).grid(
            row=len(params), column=0, columnspan=2, sticky="ew", pady=5)

        # Validation hints
        hint_label = ttk.Label(
            config_frame,
            text="ISI: 0-65535ms, Duration: 0-65535ms, Intensity: 0-100%",
            style='Muted.TLabel'
        )
        hint_label.grid(row=len(params) + 1, column=0, columnspan=2, sticky="w", padx=5, pady=2)

        # Preset LabelFrame
        preset_lf = ttk.LabelFrame(main_frame, text="Presets")
        preset_lf.pack(fill=tk.X, pady=(0, 10))

        # Use tk.Frame with bg for RoundedButton
        preset_btn_frame = tk.Frame(preset_lf, bg=Colors.BG_DARKER)
        preset_btn_frame.pack(fill=tk.X, padx=5, pady=5)

        RoundedButton(
            preset_btn_frame, text="ISO Standard",
            command=self._on_iso_preset,
            width=120, height=32, style='default',
            bg=Colors.BG_DARKER
        ).pack(side=tk.LEFT, padx=2)

        # Actions LabelFrame
        actions_lf = ttk.LabelFrame(main_frame, text="Actions")
        actions_lf.pack(fill=tk.X, pady=(0, 10))

        # Use tk.Frame with bg for RoundedButtons
        action_btn_frame = tk.Frame(actions_lf, bg=Colors.BG_DARKER)
        action_btn_frame.pack(fill=tk.X, padx=5, pady=5)

        RoundedButton(
            action_btn_frame, text="Read from Device",
            command=self._on_get_config,
            width=130, height=32, style='default',
            bg=Colors.BG_DARKER
        ).pack(side=tk.LEFT, padx=2)

        RoundedButton(
            action_btn_frame, text="Upload to Device",
            command=self._on_upload,
            width=130, height=32, style='default',
            bg=Colors.BG_DARKER
        ).pack(side=tk.LEFT, padx=2)

        # Close button at bottom
        close_frame = tk.Frame(main_frame, bg=Colors.BG_DARKER)
        close_frame.pack(fill=tk.X, pady=(10, 0))

        RoundedButton(
            close_frame, text="Close",
            command=self._on_close,
            width=80, height=32, style='default',
            bg=Colors.BG_DARKER
        ).pack(side=tk.RIGHT, padx=2)

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

        except ValueError as e:
            messagebox.showerror("Validation Error", str(e), parent=self.dialog)
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
            messagebox.showinfo("Success", "Configuration uploaded to device", parent=self.dialog)

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
