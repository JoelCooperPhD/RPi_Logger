"""EyeTracker configuration dialog for device settings.

Matches VOG/DRT styling patterns with Theme, RoundedButton, and consistent layout.
Provides configuration for Pupil Labs Neon eye tracker settings.
"""

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Any, Optional, TYPE_CHECKING
from pathlib import Path

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.core.ui.theme.styles import Theme
from rpi_logger.core.ui.theme.colors import Colors
from rpi_logger.core.ui.theme.widgets import RoundedButton
from rpi_logger.modules.base import ConfigLoader

if TYPE_CHECKING:
    from rpi_logger.modules.EyeTracker.app.eye_tracker_runtime import EyeTrackerRuntime


class EyeTrackerConfigWindow:
    """Modal dialog for configuring Eye Tracker settings.

    Configuration options:
    - Preview settings (resolution, frame rate)
    - Gaze overlay settings (shape, colors, size)
    - Recording settings (overlay, audio)

    Uses event-driven updates matching VOG/DRT pattern.
    """

    # Config key for saving dialog position
    CONFIG_DIALOG_GEOMETRY_KEY = "eyetracker_config_dialog_geometry"

    def __init__(self, parent: tk.Tk, runtime: "EyeTrackerRuntime"):
        self.runtime = runtime
        self.logger = get_module_logger("EyeTrackerConfigWindow")
        self._config_path = Path(__file__).parent.parent.parent.parent / "config.txt"

        # Window dimensions
        width, height = 380, 480

        # Calculate position before creating dialog
        saved_pos = self._load_saved_position_static()
        if saved_pos:
            x, y = saved_pos
        else:
            # Center on parent
            x = parent.winfo_x() + (parent.winfo_width() - width) // 2
            y = parent.winfo_y() + (parent.winfo_height() - height) // 2

        # Create modal dialog with full geometry immediately
        self.dialog = tk.Toplevel(parent)
        self.dialog.geometry(f"{width}x{height}+{x}+{y}")
        self.dialog.title("Configure EyeTracker-Neon")
        self.dialog.resizable(False, False)
        self.dialog.transient(parent)
        self.dialog.grab_set()
        Theme.configure_toplevel(self.dialog)

        # Config values
        self.config_vars = {}

        self._build_ui()
        self._load_config()

        # Register close handler
        self.dialog.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        """Build the configuration dialog UI."""
        main_frame = ttk.Frame(self.dialog, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(0, weight=1)

        self._build_preview_settings(main_frame, row=0)
        self._build_gaze_settings(main_frame, row=1)
        self._build_recording_settings(main_frame, row=2)
        self._build_buttons(main_frame, row=3)

    def _build_preview_settings(self, parent: ttk.Frame, row: int):
        """Build preview settings section."""
        lf = ttk.LabelFrame(parent, text="Preview Settings")
        lf.grid(row=row, column=0, sticky="new", pady=2, padx=2)
        lf.columnconfigure(1, weight=1)

        # Preview Width
        r = 0
        ttk.Label(lf, text="Preview Width:", style='Inframe.TLabel').grid(
            row=r, column=0, sticky="w", padx=5, pady=2
        )
        self.config_vars['preview_width'] = tk.StringVar()
        ttk.Entry(lf, textvariable=self.config_vars['preview_width'], width=10).grid(
            row=r, column=1, sticky="e", padx=5, pady=2
        )

        # Preview Height
        r += 1
        ttk.Label(lf, text="Preview Height:", style='Inframe.TLabel').grid(
            row=r, column=0, sticky="w", padx=5, pady=2
        )
        self.config_vars['preview_height'] = tk.StringVar()
        ttk.Entry(lf, textvariable=self.config_vars['preview_height'], width=10).grid(
            row=r, column=1, sticky="e", padx=5, pady=2
        )

        # Target FPS
        r += 1
        ttk.Label(lf, text="Target FPS:", style='Inframe.TLabel').grid(
            row=r, column=0, sticky="w", padx=5, pady=2
        )
        self.config_vars['target_fps'] = tk.StringVar()
        ttk.Entry(lf, textvariable=self.config_vars['target_fps'], width=10).grid(
            row=r, column=1, sticky="e", padx=5, pady=2
        )

    def _build_gaze_settings(self, parent: ttk.Frame, row: int):
        """Build gaze overlay settings section."""
        lf = ttk.LabelFrame(parent, text="Gaze Overlay")
        lf.grid(row=row, column=0, sticky="new", pady=2, padx=2)
        lf.columnconfigure(1, weight=1)

        # Gaze Shape
        r = 0
        ttk.Label(lf, text="Gaze Shape:", style='Inframe.TLabel').grid(
            row=r, column=0, sticky="w", padx=5, pady=2
        )
        self.config_vars['gaze_shape'] = tk.StringVar()
        shape_combo = ttk.Combobox(
            lf,
            textvariable=self.config_vars['gaze_shape'],
            values=["circle", "crosshair", "dot"],
            width=12,
            state="readonly"
        )
        shape_combo.grid(row=r, column=1, sticky="e", padx=5, pady=2)

        # Gaze Circle Radius
        r += 1
        ttk.Label(lf, text="Circle Radius:", style='Inframe.TLabel').grid(
            row=r, column=0, sticky="w", padx=5, pady=2
        )
        self.config_vars['gaze_circle_radius'] = tk.StringVar()
        ttk.Entry(lf, textvariable=self.config_vars['gaze_circle_radius'], width=10).grid(
            row=r, column=1, sticky="e", padx=5, pady=2
        )

        # Gaze Circle Thickness
        r += 1
        ttk.Label(lf, text="Circle Thickness:", style='Inframe.TLabel').grid(
            row=r, column=0, sticky="w", padx=5, pady=2
        )
        self.config_vars['gaze_circle_thickness'] = tk.StringVar()
        ttk.Entry(lf, textvariable=self.config_vars['gaze_circle_thickness'], width=10).grid(
            row=r, column=1, sticky="e", padx=5, pady=2
        )

        # Separator
        r += 1
        ttk.Separator(lf, orient=tk.HORIZONTAL).grid(
            row=r, column=0, columnspan=2, sticky="ew", pady=5
        )

        # Color labels
        r += 1
        ttk.Label(lf, text="Worn Color (RGB):", style='Inframe.TLabel').grid(
            row=r, column=0, sticky="w", padx=5, pady=2
        )

        color_frame = ttk.Frame(lf)
        color_frame.grid(row=r, column=1, sticky="e", padx=5, pady=2)

        self.config_vars['gaze_color_worn_r'] = tk.StringVar()
        self.config_vars['gaze_color_worn_g'] = tk.StringVar()
        self.config_vars['gaze_color_worn_b'] = tk.StringVar()

        ttk.Entry(color_frame, textvariable=self.config_vars['gaze_color_worn_r'], width=4).pack(side=tk.LEFT, padx=1)
        ttk.Entry(color_frame, textvariable=self.config_vars['gaze_color_worn_g'], width=4).pack(side=tk.LEFT, padx=1)
        ttk.Entry(color_frame, textvariable=self.config_vars['gaze_color_worn_b'], width=4).pack(side=tk.LEFT, padx=1)

        # Not worn color
        r += 1
        ttk.Label(lf, text="Not Worn Color (RGB):", style='Inframe.TLabel').grid(
            row=r, column=0, sticky="w", padx=5, pady=2
        )

        color_frame2 = ttk.Frame(lf)
        color_frame2.grid(row=r, column=1, sticky="e", padx=5, pady=2)

        self.config_vars['gaze_color_not_worn_r'] = tk.StringVar()
        self.config_vars['gaze_color_not_worn_g'] = tk.StringVar()
        self.config_vars['gaze_color_not_worn_b'] = tk.StringVar()

        ttk.Entry(color_frame2, textvariable=self.config_vars['gaze_color_not_worn_r'], width=4).pack(side=tk.LEFT, padx=1)
        ttk.Entry(color_frame2, textvariable=self.config_vars['gaze_color_not_worn_g'], width=4).pack(side=tk.LEFT, padx=1)
        ttk.Entry(color_frame2, textvariable=self.config_vars['gaze_color_not_worn_b'], width=4).pack(side=tk.LEFT, padx=1)

    def _build_recording_settings(self, parent: ttk.Frame, row: int):
        """Build recording settings section."""
        lf = ttk.LabelFrame(parent, text="Recording")
        lf.grid(row=row, column=0, sticky="new", pady=2, padx=2)
        lf.columnconfigure(1, weight=1)

        # Enable Recording Overlay
        r = 0
        self.config_vars['enable_recording_overlay'] = tk.StringVar(value="1")
        overlay_cb = ttk.Checkbutton(
            lf, text="Enable Recording Overlay",
            variable=self.config_vars['enable_recording_overlay'],
            onvalue="1", offvalue="0",
            style='Switch.TCheckbutton'
        )
        overlay_cb.grid(row=r, column=0, columnspan=2, sticky="w", padx=5, pady=2)

        # Include Gaze in Recording
        r += 1
        self.config_vars['include_gaze_in_recording'] = tk.StringVar(value="1")
        gaze_cb = ttk.Checkbutton(
            lf, text="Include Gaze in Recording",
            variable=self.config_vars['include_gaze_in_recording'],
            onvalue="1", offvalue="0",
            style='Switch.TCheckbutton'
        )
        gaze_cb.grid(row=r, column=0, columnspan=2, sticky="w", padx=5, pady=2)

        # Enable Audio Recording
        r += 1
        self.config_vars['enable_audio_recording'] = tk.StringVar(value="0")
        audio_cb = ttk.Checkbutton(
            lf, text="Enable Audio Recording",
            variable=self.config_vars['enable_audio_recording'],
            onvalue="1", offvalue="0",
            style='Switch.TCheckbutton'
        )
        audio_cb.grid(row=r, column=0, columnspan=2, sticky="w", padx=5, pady=2)

        # Advanced Gaze Logging
        r += 1
        self.config_vars['enable_advanced_gaze_logging'] = tk.StringVar(value="0")
        adv_cb = ttk.Checkbutton(
            lf, text="Advanced Gaze Logging",
            variable=self.config_vars['enable_advanced_gaze_logging'],
            onvalue="1", offvalue="0",
            style='Switch.TCheckbutton'
        )
        adv_cb.grid(row=r, column=0, columnspan=2, sticky="w", padx=5, pady=2)

    def _build_buttons(self, parent: ttk.Frame, row: int):
        """Build common buttons at bottom of dialog."""
        # Use tk.Frame with bg color for RoundedButtons
        btn_frame = tk.Frame(parent, bg=Colors.BG_DARKER)
        btn_frame.grid(row=row, column=0, pady=10, padx=2)

        btn_bg = Colors.BG_DARKER
        RoundedButton(
            btn_frame, text="Refresh", command=self._load_config,
            width=80, height=32, style='default', bg=btn_bg
        ).pack(side=tk.LEFT, padx=4)
        RoundedButton(
            btn_frame, text="Apply", command=self._apply_config,
            width=80, height=32, style='default', bg=btn_bg
        ).pack(side=tk.LEFT, padx=4)
        RoundedButton(
            btn_frame, text="Close", command=self._on_close,
            width=80, height=32, style='default', bg=btn_bg
        ).pack(side=tk.LEFT, padx=4)

    def _load_config(self):
        """Load current configuration from runtime."""
        if not self.runtime or not self.runtime._tracker_config:
            self.logger.warning("No tracker config available")
            return

        config = self.runtime._tracker_config

        # Preview settings
        self.config_vars['preview_width'].set(str(config.preview_width))
        self.config_vars['preview_height'].set(str(config.preview_height or ''))
        self.config_vars['target_fps'].set(str(config.fps))

        # Gaze settings
        self.config_vars['gaze_shape'].set(config.gaze_shape)
        self.config_vars['gaze_circle_radius'].set(str(config.gaze_circle_radius))
        self.config_vars['gaze_circle_thickness'].set(str(config.gaze_circle_thickness))

        # Gaze colors
        self.config_vars['gaze_color_worn_r'].set(str(config.gaze_color_worn_r))
        self.config_vars['gaze_color_worn_g'].set(str(config.gaze_color_worn_g))
        self.config_vars['gaze_color_worn_b'].set(str(config.gaze_color_worn_b))
        self.config_vars['gaze_color_not_worn_r'].set(str(config.gaze_color_not_worn_r))
        self.config_vars['gaze_color_not_worn_g'].set(str(config.gaze_color_not_worn_g))
        self.config_vars['gaze_color_not_worn_b'].set(str(config.gaze_color_not_worn_b))

        # Recording settings
        self.config_vars['enable_recording_overlay'].set('1' if config.enable_recording_overlay else '0')
        self.config_vars['include_gaze_in_recording'].set('1' if config.include_gaze_in_recording else '0')
        self.config_vars['enable_audio_recording'].set('1' if config.enable_audio_recording else '0')
        self.config_vars['enable_advanced_gaze_logging'].set('1' if config.enable_advanced_gaze_logging else '0')

    def _validate_numeric_field(self, field_name: str, display_name: str, allow_zero: bool = True) -> Optional[str]:
        """Validate a numeric field value."""
        value = self.config_vars.get(field_name, tk.StringVar()).get().strip()
        if not value:
            return None  # Empty is OK

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
        """Validate all configuration fields before applying."""
        fields = [
            ('preview_width', 'Preview Width', False),
            ('preview_height', 'Preview Height', False),
            ('target_fps', 'Target FPS', False),
            ('gaze_circle_radius', 'Circle Radius', False),
            ('gaze_circle_thickness', 'Circle Thickness', False),
            ('gaze_color_worn_r', 'Worn Color R', True),
            ('gaze_color_worn_g', 'Worn Color G', True),
            ('gaze_color_worn_b', 'Worn Color B', True),
            ('gaze_color_not_worn_r', 'Not Worn Color R', True),
            ('gaze_color_not_worn_g', 'Not Worn Color G', True),
            ('gaze_color_not_worn_b', 'Not Worn Color B', True),
        ]

        for field_name, display_name, allow_zero in fields:
            error = self._validate_numeric_field(field_name, display_name, allow_zero)
            if error:
                return error

        # Validate color ranges (0-255)
        color_fields = [
            'gaze_color_worn_r', 'gaze_color_worn_g', 'gaze_color_worn_b',
            'gaze_color_not_worn_r', 'gaze_color_not_worn_g', 'gaze_color_not_worn_b'
        ]
        for field in color_fields:
            value = self.config_vars.get(field, tk.StringVar()).get().strip()
            if value:
                try:
                    num = int(value)
                    if num < 0 or num > 255:
                        return f"{field.replace('_', ' ').title()} must be 0-255"
                except ValueError:
                    pass  # Already caught above

        return None

    def _apply_config(self):
        """Apply configuration changes."""
        # Validate before applying
        error = self._validate_config()
        if error:
            messagebox.showerror("Validation Error", error, parent=self.dialog)
            return

        if not self.runtime or not self.runtime._tracker_config:
            messagebox.showerror("Error", "No tracker configuration available", parent=self.dialog)
            return

        config = self.runtime._tracker_config

        try:
            # Update preview settings
            pw = self.config_vars['preview_width'].get().strip()
            if pw:
                config.preview_width = int(pw)

            ph = self.config_vars['preview_height'].get().strip()
            if ph:
                config.preview_height = int(ph)

            fps = self.config_vars['target_fps'].get().strip()
            if fps:
                config.fps = float(fps)

            # Update gaze settings
            config.gaze_shape = self.config_vars['gaze_shape'].get()

            gcr = self.config_vars['gaze_circle_radius'].get().strip()
            if gcr:
                config.gaze_circle_radius = int(gcr)

            gct = self.config_vars['gaze_circle_thickness'].get().strip()
            if gct:
                config.gaze_circle_thickness = int(gct)

            # Update gaze colors
            for suffix in ['r', 'g', 'b']:
                worn_val = self.config_vars[f'gaze_color_worn_{suffix}'].get().strip()
                if worn_val:
                    setattr(config, f'gaze_color_worn_{suffix}', int(worn_val))

                not_worn_val = self.config_vars[f'gaze_color_not_worn_{suffix}'].get().strip()
                if not_worn_val:
                    setattr(config, f'gaze_color_not_worn_{suffix}', int(not_worn_val))

            # Update recording settings
            config.enable_recording_overlay = self.config_vars['enable_recording_overlay'].get() == '1'
            config.include_gaze_in_recording = self.config_vars['include_gaze_in_recording'].get() == '1'
            config.enable_audio_recording = self.config_vars['enable_audio_recording'].get() == '1'
            config.enable_advanced_gaze_logging = self.config_vars['enable_advanced_gaze_logging'].get() == '1'

            # Update frame processor if it exists
            if self.runtime._frame_processor:
                self.runtime._frame_processor.config = config

            messagebox.showinfo("Success", "Configuration applied", parent=self.dialog)

        except Exception as e:
            self.logger.error("Failed to apply config: %s", e)
            messagebox.showerror("Error", f"Failed to apply: {e}", parent=self.dialog)

    def _on_close(self):
        """Handle dialog close - save position."""
        self._save_position()
        self.dialog.destroy()

    def _load_saved_position_static(self) -> Optional[tuple]:
        """Load saved dialog position from config file."""
        try:
            if not self._config_path.exists():
                return None
            config = ConfigLoader.load(self._config_path, defaults={}, strict=False)
            geometry = config.get(self.CONFIG_DIALOG_GEOMETRY_KEY, "")
            if geometry and "+" in geometry:
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
            if "+" in geometry:
                pos_start = geometry.index("+")
                position = geometry[pos_start:]
                ConfigLoader.update_config_values(
                    self._config_path,
                    {self.CONFIG_DIALOG_GEOMETRY_KEY: position}
                )
                self.logger.debug("Saved config dialog position: %s", position)
        except Exception as e:
            self.logger.debug("Could not save position: %s", e)
