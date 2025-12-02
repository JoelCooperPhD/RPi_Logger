"""VOG device configuration dialog.

Based on RS_Logger's sVOG_UIConfig.py pattern - modal dialog for configuring
sVOG device parameters with preset configurations.
"""

from __future__ import annotations

from typing import Awaitable, Callable, Dict, Optional, TYPE_CHECKING

try:
    import tkinter as tk
    from tkinter import ttk
    HAS_TK = True
except ImportError:
    HAS_TK = False
    tk = None
    ttk = None

if TYPE_CHECKING:
    ActionCallback = Optional[Callable[[str, Dict], Awaitable[None]]]


class VOGConfigDialog:
    """Configuration dialog for VOG devices.

    Provides:
    - Current config display (name, open duration, close duration)
    - Preset configurations (NHTSA, eBlindfold, Direct)
    - Upload custom settings to device
    """

    # Button control modes
    BUTTON_CONTROL = ("Trial", "Lens", "Peek")
    CLICK_MODE = ("Hold", "Click")

    def __init__(self, action_callback: "ActionCallback" = None):
        if not HAS_TK:
            raise ImportError("tkinter is required for VOGConfigDialog")

        self._action_callback = action_callback

        # Configuration StringVars - will be created when dialog opens
        self._settings: Dict[str, tk.StringVar] = {}
        self._active_port: Optional[str] = None
        self._win: Optional[tk.Toplevel] = None

    def show(self, port: str, parent: Optional[tk.Widget] = None):
        """Show the configuration dialog for a specific device port."""
        self._active_port = port

        # Create toplevel window
        self._win = tk.Toplevel(parent) if parent else tk.Toplevel()
        self._win.withdraw()
        self._win.grab_set()
        self._win.title(f"VOG Configuration - {port}")
        self._win.focus_force()
        self._win.resizable(False, False)

        # Initialize StringVars
        self._settings = {
            "deviceVer": tk.StringVar(),
            "configName": tk.StringVar(),
            "configMaxOpen": tk.StringVar(),
            "configMaxClose": tk.StringVar(),
            "configDebounce": tk.StringVar(),
            "configClickMode": tk.StringVar(),
            "buttonControl": tk.StringVar(),
        }

        self._build_ui()
        self._win.deiconify()

    def _build_ui(self):
        """Build the dialog UI."""
        win = self._win

        # Configuration frame
        lf = ttk.LabelFrame(win, text="Configuration")
        lf.grid(row=0, column=0, sticky="NEWS", pady=5, padx=5)
        lf.grid_columnconfigure(1, weight=1)

        row = 0

        # Device version (read-only display)
        ttk.Label(lf, text="Device Version:").grid(row=row, column=0, sticky="W", padx=5)
        ttk.Label(lf, textvariable=self._settings["deviceVer"]).grid(row=row, column=1, sticky="E", padx=5)
        row += 1

        # Name
        ttk.Label(lf, text="Name:").grid(row=row, column=0, sticky="W", padx=5)
        ttk.Entry(lf, textvariable=self._settings["configName"], width=17).grid(row=row, column=1, sticky="E", padx=5)
        row += 1

        # Separator
        ttk.Separator(lf).grid(row=row, column=0, columnspan=2, sticky="EW", pady=5)
        row += 1

        # Open Duration
        ttk.Label(lf, text="Open Duration (ms):").grid(row=row, column=0, sticky="W", padx=5)
        ttk.Entry(lf, textvariable=self._settings["configMaxOpen"], width=10).grid(row=row, column=1, sticky="E", padx=5)
        row += 1

        # Close Duration
        ttk.Label(lf, text="Closed Duration (ms):").grid(row=row, column=0, sticky="W", padx=5)
        ttk.Entry(lf, textvariable=self._settings["configMaxClose"], width=10).grid(row=row, column=1, sticky="E", padx=5)
        row += 1

        # Separator
        ttk.Separator(lf).grid(row=row, column=0, columnspan=2, sticky="EW", pady=5)
        row += 1

        # Upload button
        ttk.Button(
            lf, text="Upload Settings", command=self._on_upload
        ).grid(row=row, column=0, columnspan=2, sticky="EW", padx=20, pady=5)

        # Presets frame
        pf = ttk.LabelFrame(win, text="Preset Configurations")
        pf.grid(row=1, column=0, sticky="EW", pady=5, padx=5)
        pf.grid_columnconfigure((0, 1, 2), weight=1)

        ttk.Button(pf, text="NHTSA", command=self._on_nhtsa).grid(row=0, column=0, sticky="EW", padx=2, pady=2)
        ttk.Button(pf, text="eBlindfold", command=self._on_eblindfold).grid(row=0, column=1, sticky="EW", padx=2, pady=2)
        ttk.Button(pf, text="Direct", command=self._on_direct).grid(row=0, column=2, sticky="EW", padx=2, pady=2)

        # Close button
        ttk.Button(win, text="Close", command=self._on_close).grid(row=2, column=0, sticky="EW", padx=5, pady=5)

    def update_fields(self, key: str, val: str):
        """Update a configuration field from device response."""
        if key == "configClickMode":
            try:
                val = self.CLICK_MODE[int(val)]
            except (ValueError, IndexError):
                pass
        elif key in ("configButtonControl", "buttonControl"):
            key = "buttonControl"
            try:
                val = self.BUTTON_CONTROL[int(val)]
            except (ValueError, IndexError):
                pass

        if key in self._settings:
            self._settings[key].set(val)

    def _on_upload(self):
        """Upload current settings to device."""
        if not self._action_callback or not self._active_port:
            return

        # Fixed values matching RS_Logger behavior
        clk_mode = "1"  # Hold mode
        btn_mode = "0"  # Trial mode
        debounce = "20"

        config = {
            "name": self._settings["configName"].get().strip(),
            "max_open": self._settings["configMaxOpen"].get().strip(),
            "max_close": self._settings["configMaxClose"].get().strip(),
            "debounce": debounce,
            "click_mode": clk_mode,
            "button_mode": btn_mode,
        }

        # Schedule the async callback
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._action_callback("set_config", {"port": self._active_port, "config": config}))
        except RuntimeError:
            pass

    def _on_nhtsa(self):
        """Apply NHTSA preset (1500ms open/close)."""
        self._apply_preset("NHTSA", "1500", "1500", "20", "1", "0")

    def _on_eblindfold(self):
        """Apply eBlindfold preset (unlimited open, instant close)."""
        self._apply_preset("eBlindfold", "2147483647", "0", "100", "1", "0")

    def _on_direct(self):
        """Apply Direct preset (manual control)."""
        self._apply_preset("Direct", "2147483647", "0", "100", "0", "1")

    def _apply_preset(self, name: str, max_open: str, max_close: str, debounce: str, click_mode: str, button_mode: str):
        """Apply a preset configuration and upload to device."""
        if not self._action_callback or not self._active_port:
            return

        # Update UI
        self._settings["configName"].set(name)
        self._settings["configMaxOpen"].set(max_open)
        self._settings["configMaxClose"].set(max_close)

        config = {
            "name": name,
            "max_open": max_open,
            "max_close": max_close,
            "debounce": debounce,
            "click_mode": click_mode,
            "button_mode": button_mode,
        }

        # Schedule the async callback
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._action_callback("set_config", {"port": self._active_port, "config": config}))
        except RuntimeError:
            pass

    def _on_close(self):
        """Close the dialog."""
        if self._win:
            self._win.grab_release()
            self._win.destroy()
            self._win = None
