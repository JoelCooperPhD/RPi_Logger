"""VOG configuration dialog for device settings.

Supports both sVOG and wVOG devices with adaptive UI.
Uses event-driven config updates via handler callback mechanism.
"""

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Any, Optional
import asyncio
from pathlib import Path

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.core.ui.theme.styles import Theme
from rpi_logger.core.ui.theme.colors import Colors
from rpi_logger.core.ui.theme.widgets import RoundedButton
from rpi_logger.modules.base import ConfigLoader


class VOGConfigWindow:
    """Modal dialog for configuring VOG device settings.

    Adapts UI based on device type:
    - sVOG: Config name, max open/close, debounce, click mode, button control
    - wVOG: Clear/dark opacity, open/close times, debounce, experiment type, battery status

    Uses event-driven updates: registers a callback with the handler to receive
    config responses in real-time rather than polling with delays.
    """

    # Config key for saving dialog position
    CONFIG_DIALOG_GEOMETRY_KEY = "config_dialog_geometry"

    def __init__(self, parent: tk.Tk, port: str, system: Any, device_type: str = 'svog', async_bridge=None):
        self.port = port
        self.system = system
        self.device_type = device_type
        self.async_bridge = async_bridge
        self.logger = get_module_logger("VOGConfigWindow")
        self._handler = None  # Store handler reference for cleanup
        self._config_path = Path(__file__).parent.parent.parent.parent / "config.txt"

        # Determine window size based on device type
        if device_type == 'wvog':
            width, height = 365, 365
        else:
            width, height = 345, 345

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
        self.dialog.title(f"Configure {device_type.upper()} - {port}")
        self.dialog.resizable(False, False)
        self.dialog.transient(parent)
        self.dialog.grab_set()
        Theme.configure_toplevel(self.dialog)

        # Config values
        self.config_vars = {}
        self._loading = False  # Loading state flag

        self._build_ui()
        self._load_config()

        # Register close handler to clean up callback
        self.dialog.protocol("WM_DELETE_WINDOW", self._on_close)

    def _is_wvog(self) -> bool:
        """Check if device is wVOG type (handles various formats like 'wvog', 'wVOG_USB')."""
        return 'wvog' in self.device_type.lower()

    def _build_ui(self):
        """Build the configuration dialog UI."""
        main_frame = ttk.Frame(self.dialog, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        if self._is_wvog():
            self._build_wvog_ui(main_frame)
        else:
            self._build_svog_ui(main_frame)

        main_frame.columnconfigure(1, weight=1)

    def _build_svog_ui(self, main_frame: ttk.Frame):
        """Build sVOG-specific configuration UI."""
        # Configuration LabelFrame for consistent styling with wVOG
        config_lf = ttk.LabelFrame(main_frame, text="Configuration")
        config_lf.grid(row=0, column=0, columnspan=2, sticky="news", pady=2, padx=2)
        config_lf.grid_columnconfigure(1, weight=1)

        # Config name
        row = 0
        ttk.Label(config_lf, text="Config Name:", style='Inframe.TLabel').grid(row=row, column=0, sticky="w", padx=5, pady=5)
        self.config_vars['config_name'] = tk.StringVar()
        ttk.Entry(config_lf, textvariable=self.config_vars['config_name'], width=20).grid(row=row, column=1, sticky="ew", padx=5, pady=5)

        # Separator
        row += 1
        ttk.Separator(config_lf, orient=tk.HORIZONTAL).grid(row=row, column=0, columnspan=2, sticky="ew", pady=5)

        # Max Open Time
        row += 1
        ttk.Label(config_lf, text="Max Open (ms):", style='Inframe.TLabel').grid(row=row, column=0, sticky="w", padx=5, pady=2)
        self.config_vars['max_open'] = tk.StringVar()
        ttk.Entry(config_lf, textvariable=self.config_vars['max_open'], width=10).grid(row=row, column=1, sticky="e", padx=5, pady=2)

        # Max Close Time
        row += 1
        ttk.Label(config_lf, text="Max Close (ms):", style='Inframe.TLabel').grid(row=row, column=0, sticky="w", padx=5, pady=2)
        self.config_vars['max_close'] = tk.StringVar()
        ttk.Entry(config_lf, textvariable=self.config_vars['max_close'], width=10).grid(row=row, column=1, sticky="e", padx=5, pady=2)

        # Debounce Time
        row += 1
        ttk.Label(config_lf, text="Debounce (ms):", style='Inframe.TLabel').grid(row=row, column=0, sticky="w", padx=5, pady=2)
        self.config_vars['debounce'] = tk.StringVar()
        ttk.Entry(config_lf, textvariable=self.config_vars['debounce'], width=10).grid(row=row, column=1, sticky="e", padx=5, pady=2)

        # Click Mode
        row += 1
        ttk.Label(config_lf, text="Click Mode:", style='Inframe.TLabel').grid(row=row, column=0, sticky="w", padx=5, pady=2)
        self.config_vars['click_mode'] = tk.StringVar()
        click_combo = ttk.Combobox(
            config_lf,
            textvariable=self.config_vars['click_mode'],
            values=["0 - Single", "1 - Double", "2 - Hold"],
            width=17,
            state="readonly"
        )
        click_combo.grid(row=row, column=1, sticky="e", padx=5, pady=2)

        # Button Control
        row += 1
        ttk.Label(config_lf, text="Button Control:", style='Inframe.TLabel').grid(row=row, column=0, sticky="w", padx=5, pady=2)
        self.config_vars['button_control'] = tk.StringVar()
        btn_combo = ttk.Combobox(
            config_lf,
            textvariable=self.config_vars['button_control'],
            values=["0 - Disabled", "1 - Enabled"],
            width=17,
            state="readonly"
        )
        btn_combo.grid(row=row, column=1, sticky="e", padx=5, pady=2)

        # Device Version (read-only)
        row += 1
        ttk.Label(config_lf, text="Device Version:", style='Inframe.TLabel').grid(row=row, column=0, sticky="w", padx=5, pady=2)
        self.version_label = ttk.Label(config_lf, text="-", style='Inframe.TLabel')
        self.version_label.grid(row=row, column=1, sticky="e", padx=5, pady=2)

        # Separator and buttons
        self._build_buttons(main_frame, 1)

    def _build_wvog_ui(self, main_frame: ttk.Frame):
        """Build wVOG-specific configuration UI matching RS_Logger layout."""
        # Configuration LabelFrame
        config_lf = ttk.LabelFrame(main_frame, text="Configuration")
        config_lf.grid(row=0, column=0, sticky="news", pady=2, padx=2)
        config_lf.grid_columnconfigure(1, weight=1)

        row = 0

        # Name (experiment type) - entry expands to fill space
        ttk.Label(config_lf, text="Name:", style='Inframe.TLabel').grid(row=row, column=0, sticky="w", padx=5, pady=2)
        self.config_vars['experiment_type'] = tk.StringVar()
        ttk.Entry(config_lf, textvariable=self.config_vars['experiment_type']).grid(
            row=row, column=1, sticky="ew", padx=5, pady=2)

        # Separator
        row += 1
        ttk.Separator(config_lf, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=5)

        # Open Duration - entry right-aligned
        row += 1
        ttk.Label(config_lf, text="Open Duration (ms):", style='Inframe.TLabel').grid(row=row, column=0, sticky="w", padx=5, pady=2)
        self.config_vars['open_time'] = tk.StringVar()
        ttk.Entry(config_lf, textvariable=self.config_vars['open_time'], width=10).grid(
            row=row, column=1, sticky="e", padx=5, pady=2)

        # Closed Duration - entry right-aligned
        row += 1
        ttk.Label(config_lf, text="Closed Duration (ms):", style='Inframe.TLabel').grid(row=row, column=0, sticky="w", padx=5, pady=2)
        self.config_vars['close_time'] = tk.StringVar()
        ttk.Entry(config_lf, textvariable=self.config_vars['close_time'], width=10).grid(
            row=row, column=1, sticky="e", padx=5, pady=2)

        # Debounce Time - entry right-aligned
        row += 1
        ttk.Label(config_lf, text="Debounce Time (ms):", style='Inframe.TLabel').grid(row=row, column=0, sticky="w", padx=5, pady=2)
        self.config_vars['debounce'] = tk.StringVar()
        ttk.Entry(config_lf, textvariable=self.config_vars['debounce'], width=10).grid(
            row=row, column=1, sticky="e", padx=5, pady=2)

        # Separator
        row += 1
        ttk.Separator(config_lf, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=5)

        # Checkbuttons row - Start Clear and Verbose
        row += 1
        self.config_vars['start_state'] = tk.StringVar(value="0")
        start_clear_cb = ttk.Checkbutton(
            config_lf, text="Start Clear",
            variable=self.config_vars['start_state'],
            onvalue="1", offvalue="0",
            style='Switch.TCheckbutton'
        )
        start_clear_cb.grid(row=row, column=0, sticky="w", padx=5, pady=2)

        self.config_vars['verbose'] = tk.StringVar(value="0")
        verbose_cb = ttk.Checkbutton(
            config_lf, text="Verbose",
            variable=self.config_vars['verbose'],
            onvalue="1", offvalue="0",
            style='Switch.TCheckbutton'
        )
        verbose_cb.grid(row=row, column=1, sticky="e", padx=5, pady=2)

        # Separator
        row += 1
        ttk.Separator(config_lf, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=5)

        # Upload Settings button - use tk.Frame with bg color for RoundedButton
        row += 1
        upload_frame = tk.Frame(config_lf, bg=Colors.BG_DARKER)
        upload_frame.grid(row=row, column=0, columnspan=2, pady=5)
        RoundedButton(
            upload_frame, text="Upload Settings", command=self._apply_config,
            width=150, height=32, style='default', bg=Colors.BG_DARKER
        ).pack()

        # Preset Configurations LabelFrame
        preset_lf = ttk.LabelFrame(main_frame, text="Preset Configurations:")
        preset_lf.grid(row=1, column=0, sticky="ew", pady=5, padx=2)

        # Use tk.Frame with bg for RoundedButtons
        preset_btn_frame = tk.Frame(preset_lf, bg=Colors.BG_DARKER)
        preset_btn_frame.pack(fill=tk.X, padx=2, pady=4)
        for i in range(4):
            preset_btn_frame.columnconfigure(i, weight=1)

        RoundedButton(preset_btn_frame, text="Cycle", command=self._preset_cycle,
                      width=75, height=28, style='default', bg=Colors.BG_DARKER).grid(row=0, column=0, padx=2)
        RoundedButton(preset_btn_frame, text="Peek", command=self._preset_peek,
                      width=75, height=28, style='default', bg=Colors.BG_DARKER).grid(row=0, column=1, padx=2)
        RoundedButton(preset_btn_frame, text="eBlindfold", command=self._preset_eblindfold,
                      width=75, height=28, style='default', bg=Colors.BG_DARKER).grid(row=0, column=2, padx=2)
        RoundedButton(preset_btn_frame, text="Direct", command=self._preset_direct,
                      width=75, height=28, style='default', bg=Colors.BG_DARKER).grid(row=0, column=3, padx=2)

        # Store version label reference (not displayed for wVOG, but needed for compatibility)
        self.version_label = ttk.Label(main_frame, text="")

        # Hidden fields for opacity (not in RS_Logger UI but keep for protocol compatibility)
        self.config_vars['clear_opacity'] = tk.StringVar()
        self.config_vars['dark_opacity'] = tk.StringVar()

    def _build_buttons(self, main_frame: ttk.Frame, start_row: int):
        """Build common buttons at bottom of dialog."""
        # Use tk.Frame with bg color for RoundedButtons
        btn_frame = tk.Frame(main_frame, bg=Colors.BG_DARKER)
        btn_frame.grid(row=start_row, column=0, columnspan=2, pady=10, padx=2)

        btn_bg = Colors.BG_DARKER
        RoundedButton(btn_frame, text="Refresh", command=self._load_config,
                      width=80, height=32, style='default', bg=btn_bg).pack(side=tk.LEFT, padx=4)
        RoundedButton(btn_frame, text="Apply", command=self._apply_config,
                      width=80, height=32, style='default', bg=btn_bg).pack(side=tk.LEFT, padx=4)
        RoundedButton(btn_frame, text="Close", command=self._on_close,
                      width=80, height=32, style='default', bg=btn_bg).pack(side=tk.LEFT, padx=4)

    def _load_config(self):
        """Load current configuration from device.

        Uses event-driven approach:
        1. Register callback with handler to receive config updates
        2. Populate UI with any cached config immediately
        3. Request fresh config from device via async bridge
        4. Callback updates UI as responses arrive
        """
        handler = self.system.get_device_handler(self.port)
        if not handler:
            messagebox.showerror("Error", f"Device not connected on {self.port}", parent=self.dialog)
            return

        self.logger.debug("Loading config for port %s, device_type=%s", self.port, self.device_type)

        # Store handler reference for cleanup
        self._handler = handler

        # Register callback to receive config updates
        handler.set_config_callback(self._on_config_received)

        # First, populate from any cached config immediately
        cached_config = handler.get_config()
        if cached_config:
            self._update_ui_from_config(cached_config)

        # Show loading state
        self._set_loading(True)

        # Request fresh config from device via async bridge
        if self.async_bridge:
            self.async_bridge.run_coroutine(handler.get_device_config())
        else:
            self.logger.warning("No async bridge available - cannot request device config")
            self._set_loading(False)

    def _set_loading(self, loading: bool):
        """Update loading state and visual indicator."""
        self._loading = loading
        try:
            if not self.dialog.winfo_exists():
                return
            title_base = f"Configure {self.device_type.upper()} - {self.port}"
            if loading:
                self.dialog.title(f"{title_base} (Loading...)")
                self.dialog.config(cursor="watch")
            else:
                self.dialog.title(title_base)
                self.dialog.config(cursor="")
        except tk.TclError:
            pass  # Dialog was destroyed

    def _on_config_received(self, config: dict):
        """Callback invoked when config response is received from device.

        This is called from the handler's read loop when CONFIG responses arrive.
        We schedule UI update on the main thread via dialog.after().
        """
        self.logger.debug("Config callback received: %s", config)
        try:
            if self.dialog.winfo_exists():
                # Clear loading state and update UI
                self.dialog.after(0, lambda: self._handle_config_update(config))
        except tk.TclError:
            pass  # Dialog was destroyed

    def _handle_config_update(self, config: dict):
        """Handle config update on main thread."""
        self._set_loading(False)
        self._safe_update_ui(config)

    def _on_close(self):
        """Handle dialog close - save position and clean up callback registration."""
        self._save_position()
        if self._handler:
            self._handler.clear_config_callback()
            self._handler = None
        self.dialog.destroy()

    def _load_saved_position_static(self) -> Optional[tuple]:
        """Load saved dialog position from config file.

        This method can be called before self.dialog exists.

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
        except Exception as e:
            pass  # Can't use self.logger yet if called early
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

    def _safe_update_ui(self, config: dict):
        """Safely update UI, checking if dialog still exists."""
        try:
            if self.dialog.winfo_exists():
                self._update_ui_from_config(config)
        except tk.TclError:
            pass  # Dialog was destroyed

    def _update_ui_from_config(self, config: dict):
        """Update UI with config values."""
        # Handle various device_type formats: 'wvog', 'wVOG_USB', 'wVOG', etc.
        is_wvog = 'wvog' in self.device_type.lower()
        if is_wvog:
            self._update_wvog_ui_from_config(config)
        else:
            self._update_svog_ui_from_config(config)

        version = config.get('deviceVer', '-')
        self.version_label.config(text=version)

    def _update_svog_ui_from_config(self, config: dict):
        """Update sVOG UI with config values."""
        self.config_vars['config_name'].set(config.get('configName', ''))
        self.config_vars['max_open'].set(config.get('configMaxOpen', ''))
        self.config_vars['max_close'].set(config.get('configMaxClose', ''))
        self.config_vars['debounce'].set(config.get('configDebounce', ''))

        click_mode = config.get('configClickMode', '0')
        click_labels = {"0": "0 - Single", "1": "1 - Double", "2": "2 - Hold"}
        self.config_vars['click_mode'].set(click_labels.get(str(click_mode), f"{click_mode}"))

        btn_ctrl = config.get('configButtonControl', '0')
        btn_labels = {"0": "0 - Disabled", "1": "1 - Enabled"}
        self.config_vars['button_control'].set(btn_labels.get(str(btn_ctrl), f"{btn_ctrl}"))

    def _update_wvog_ui_from_config(self, config: dict):
        """Update wVOG UI with config values."""
        # Experiment type (typ key or experiment_type)
        exp_type = config.get('experiment_type', config.get('typ', ''))
        self.config_vars['experiment_type'].set(str(exp_type))

        # Open time (opn key or open_time)
        open_time = config.get('open_time', config.get('opn', ''))
        self.config_vars['open_time'].set(str(open_time))

        # Close time (cls key or close_time)
        close_time = config.get('close_time', config.get('cls', ''))
        self.config_vars['close_time'].set(str(close_time))

        # Debounce (dbc key or debounce)
        debounce = config.get('debounce', config.get('dbc', ''))
        self.config_vars['debounce'].set(str(debounce))

        # Start state (srt key) - now just 0 or 1 for checkbutton
        start_state = config.get('start_state', config.get('srt', '0'))
        self.config_vars['start_state'].set(str(start_state) if str(start_state) in ('0', '1') else '0')

        # Verbose / print cycle (dta key)
        verbose = config.get('verbose', config.get('dta', '0'))
        if 'verbose' in self.config_vars:
            self.config_vars['verbose'].set(str(verbose) if str(verbose) in ('0', '1') else '0')

        # Hidden opacity fields (for protocol compatibility)
        clear_opacity = config.get('clear_opacity', config.get('clr', ''))
        if 'clear_opacity' in self.config_vars:
            self.config_vars['clear_opacity'].set(str(clear_opacity))

        dark_opacity = config.get('dark_opacity', config.get('drk', ''))
        if 'dark_opacity' in self.config_vars:
            self.config_vars['dark_opacity'].set(str(dark_opacity))

    def _validate_numeric_field(self, field_name: str, display_name: str, allow_zero: bool = True) -> Optional[str]:
        """Validate a numeric field value.

        Args:
            field_name: Key in config_vars
            display_name: Human-readable name for error messages
            allow_zero: Whether zero is a valid value

        Returns:
            Error message if invalid, None if valid or empty
        """
        value = self.config_vars.get(field_name, tk.StringVar()).get().strip()
        if not value:
            return None  # Empty is OK (won't be sent)

        try:
            num = int(value)
            if num < 0:
                return f"{display_name} must be a positive number"
            if not allow_zero and num == 0:
                return f"{display_name} must be greater than zero"
        except ValueError:
            return f"{display_name} must be a valid integer"

        return None

    def _validate_config(self) -> Optional[str]:
        """Validate all configuration fields before applying.

        Returns:
            Error message if validation fails, None if valid
        """
        if self.device_type == 'wvog':
            # wVOG numeric fields
            fields = [
                ('open_time', 'Open Duration', True),
                ('close_time', 'Closed Duration', True),
                ('debounce', 'Debounce Time', True),
            ]
        else:
            # sVOG numeric fields
            fields = [
                ('max_open', 'Max Open', True),
                ('max_close', 'Max Close', True),
                ('debounce', 'Debounce', True),
            ]

        for field_name, display_name, allow_zero in fields:
            error = self._validate_numeric_field(field_name, display_name, allow_zero)
            if error:
                return error

        return None

    def _apply_config(self):
        """Apply configuration changes to device."""
        # Validate before applying
        error = self._validate_config()
        if error:
            messagebox.showerror("Validation Error", error, parent=self.dialog)
            return

        handler = self.system.get_device_handler(self.port)
        if not handler:
            messagebox.showerror("Error", "Device not connected", parent=self.dialog)
            return

        if self.async_bridge:
            self.async_bridge.run_coroutine(self._apply_config_async(handler))
        else:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._apply_config_async(handler))
            except RuntimeError:
                messagebox.showerror("Error", "Cannot apply config - no event loop", parent=self.dialog)

    async def _apply_config_async(self, handler):
        """Async config application."""
        try:
            if self.device_type == 'wvog':
                await self._apply_wvog_config(handler)
            else:
                await self._apply_svog_config(handler)

            self.dialog.after(0, lambda: messagebox.showinfo("Success", "Configuration applied", parent=self.dialog))

        except Exception as e:
            self.logger.error("Failed to apply config: %s", e)
            self.dialog.after(0, lambda: messagebox.showerror("Error", f"Failed to apply: {e}", parent=self.dialog))

    async def _apply_svog_config(self, handler):
        """Apply sVOG configuration values."""
        config_name = self.config_vars['config_name'].get()
        if config_name:
            await handler.set_config_value('config_name', config_name)

        max_open = self.config_vars['max_open'].get()
        if max_open:
            await handler.set_config_value('max_open', max_open)

        max_close = self.config_vars['max_close'].get()
        if max_close:
            await handler.set_config_value('max_close', max_close)

        debounce = self.config_vars['debounce'].get()
        if debounce:
            await handler.set_config_value('debounce', debounce)

        click_mode = self.config_vars['click_mode'].get()
        if click_mode:
            mode_val = click_mode.split(' - ')[0] if ' - ' in click_mode else click_mode
            await handler.set_config_value('click_mode', mode_val)

        btn_ctrl = self.config_vars['button_control'].get()
        if btn_ctrl:
            ctrl_val = btn_ctrl.split(' - ')[0] if ' - ' in btn_ctrl else btn_ctrl
            await handler.set_config_value('button_control', ctrl_val)

    async def _apply_wvog_config(self, handler):
        """Apply wVOG configuration values."""
        # wVOG uses set>{key},{value} format
        # Map UI field names to wVOG config keys
        config_mapping = {
            'experiment_type': 'typ',
            'open_time': 'opn',
            'close_time': 'cls',
            'debounce': 'dbc',
            'clear_opacity': 'clr',
            'dark_opacity': 'drk',
        }

        for ui_key, wvog_key in config_mapping.items():
            value = self.config_vars.get(ui_key, tk.StringVar()).get()
            if value:
                await handler.set_config_value(wvog_key, value)

        # Start state - now a simple 0/1 from checkbutton
        start_state = self.config_vars['start_state'].get()
        if start_state:
            await handler.set_config_value('srt', start_state)

        # Verbose (print cycle data)
        verbose = self.config_vars.get('verbose', tk.StringVar()).get()
        if verbose:
            await handler.set_config_value('dta', verbose)

    # ------------------------------------------------------------------
    # wVOG Preset configurations (matching RS_Logger)
    # ------------------------------------------------------------------

    def _preset_cycle(self):
        """Apply Cycle (NHTSA) preset configuration."""
        self.config_vars['experiment_type'].set('cycle')
        self.config_vars['open_time'].set('1500')
        self.config_vars['close_time'].set('1500')
        self.config_vars['start_state'].set('1')
        self._apply_config()

    def _preset_peek(self):
        """Apply Peek preset configuration."""
        self.config_vars['experiment_type'].set('peek')
        self.config_vars['open_time'].set('1500')
        self.config_vars['close_time'].set('1500')
        self.config_vars['start_state'].set('0')
        self._apply_config()

    def _preset_eblindfold(self):
        """Apply eBlindfold preset configuration."""
        self.config_vars['experiment_type'].set('eblind')
        self.config_vars['open_time'].set('2147483647')
        self.config_vars['close_time'].set('0')
        self.config_vars['start_state'].set('1')
        self._apply_config()

    def _preset_direct(self):
        """Apply Direct preset configuration."""
        self.config_vars['experiment_type'].set('direct')
        self._apply_config()
