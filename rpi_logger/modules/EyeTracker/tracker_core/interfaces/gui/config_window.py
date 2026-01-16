"""EyeTracker configuration dialog for device settings.

Matches VOG/DRT styling patterns with Theme, RoundedButton, and consistent layout.
Provides configuration for Pupil Labs Neon eye tracker settings.
"""

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional, TYPE_CHECKING
from pathlib import Path

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.core.ui.theme.styles import Theme
from rpi_logger.core.ui.theme.colors import Colors
from rpi_logger.core.ui.theme.widgets import RoundedButton
from rpi_logger.modules.base import ConfigLoader

if TYPE_CHECKING:
    from rpi_logger.modules.EyeTracker.app.eye_tracker_runtime import EyeTrackerRuntime


# Neon scene camera raw specifications (fixed by hardware)
RAW_WIDTH = 1600
RAW_HEIGHT = 1200
RAW_FPS = 30

# Recording resolution options (downsampled from raw)
RECORDING_RESOLUTIONS = [
    (1600, 1200, "1600x1200 (Full)"),
    (1200, 900, "1200x900 (3/4)"),
    (800, 600, "800x600 (1/2)"),
    (400, 300, "400x300 (1/4)"),
]

# Recording FPS options (downsampled from 30 Hz via frame skipping)
# Format: (fps_value, display_label)
RECORDING_FPS_OPTIONS = [
    (15.0, "15 fps"),
    (10.0, "10 fps"),
    (5.0, "5 fps"),
    (2.0, "2 fps"),
    (1.0, "1 fps"),
]


