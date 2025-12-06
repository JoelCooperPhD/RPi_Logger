"""GPS configuration dialog.

Provides a configuration dialog for GPS module settings,
following the VOG/DRT config window pattern.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

try:
    import tkinter as tk
    from tkinter import ttk, messagebox
    HAS_TK = True
except ImportError:
    HAS_TK = False
    tk = None
    ttk = None
    messagebox = None

try:
    from rpi_logger.core.ui.theme.colors import Colors
    from rpi_logger.core.ui.theme.widgets import RoundedButton
    HAS_THEME = True
except ImportError:
    HAS_THEME = False
    Colors = None
    RoundedButton = None


class GPSConfigWindow:
    """Configuration dialog for GPS device settings."""

    # Baud rate options for GPS devices
    BAUD_RATES = [4800, 9600, 19200, 38400, 57600, 115200]

    # Update rates (Hz) for GPS devices that support it
    UPDATE_RATES = [1, 5, 10]

    def __init__(
        self,
        parent: tk.Widget,
        port: str,
        system: Any,
        *,
        async_bridge: Optional[Any] = None,
        logger: Optional[logging.Logger] = None,
    ):
        """Initialize the GPS configuration window.

        Args:
            parent: Parent tkinter widget
            port: Serial port path
            system: GPS runtime system reference
            async_bridge: Optional async bridge for coroutine scheduling
            logger: Optional logger instance
        """
        if not HAS_TK:
            return

        self.port = port
        self.system = system
        self.async_bridge = async_bridge
        self.logger = logger or logging.getLogger(__name__)

        # Get current settings from system
        current_baud = getattr(system, 'baud_rate', 9600)

        # Create dialog window
        self.dialog = tk.Toplevel(parent)
        self.dialog.title(f"GPS Configuration - {port.split('/')[-1]}")
        self.dialog.transient(parent)
        self.dialog.grab_set()

        # Apply theme
        if HAS_THEME and Colors is not None:
            self.dialog.configure(bg=Colors.BG_DARK)

        # Size and position
        self.dialog.geometry("320x400")
        self.dialog.resizable(False, False)

        # Center on parent
        self._center_on_parent(parent)

        # Build UI
        self._build_ui(current_baud)

        # Handle close
        self.dialog.protocol("WM_DELETE_WINDOW", self._on_close)

    def _center_on_parent(self, parent: tk.Widget) -> None:
        """Center the dialog on its parent window."""
        try:
            self.dialog.update_idletasks()
            parent_x = parent.winfo_rootx()
            parent_y = parent.winfo_rooty()
            parent_w = parent.winfo_width()
            parent_h = parent.winfo_height()

            dialog_w = self.dialog.winfo_width()
            dialog_h = self.dialog.winfo_height()

            x = parent_x + (parent_w - dialog_w) // 2
            y = parent_y + (parent_h - dialog_h) // 2

            self.dialog.geometry(f"+{x}+{y}")
        except Exception:
            pass

    def _build_ui(self, current_baud: int) -> None:
        """Build the configuration dialog UI."""
        # Main container
        if HAS_THEME and Colors is not None:
            main = tk.Frame(self.dialog, bg=Colors.BG_DARK, padx=12, pady=12)
        else:
            main = ttk.Frame(self.dialog, padding=12)
        main.pack(fill=tk.BOTH, expand=True)
        main.columnconfigure(0, weight=1)

        # Serial Settings
        serial_lf = ttk.LabelFrame(main, text="Serial Settings")
        serial_lf.grid(row=0, column=0, sticky="new", pady=(0, 8))
        serial_lf.columnconfigure(1, weight=1)

        # Port (read-only)
        ttk.Label(serial_lf, text="Port:", style='Inframe.TLabel').grid(
            row=0, column=0, sticky="w", padx=8, pady=4
        )
        port_short = self.port.split('/')[-1]
        ttk.Label(serial_lf, text=port_short, style='Inframe.TLabel').grid(
            row=0, column=1, sticky="e", padx=8, pady=4
        )

        # Baud Rate
        ttk.Label(serial_lf, text="Baud Rate:", style='Inframe.TLabel').grid(
            row=1, column=0, sticky="w", padx=8, pady=4
        )
        self._baud_var = tk.StringVar(value=str(current_baud))
        baud_combo = ttk.Combobox(
            serial_lf,
            textvariable=self._baud_var,
            values=[str(b) for b in self.BAUD_RATES],
            state="readonly",
            width=12
        )
        baud_combo.grid(row=1, column=1, sticky="e", padx=8, pady=4)

        # GPS Settings
        gps_lf = ttk.LabelFrame(main, text="GPS Settings")
        gps_lf.grid(row=1, column=0, sticky="new", pady=(0, 8))
        gps_lf.columnconfigure(1, weight=1)

        # Update Rate
        ttk.Label(gps_lf, text="Update Rate:", style='Inframe.TLabel').grid(
            row=0, column=0, sticky="w", padx=8, pady=4
        )
        self._update_rate_var = tk.StringVar(value="1")
        rate_combo = ttk.Combobox(
            gps_lf,
            textvariable=self._update_rate_var,
            values=[f"{r} Hz" for r in self.UPDATE_RATES],
            state="readonly",
            width=12
        )
        rate_combo.grid(row=0, column=1, sticky="e", padx=8, pady=4)

        # NMEA Sentences (checkboxes)
        nmea_lf = ttk.LabelFrame(main, text="NMEA Sentences")
        nmea_lf.grid(row=2, column=0, sticky="new", pady=(0, 8))
        nmea_lf.columnconfigure(0, weight=1)
        nmea_lf.columnconfigure(1, weight=1)

        self._nmea_vars = {}
        sentences = [
            ("GGA", "Position fix"),
            ("RMC", "Recommended minimum"),
            ("VTG", "Course/speed"),
            ("GSA", "DOP and satellites"),
            ("GSV", "Satellites in view"),
            ("GLL", "Lat/Lon position"),
        ]

        for i, (code, desc) in enumerate(sentences):
            var = tk.BooleanVar(value=True)
            self._nmea_vars[code] = var
            cb = ttk.Checkbutton(
                nmea_lf,
                text=f"{code} - {desc}",
                variable=var,
                style='Inframe.TCheckbutton'
            )
            cb.grid(row=i // 2, column=i % 2, sticky="w", padx=8, pady=2)

        # Display Settings
        display_lf = ttk.LabelFrame(main, text="Display Settings")
        display_lf.grid(row=3, column=0, sticky="new", pady=(0, 8))
        display_lf.columnconfigure(1, weight=1)

        # Speed units
        ttk.Label(display_lf, text="Speed Units:", style='Inframe.TLabel').grid(
            row=0, column=0, sticky="w", padx=8, pady=4
        )
        self._speed_unit_var = tk.StringVar(value="km/h")
        speed_combo = ttk.Combobox(
            display_lf,
            textvariable=self._speed_unit_var,
            values=["km/h", "mph", "knots", "m/s"],
            state="readonly",
            width=12
        )
        speed_combo.grid(row=0, column=1, sticky="e", padx=8, pady=4)

        # Altitude units
        ttk.Label(display_lf, text="Altitude Units:", style='Inframe.TLabel').grid(
            row=1, column=0, sticky="w", padx=8, pady=4
        )
        self._alt_unit_var = tk.StringVar(value="meters")
        alt_combo = ttk.Combobox(
            display_lf,
            textvariable=self._alt_unit_var,
            values=["meters", "feet"],
            state="readonly",
            width=12
        )
        alt_combo.grid(row=1, column=1, sticky="e", padx=8, pady=4)

        # Buttons frame
        btn_frame = ttk.Frame(main)
        btn_frame.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        btn_frame.columnconfigure(0, weight=1)
        btn_frame.columnconfigure(1, weight=1)
        btn_frame.columnconfigure(2, weight=1)

        # Apply, Reset, Close buttons
        if RoundedButton is not None:
            btn_bg = Colors.BG_FRAME if Colors is not None else None

            apply_btn = RoundedButton(
                btn_frame, text="Apply",
                command=self._on_apply,
                width=80, height=32, style='primary', bg=btn_bg
            )
            apply_btn.grid(row=0, column=0, padx=4)

            reset_btn = RoundedButton(
                btn_frame, text="Reset",
                command=self._on_reset,
                width=80, height=32, style='default', bg=btn_bg
            )
            reset_btn.grid(row=0, column=1, padx=4)

            close_btn = RoundedButton(
                btn_frame, text="Close",
                command=self._on_close,
                width=80, height=32, style='default', bg=btn_bg
            )
            close_btn.grid(row=0, column=2, padx=4)
        else:
            ttk.Button(btn_frame, text="Apply", command=self._on_apply).grid(
                row=0, column=0, sticky="ew", padx=4
            )
            ttk.Button(btn_frame, text="Reset", command=self._on_reset).grid(
                row=0, column=1, sticky="ew", padx=4
            )
            ttk.Button(btn_frame, text="Close", command=self._on_close).grid(
                row=0, column=2, sticky="ew", padx=4
            )

    def _on_apply(self) -> None:
        """Apply configuration changes."""
        try:
            # Collect settings
            baud = int(self._baud_var.get())
            speed_unit = self._speed_unit_var.get()
            alt_unit = self._alt_unit_var.get()

            # Apply to system if possible
            if hasattr(self.system, 'preferences') and self.system.preferences:
                self.system.preferences.write_sync({
                    'baud_rate': baud,
                    'speed_unit': speed_unit,
                    'altitude_unit': alt_unit,
                })

            self.logger.info("GPS config applied: baud=%d, speed=%s, alt=%s",
                             baud, speed_unit, alt_unit)

            if messagebox:
                messagebox.showinfo(
                    "Configuration Applied",
                    "Settings have been saved.\nSome changes may require reconnection.",
                    parent=self.dialog
                )
        except Exception as e:
            self.logger.error("Failed to apply GPS config: %s", e)
            if messagebox:
                messagebox.showerror(
                    "Configuration Error",
                    f"Failed to apply settings:\n{e}",
                    parent=self.dialog
                )

    def _on_reset(self) -> None:
        """Reset to default values."""
        self._baud_var.set("9600")
        self._update_rate_var.set("1 Hz")
        self._speed_unit_var.set("km/h")
        self._alt_unit_var.set("meters")

        # Reset NMEA sentences
        for var in self._nmea_vars.values():
            var.set(True)

    def _on_close(self) -> None:
        """Close the configuration dialog."""
        self.dialog.destroy()