class EyeTrackerConfigWindow:
    """Modal dialog for configuring Eye Tracker settings.

    Configuration options:
    - Recording settings (resolution, frame rate)
    - Preview settings (resolution, frame rate)

    Uses event-driven updates matching VOG/DRT pattern.
    """

    # Config key for saving dialog position
    CONFIG_DIALOG_GEOMETRY_KEY = "eyetracker_config_dialog_geometry"

    def __init__(self, parent: tk.Tk, runtime: "EyeTrackerRuntime"):
        self.runtime = runtime
        self.logger = get_module_logger("EyeTrackerConfigWindow")
        self._config_path = Path(__file__).parent.parent.parent.parent / "config.txt"

        # Window dimensions
        width, height = 340, 240

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

        self._build_recording_settings(main_frame, row=0)
        self._build_preview_settings(main_frame, row=1)
        self._build_buttons(main_frame, row=2)

    def _build_recording_settings(self, parent: ttk.Frame, row: int):
        """Build recording settings section."""
        lf = ttk.LabelFrame(parent, text="Recording")
        lf.grid(row=row, column=0, sticky="new", pady=2, padx=2)
        lf.columnconfigure(1, weight=1)

        # Recording Resolution dropdown
        r = 0
        ttk.Label(lf, text="Resolution:", style='Inframe.TLabel').grid(
            row=r, column=0, sticky="w", padx=5, pady=2
        )
        self.config_vars['recording_resolution'] = tk.StringVar()
        self._recording_res_combo = ttk.Combobox(
            lf,
            textvariable=self.config_vars['recording_resolution'],
            values=[res[2] for res in RECORDING_RESOLUTIONS],
            width=18,
            state="readonly"
        )
        self._recording_res_combo.grid(row=r, column=1, sticky="e", padx=5, pady=2)
        self._recording_res_combo.bind("<<ComboboxSelected>>", self._on_recording_resolution_changed)

        # Recording FPS dropdown
        r += 1
        ttk.Label(lf, text="FPS:", style='Inframe.TLabel').grid(
            row=r, column=0, sticky="w", padx=5, pady=2
        )
        self.config_vars['recording_fps'] = tk.StringVar()
        self._recording_fps_combo = ttk.Combobox(
            lf,
            textvariable=self.config_vars['recording_fps'],
            values=[label for _, label in RECORDING_FPS_OPTIONS],
            width=18,
            state="readonly"
        )
        self._recording_fps_combo.grid(row=r, column=1, sticky="e", padx=5, pady=2)

    def _build_preview_settings(self, parent: ttk.Frame, row: int):
        """Build preview settings section."""
        lf = ttk.LabelFrame(parent, text="Preview")
        lf.grid(row=row, column=0, sticky="new", pady=2, padx=2)
        lf.columnconfigure(1, weight=1)

        # Preview Resolution dropdown (relative to recording - 4 downsampling options)
        r = 0
        ttk.Label(lf, text="Resolution:", style='Inframe.TLabel').grid(
            row=r, column=0, sticky="w", padx=5, pady=2
        )
        self.config_vars['preview_resolution'] = tk.StringVar()
        self._preview_res_combo = ttk.Combobox(
            lf,
            textvariable=self.config_vars['preview_resolution'],
            width=18,
            state="readonly"
        )
        self._preview_res_combo.grid(row=r, column=1, sticky="e", padx=5, pady=2)

        # Preview FPS dropdown
        r += 1
        ttk.Label(lf, text="FPS:", style='Inframe.TLabel').grid(
            row=r, column=0, sticky="w", padx=5, pady=2
        )
        self.config_vars['preview_fps'] = tk.StringVar()
        self._preview_fps_combo = ttk.Combobox(
            lf,
            textvariable=self.config_vars['preview_fps'],
            values=[label for _, label in RECORDING_FPS_OPTIONS],
            width=18,
            state="readonly"
        )
        self._preview_fps_combo.grid(row=r, column=1, sticky="e", padx=5, pady=2)

    def _build_buttons(self, parent: ttk.Frame, row: int):
        """Build common buttons at bottom of dialog."""
        # Use tk.Frame with bg color for RoundedButtons
        btn_frame = tk.Frame(parent, bg=Colors.BG_DARKER)
        btn_frame.grid(row=row, column=0, pady=10, padx=2)

        btn_bg = Colors.BG_DARKER
        RoundedButton(
            btn_frame, text="Apply", command=self._apply_config,
            width=100, height=32, style='default', bg=btn_bg
        ).pack(side=tk.LEFT, padx=4)
        RoundedButton(
            btn_frame, text="Close", command=self._on_close,
            width=100, height=32, style='default', bg=btn_bg
        ).pack(side=tk.LEFT, padx=4)

    def _on_recording_resolution_changed(self, event=None):
        """Update preview resolution options when recording resolution changes."""
        self._update_preview_resolution_options()

    def _update_preview_resolution_options(self):
        """Update preview resolution dropdown based on current recording resolution.

        Preview options are relative to recording resolution with 4 downsampling levels:
        Full, 3/4, 1/2, 1/4 of the recording resolution.
        """
        rec_label = self.config_vars['recording_resolution'].get()

        # Find the recording resolution
        rec_w, rec_h = RECORDING_RESOLUTIONS[0][:2]  # Default to full
        for w, h, label in RECORDING_RESOLUTIONS:
            if label == rec_label:
                rec_w, rec_h = w, h
                break

        # Build preview options: 4 downsampling levels from recording resolution
        preview_options = [
            (rec_w, rec_h, f"{rec_w}x{rec_h} (Full)"),
            (rec_w * 3 // 4, rec_h * 3 // 4, f"{rec_w * 3 // 4}x{rec_h * 3 // 4} (3/4)"),
            (rec_w // 2, rec_h // 2, f"{rec_w // 2}x{rec_h // 2} (1/2)"),
            (rec_w // 4, rec_h // 4, f"{rec_w // 4}x{rec_h // 4} (1/4)"),
        ]

        self._preview_options = preview_options  # Store for apply
        self._preview_res_combo['values'] = [opt[2] for opt in preview_options]

        # Keep current selection if valid, otherwise default to 1/2
        current = self.config_vars['preview_resolution'].get()
        valid_labels = [opt[2] for opt in preview_options]
        if current not in valid_labels:
            self.config_vars['preview_resolution'].set(preview_options[2][2])  # Default to 1/2

    def _load_config(self):
        """Load current configuration from runtime."""
        if not self.runtime or not self.runtime._tracker_config:
            self.logger.debug("No tracker config available")
            return

        config = self.runtime._tracker_config

        # Recording resolution - find closest match
        rec_w, rec_h = config.resolution
        matched_label = RECORDING_RESOLUTIONS[0][2]  # Default to full
        for w, h, label in RECORDING_RESOLUTIONS:
            if w == rec_w and h == rec_h:
                matched_label = label
                break
        self.config_vars['recording_resolution'].set(matched_label)

        # Recording FPS - find closest match
        fps = config.fps
        closest_option = min(RECORDING_FPS_OPTIONS, key=lambda x: abs(x[0] - fps))
        self.config_vars['recording_fps'].set(closest_option[1])

        # Update preview resolution options based on recording resolution
        self._update_preview_resolution_options()

        # Preview resolution - find closest match from current options
        preview_w = config.preview_width
        preview_h = config.preview_height or preview_w * 3 // 4  # Default 4:3 aspect
        # Find best match in preview options
        if hasattr(self, '_preview_options'):
            matched_label = self._preview_options[2][2]  # Default to 1/2
            for w, h, label in self._preview_options:
                if w == preview_w and h == preview_h:
                    matched_label = label
                    break
            self.config_vars['preview_resolution'].set(matched_label)

        # Preview FPS
        preview_fps = getattr(config, 'preview_fps', config.fps)
        closest_option = min(RECORDING_FPS_OPTIONS, key=lambda x: abs(x[0] - preview_fps))
        self.config_vars['preview_fps'].set(closest_option[1])

    def _apply_config(self):
        """Apply configuration changes."""
        if not self.runtime or not self.runtime._tracker_config:
            messagebox.showerror("Error", "No tracker configuration available", parent=self.dialog)
            return

        config = self.runtime._tracker_config

        try:
            # Update recording resolution
            rec_label = self.config_vars['recording_resolution'].get()
            for w, h, label in RECORDING_RESOLUTIONS:
                if label == rec_label:
                    config.resolution = (w, h)
                    break

            # Update recording FPS
            rec_fps_label = self.config_vars['recording_fps'].get()
            for fps_val, label in RECORDING_FPS_OPTIONS:
                if label == rec_fps_label:
                    config.fps = fps_val
                    break

            # Update preview resolution (from relative options)
            preview_label = self.config_vars['preview_resolution'].get()
            if hasattr(self, '_preview_options'):
                for w, h, label in self._preview_options:
                    if label == preview_label:
                        config.preview_width = w
                        config.preview_height = h
                        break

            # Update preview FPS
            preview_fps_label = self.config_vars['preview_fps'].get()
            for fps_val, label in RECORDING_FPS_OPTIONS:
                if label == preview_fps_label:
                    config.preview_fps = fps_val
                    break

            # Update frame processor if it exists
            if self.runtime._frame_processor:
                self.runtime._frame_processor.config = config

            # Update recording manager if it exists
            if self.runtime._recording_manager:
                self.runtime._recording_manager.config = config
                # Update video encoder resolution
                self.runtime._recording_manager._world_video_encoder.resolution = config.resolution
                self.runtime._recording_manager._world_video_encoder.fps = config.fps

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
        except Exception:
            pass  # Position save is best-effort
