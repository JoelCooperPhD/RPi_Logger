"""Unified camera settings window with resolution/FPS and interactive camera controls."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger

try:  # pragma: no cover - GUI availability varies
    import tkinter as tk  # type: ignore
    from tkinter import ttk  # type: ignore
except Exception:  # pragma: no cover
    tk = None  # type: ignore
    ttk = None  # type: ignore

try:
    from rpi_logger.core.ui.theme.styles import Theme
    from rpi_logger.core.ui.theme.colors import Colors
    from rpi_logger.core.ui.theme.widgets import RoundedButton

    HAS_THEME = True
except ImportError:
    HAS_THEME = False
    Theme = None  # type: ignore
    Colors = None  # type: ignore
    RoundedButton = None  # type: ignore

if TYPE_CHECKING:
    from rpi_logger.modules.Cameras.runtime.state import CameraCapabilities, ControlInfo, ControlType

# Re-export DEFAULT_SETTINGS for backwards compatibility
DEFAULT_SETTINGS = {
    "preview_resolution": "",
    "preview_fps": "5",
    "record_resolution": "",
    "record_fps": "15",
    "overlay": "true",
}

# Essential controls to display (in order)
ESSENTIAL_CONTROLS = [
    "Brightness",
    "Contrast",
    "Saturation",
    "Hue",
    "Exposure",
    "AutoExposure",
    "Gain",
    "WhiteBalanceBlueU",
    "WhiteBalanceRedV",
    "Focus",
    "AutoFocus",
    # Picam equivalents
    "AwbMode",
    "AeExposureMode",
    "ExposureTime",
    "AnalogueGain",
    "Brightness",
    "Contrast",
    "Saturation",
    "AfMode",
]

# Control dependencies: child -> (parent, values_that_enable_child)
# When parent's value is NOT in the enable set, the child control is disabled
CONTROL_DEPENDENCIES = {
    # USB cameras: Gain/Exposure only work in Manual Mode (value starts with "1:")
    "Gain": ("AutoExposure", lambda v: str(v).startswith("1:") or v is True),
    "Exposure": ("AutoExposure", lambda v: str(v).startswith("1:") or v is True),
    # Picam: AnalogueGain/ExposureTime work when AeExposureMode is "Custom" or "Off"
    "AnalogueGain": ("AeExposureMode", lambda v: v in ("Custom", "Off")),
    "ExposureTime": ("AeExposureMode", lambda v: v in ("Custom", "Off")),
}


class CameraSettingsWindow:
    """Pop-out window with resolution/FPS settings and interactive camera controls."""

    def __init__(
        self,
        root=None,
        *,
        logger: LoggerLike = None,
        on_apply_resolution: Optional[Callable[[str, Dict[str, str]], None]] = None,
        on_control_change: Optional[Callable[[str, str, Any], None]] = None,
        on_reprobe: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._root = root
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._on_apply_resolution = on_apply_resolution
        self._on_control_change = on_control_change
        self._on_reprobe = on_reprobe
        self._window: Optional[tk.Toplevel] = None
        self._toggle_var: Optional[tk.BooleanVar] = None
        self._active_camera: Optional[str] = None

        # Resolution/FPS state per camera
        self._latest: Dict[str, Dict[str, str]] = {}
        self._options: Dict[str, Dict[str, List[str]]] = {}

        # Capabilities per camera
        self._capabilities: Dict[str, "CameraCapabilities"] = {}
        self._camera_info: Dict[str, Dict[str, str]] = {}  # model, backend, mode_count

        # UI widgets (created lazily)
        self._preview_res_var: Optional[tk.StringVar] = None
        self._preview_fps_var: Optional[tk.StringVar] = None
        self._record_res_var: Optional[tk.StringVar] = None
        self._record_fps_var: Optional[tk.StringVar] = None
        self._preview_res_combo = None
        self._preview_fps_combo = None
        self._record_res_combo = None
        self._record_fps_combo = None

        # Control widgets - keyed by control name
        self._control_widgets: Dict[str, Dict[str, Any]] = {}  # {name: {var, widget, reset_btn, ...}}
        self._controls_frame: Optional[tk.Widget] = None
        self._info_labels: Dict[str, tk.Label] = {}

        self._suppress_change = False
        self._debounce_id: Optional[str] = None

    def bind_toggle_var(self, var: "tk.BooleanVar") -> None:
        self._toggle_var = var

    # ------------------------------------------------------------------
    # Public API - Camera management
    # ------------------------------------------------------------------

    def set_active_camera(self, camera_id: Optional[str]) -> None:
        self._active_camera = camera_id
        if camera_id:
            self._latest.setdefault(camera_id, dict(DEFAULT_SETTINGS))
            self._options.setdefault(camera_id, {})
        self._refresh_ui()
        self._update_title()

    def update_camera_defaults(self, camera_id: str) -> None:
        self._latest.setdefault(camera_id, dict(DEFAULT_SETTINGS))
        if self._active_camera == camera_id:
            self._refresh_resolution_ui()

    def set_camera_settings(self, camera_id: str, settings: Dict[str, str]) -> None:
        merged = dict(DEFAULT_SETTINGS)
        merged.update(settings or {})
        self._latest[camera_id] = merged
        if self._active_camera == camera_id:
            self._refresh_resolution_ui()

    def update_camera_options(
        self,
        camera_id: str,
        *,
        preview_resolutions: Optional[List[str]] = None,
        record_resolutions: Optional[List[str]] = None,
        preview_fps_values: Optional[List[str]] = None,
        record_fps_values: Optional[List[str]] = None,
    ) -> None:
        """Update available resolution/FPS options for a camera."""
        self._options.setdefault(camera_id, {})
        if preview_resolutions is not None:
            self._options[camera_id]["preview_resolutions"] = preview_resolutions
        if record_resolutions is not None:
            self._options[camera_id]["record_resolutions"] = record_resolutions
        if preview_fps_values is not None:
            self._options[camera_id]["preview_fps_values"] = preview_fps_values
        if record_fps_values is not None:
            self._options[camera_id]["record_fps_values"] = record_fps_values

        if camera_id == self._active_camera:
            self._clamp_settings_to_options(camera_id)
            self._refresh_resolution_ui()

    def update_camera_capabilities(
        self,
        camera_id: str,
        capabilities: "CameraCapabilities",
        *,
        hw_model: Optional[str] = None,
        backend: Optional[str] = None,
    ) -> None:
        """Update capabilities for a camera, enabling control widgets."""
        # Check if controls actually changed before storing
        old_caps = self._capabilities.get(camera_id)
        old_controls = old_caps.controls if old_caps else None
        new_controls = capabilities.controls if capabilities else None
        controls_changed = old_controls != new_controls

        self._capabilities[camera_id] = capabilities

        # Format backend nicely: "usb" -> "USB", "picam" -> "Pi Camera"
        backend_display = backend or "Unknown"
        if backend_display.lower() == "usb":
            backend_display = "USB"
        elif backend_display.lower() == "picam":
            backend_display = "Pi Camera"

        # Count unique resolutions for display
        mode_count = 0
        if capabilities and capabilities.modes:
            unique_sizes = set()
            for m in capabilities.modes:
                if hasattr(m, "size"):
                    unique_sizes.add(m.size)
            mode_count = len(unique_sizes)

        self._camera_info[camera_id] = {
            "model": hw_model or "Unknown",
            "backend": backend_display,
            "mode_count": str(mode_count) if mode_count else "0",
        }
        if camera_id == self._active_camera:
            # Only rebuild controls if they actually changed
            if controls_changed:
                self._rebuild_controls_section()
            self._refresh_info_section()

    def remove_camera(self, camera_id: str) -> None:
        if self._active_camera == camera_id:
            self._active_camera = None
        self._refresh_ui()

    # ------------------------------------------------------------------
    # Public API - Window management
    # ------------------------------------------------------------------

    def show(self) -> None:
        if tk is None or self._root is None:
            return
        self._ensure_window()
        if self._window:
            try:
                self._window.deiconify()
                self._window.lift()
            except Exception:
                self._logger.debug("Unable to raise settings window", exc_info=True)
        self._refresh_ui()
        self._update_title()
        if self._toggle_var:
            self._toggle_var.set(True)

    def hide(self) -> None:
        if not self._window:
            if self._toggle_var:
                self._toggle_var.set(False)
            return
        try:
            self._window.withdraw()
        except Exception:
            try:
                self._window.destroy()
            except Exception:
                self._logger.debug("Unable to hide settings window", exc_info=True)
            finally:
                self._window = None
        if self._toggle_var:
            self._toggle_var.set(False)

    def has_panel(self) -> bool:
        return self._window is not None and self._window.winfo_exists()

    def get_latest_settings(self, camera_id: str) -> Dict[str, str]:
        return self._latest.get(camera_id, dict(DEFAULT_SETTINGS))

    def set_latest_settings(self, camera_id: str, settings: Dict[str, str]) -> None:
        self._latest.setdefault(camera_id, dict(DEFAULT_SETTINGS))
        self._latest[camera_id].update(settings)

    def apply_to_panel(self, settings: Dict[str, str]) -> bool:
        if not self._window:
            return False
        try:
            self._apply_settings_to_ui(settings)
            return True
        except Exception:
            self._logger.debug("Settings panel apply failed", exc_info=True)
            return False

    # ------------------------------------------------------------------
    # Window construction
    # ------------------------------------------------------------------

    def _ensure_window(self) -> None:
        if self._window and self._window.winfo_exists():
            return
        try:
            self._window = tk.Toplevel(self._root)
        except Exception:
            self._logger.debug("Failed to create settings window", exc_info=True)
            self._window = None
            return

        self._window.title("Camera Settings")
        self._window.protocol("WM_DELETE_WINDOW", self._handle_close)
        self._window.minsize(320, 200)

        if HAS_THEME and Theme is not None:
            try:
                Theme.configure_toplevel(self._window)
            except Exception:
                pass

        self._build_ui()
        self._update_title()

    def _build_ui(self) -> None:
        assert tk is not None and ttk is not None

        main_frame = ttk.Frame(self._window, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(0, weight=1)

        self._build_resolution_section(main_frame, row=0)
        self._build_controls_section(main_frame, row=1)
        self._build_info_section(main_frame, row=2)
        self._build_buttons_section(main_frame, row=3)

    def _build_resolution_section(self, parent, row: int) -> None:
        """Build the resolution and FPS settings section."""
        lf = ttk.LabelFrame(parent, text="Resolution & FPS")
        lf.grid(row=row, column=0, sticky="new", pady=(0, 8), padx=2)
        lf.columnconfigure(1, weight=1)

        # Use Inframe styles for widgets inside LabelFrames
        label_style = "Inframe.TLabel" if HAS_THEME else ""
        combo_style = "Inframe.TCombobox" if HAS_THEME else ""

        # Preview Resolution
        r = 0
        ttk.Label(lf, text="Preview Resolution:", style=label_style).grid(row=r, column=0, sticky="w", padx=5, pady=2)
        self._preview_res_var = tk.StringVar(value=DEFAULT_SETTINGS["preview_resolution"])
        self._preview_res_combo = ttk.Combobox(lf, textvariable=self._preview_res_var, values=(), state="readonly", width=14, style=combo_style)
        self._preview_res_combo.grid(row=r, column=1, sticky="e", padx=5, pady=2)

        # Preview FPS
        r += 1
        ttk.Label(lf, text="Preview FPS:", style=label_style).grid(row=r, column=0, sticky="w", padx=5, pady=2)
        self._preview_fps_var = tk.StringVar(value=DEFAULT_SETTINGS["preview_fps"])
        self._preview_fps_combo = ttk.Combobox(lf, textvariable=self._preview_fps_var, values=("1", "2", "5", "10", "15"), state="readonly", width=14, style=combo_style)
        self._preview_fps_combo.grid(row=r, column=1, sticky="e", padx=5, pady=2)

        # Record Resolution
        r += 1
        ttk.Label(lf, text="Record Resolution:", style=label_style).grid(row=r, column=0, sticky="w", padx=5, pady=2)
        self._record_res_var = tk.StringVar(value=DEFAULT_SETTINGS["record_resolution"])
        self._record_res_combo = ttk.Combobox(lf, textvariable=self._record_res_var, values=(), state="readonly", width=14, style=combo_style)
        self._record_res_combo.grid(row=r, column=1, sticky="e", padx=5, pady=2)

        # Record FPS
        r += 1
        ttk.Label(lf, text="Record FPS:", style=label_style).grid(row=r, column=0, sticky="w", padx=5, pady=2)
        self._record_fps_var = tk.StringVar(value=DEFAULT_SETTINGS["record_fps"])
        self._record_fps_combo = ttk.Combobox(lf, textvariable=self._record_fps_var, values=("15", "24", "30", "60"), state="readonly", width=14, style=combo_style)
        self._record_fps_combo.grid(row=r, column=1, sticky="e", padx=5, pady=2)

    def _build_controls_section(self, parent, row: int) -> None:
        """Build the camera controls section (populated dynamically)."""
        lf = ttk.LabelFrame(parent, text="Camera Controls")
        lf.grid(row=row, column=0, sticky="new", pady=(0, 8), padx=2)
        lf.columnconfigure(1, weight=1)
        self._controls_frame = lf

        # Use Inframe style for placeholder
        label_style = "Inframe.Secondary.TLabel" if HAS_THEME else ""

        # Placeholder - will be rebuilt when capabilities arrive
        self._controls_placeholder = ttk.Label(lf, text="No camera selected", style=label_style)
        self._controls_placeholder.grid(row=0, column=0, columnspan=3, padx=10, pady=10)

    def _build_info_section(self, parent, row: int) -> None:
        """Build the camera info section (read-only)."""
        lf = ttk.LabelFrame(parent, text="Camera Info")
        lf.grid(row=row, column=0, sticky="new", pady=(0, 4), padx=2)
        lf.columnconfigure(1, weight=1)

        # Use Inframe styles for widgets inside LabelFrames
        label_style = "Inframe.TLabel" if HAS_THEME else ""

        info_items = [("Model:", "model"), ("Backend:", "backend")]
        for i, (label, key) in enumerate(info_items):
            ttk.Label(lf, text=label, style=label_style).grid(row=i, column=0, sticky="w", padx=5, pady=1)
            val_label = ttk.Label(lf, text="-", style=label_style)
            val_label.grid(row=i, column=1, sticky="e", padx=5, pady=1)
            self._info_labels[key] = val_label

    def _build_buttons_section(self, parent, row: int) -> None:
        """Build the bottom buttons section with Apply and Reprobe."""
        btn_frame = ttk.Frame(parent)
        btn_frame.grid(row=row, column=0, sticky="e", pady=(8, 0), padx=2)

        if HAS_THEME and RoundedButton is not None and Colors is not None:
            bg = Colors.BG_DARKER if Colors else "#2b2b2b"
            apply_btn = RoundedButton(btn_frame, text="Apply", command=self._apply_resolution, width=100, height=30, style="default", bg=bg)
            apply_btn.pack(side=tk.RIGHT, padx=(4, 0))
            reprobe_btn = RoundedButton(btn_frame, text="Reprobe", command=self._reprobe_camera, width=100, height=30, style="default", bg=bg)
            reprobe_btn.pack(side=tk.RIGHT)
        else:
            apply_btn = ttk.Button(btn_frame, text="Apply", command=self._apply_resolution)
            apply_btn.pack(side=tk.RIGHT, padx=(4, 0))
            reprobe_btn = ttk.Button(btn_frame, text="Reprobe", command=self._reprobe_camera)
            reprobe_btn.pack(side=tk.RIGHT)

    # ------------------------------------------------------------------
    # Controls section - dynamic rebuild
    # ------------------------------------------------------------------

    def _rebuild_controls_section(self) -> None:
        """Rebuild control widgets based on current camera's capabilities."""
        if not self._controls_frame or not self._window:
            return

        # Clear existing control widgets
        for child in self._controls_frame.winfo_children():
            child.destroy()
        self._control_widgets.clear()

        # Use Inframe style for placeholder labels
        placeholder_style = "Inframe.Secondary.TLabel" if HAS_THEME else ""

        if not self._active_camera:
            ttk.Label(self._controls_frame, text="No camera selected", style=placeholder_style).grid(row=0, column=0, columnspan=3, padx=10, pady=10)
            return

        caps = self._capabilities.get(self._active_camera)
        if not caps or not caps.controls:
            ttk.Label(self._controls_frame, text="No controls available", style=placeholder_style).grid(row=0, column=0, columnspan=3, padx=10, pady=10)
            return

        # Filter to essential controls that exist
        available_controls = []
        seen_names = set()
        for name in ESSENTIAL_CONTROLS:
            if name in caps.controls and name not in seen_names:
                available_controls.append((name, caps.controls[name]))
                seen_names.add(name)

        if not available_controls:
            ttk.Label(self._controls_frame, text="No controls available", style=placeholder_style).grid(row=0, column=0, columnspan=3, padx=10, pady=10)
            return

        # Build widgets for each control
        for row_idx, (name, ctrl) in enumerate(available_controls):
            self._build_control_widget(self._controls_frame, row_idx, name, ctrl)

        # Apply initial dependent control states
        self._update_dependent_control_states()

    def _build_control_widget(self, parent, row: int, name: str, ctrl: "ControlInfo") -> None:
        """Build a single control widget based on control type."""
        from rpi_logger.modules.Cameras.runtime.state import ControlType

        # Inframe styles for widgets inside LabelFrames
        label_style = "Inframe.TLabel" if HAS_THEME else ""
        check_style = "Inframe.TCheckbutton" if HAS_THEME else ""
        combo_style = "Inframe.TCombobox" if HAS_THEME else ""
        frame_style = "Inframe.TFrame" if HAS_THEME else ""
        scale_style = "Inframe.Horizontal.TScale" if HAS_THEME else ""

        # Label
        display_name = self._format_control_name(name)
        ttk.Label(parent, text=f"{display_name}:", style=label_style).grid(row=row, column=0, sticky="w", padx=5, pady=2)

        widget_info: Dict[str, Any] = {"control": ctrl, "name": name}

        if ctrl.control_type == ControlType.BOOLEAN:
            # Checkbutton
            var = tk.BooleanVar(value=bool(ctrl.current_value))
            cb = ttk.Checkbutton(parent, variable=var, command=lambda n=name: self._on_control_changed(n), style=check_style)
            cb.grid(row=row, column=1, sticky="w", padx=5, pady=2)
            widget_info["var"] = var
            widget_info["widget"] = cb

        elif ctrl.control_type == ControlType.ENUM and ctrl.options:
            # Combobox for enum
            var = tk.StringVar(value=str(ctrl.current_value) if ctrl.current_value is not None else "")
            combo = ttk.Combobox(parent, textvariable=var, values=[str(o) for o in ctrl.options], state="readonly", width=12, style=combo_style)
            combo.grid(row=row, column=1, sticky="ew", padx=5, pady=2)
            combo.bind("<<ComboboxSelected>>", lambda e, n=name: self._on_control_changed(n))
            widget_info["var"] = var
            widget_info["widget"] = combo

        elif ctrl.min_value is not None and ctrl.max_value is not None:
            # Scale (slider) for numeric with range
            frame = ttk.Frame(parent, style=frame_style)
            frame.grid(row=row, column=1, sticky="ew", padx=5, pady=2)
            frame.columnconfigure(0, weight=1)

            min_val = float(ctrl.min_value)
            max_val = float(ctrl.max_value)
            current = float(ctrl.current_value) if ctrl.current_value is not None else min_val

            var = tk.DoubleVar(value=current)

            # Determine resolution (step)
            resolution = ctrl.step if ctrl.step else 1.0
            if ctrl.control_type == ControlType.INTEGER:
                resolution = max(1, int(resolution))

            scale = ttk.Scale(frame, from_=min_val, to=max_val, variable=var, orient=tk.HORIZONTAL, command=lambda v, n=name: self._on_scale_changed(n, v), style=scale_style)
            scale.grid(row=0, column=0, sticky="ew")

            # Value label
            val_label = ttk.Label(frame, text=self._format_value(current, ctrl), width=6, anchor="e", style=label_style)
            val_label.grid(row=0, column=1, padx=(4, 0))

            widget_info["var"] = var
            widget_info["widget"] = scale
            widget_info["value_label"] = val_label
            widget_info["resolution"] = resolution

        else:
            # Entry for unknown or unbounded
            var = tk.StringVar(value=str(ctrl.current_value) if ctrl.current_value is not None else "")
            entry = ttk.Entry(parent, textvariable=var, width=10)
            entry.grid(row=row, column=1, sticky="e", padx=5, pady=2)
            entry.bind("<Return>", lambda e, n=name: self._on_control_changed(n))
            entry.bind("<FocusOut>", lambda e, n=name: self._on_control_changed(n))
            widget_info["var"] = var
            widget_info["widget"] = entry

        # Reset button (if default available)
        if ctrl.default_value is not None:
            reset_btn = ttk.Button(parent, text="R", width=2, command=lambda n=name: self._reset_control(n))
            reset_btn.grid(row=row, column=2, padx=(2, 5), pady=2)
            widget_info["reset_btn"] = reset_btn

        self._control_widgets[name] = widget_info

    def _format_control_name(self, name: str) -> str:
        """Format control name for display."""
        # Insert spaces before capitals: AutoExposure -> Auto Exposure
        result = []
        for i, char in enumerate(name):
            if i > 0 and char.isupper():
                result.append(" ")
            result.append(char)
        return "".join(result)

    def _update_dependent_control_states(self) -> None:
        """Enable/disable controls based on their parent control's value."""
        # Determine label style for disabled state
        if HAS_THEME and Colors is not None:
            disabled_fg = Colors.FG_MUTED
            enabled_fg = Colors.FG_PRIMARY
        else:
            disabled_fg = "#6c7a89"
            enabled_fg = "#ecf0f1"

        for child_name, (parent_name, is_enabled_func) in CONTROL_DEPENDENCIES.items():
            child_info = self._control_widgets.get(child_name)
            parent_info = self._control_widgets.get(parent_name)

            if not child_info or not parent_info:
                continue

            parent_var = parent_info.get("var")
            if not parent_var:
                continue

            try:
                parent_value = parent_var.get()
            except tk.TclError:
                continue

            # Determine if child should be enabled
            should_enable = is_enabled_func(parent_value)
            state = "normal" if should_enable else "disabled"

            # Update child widget state
            widget = child_info.get("widget")
            if widget:
                try:
                    widget.config(state=state)
                except tk.TclError:
                    pass

            # Update value label appearance (for sliders)
            value_label = child_info.get("value_label")
            if value_label:
                try:
                    value_label.config(foreground=enabled_fg if should_enable else disabled_fg)
                except tk.TclError:
                    pass

            # Update reset button state
            reset_btn = child_info.get("reset_btn")
            if reset_btn:
                try:
                    reset_btn.config(state=state)
                except tk.TclError:
                    pass

    def _format_value(self, value: float, ctrl: "ControlInfo") -> str:
        """Format a value for display."""
        from rpi_logger.modules.Cameras.runtime.state import ControlType

        if ctrl.control_type == ControlType.INTEGER:
            return str(int(value))
        return f"{value:.1f}"

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_scale_changed(self, name: str, value: str) -> None:
        """Handle scale value change with debouncing."""
        widget_info = self._control_widgets.get(name)
        if not widget_info:
            return

        # Update value label
        val_label = widget_info.get("value_label")
        ctrl = widget_info.get("control")
        if val_label and ctrl:
            val_label.config(text=self._format_value(float(value), ctrl))

        # Debounce the actual control change
        if self._debounce_id:
            try:
                self._window.after_cancel(self._debounce_id)
            except Exception:
                pass
        self._debounce_id = self._window.after(100, lambda: self._on_control_changed(name))

    def _on_control_changed(self, name: str) -> None:
        """Handle control value change - apply immediately."""
        if self._suppress_change or not self._active_camera:
            return

        widget_info = self._control_widgets.get(name)
        if not widget_info:
            return

        var = widget_info.get("var")
        ctrl = widget_info.get("control")
        if not var or not ctrl:
            return

        # Get value based on type
        from rpi_logger.modules.Cameras.runtime.state import ControlType

        try:
            if ctrl.control_type == ControlType.BOOLEAN:
                value = var.get()
            elif ctrl.control_type == ControlType.INTEGER:
                value = int(float(var.get()))
            elif ctrl.control_type == ControlType.FLOAT:
                value = float(var.get())
            elif ctrl.control_type == ControlType.ENUM:
                # Handle "value:label" format from v4l2 menu options
                raw_value = var.get()
                if ":" in str(raw_value):
                    value = int(raw_value.split(":")[0])
                else:
                    value = raw_value
            else:
                value = var.get()
        except (ValueError, tk.TclError):
            self._logger.debug("Invalid control value for %s", name)
            return

        self._logger.debug("Control changed: %s = %s", name, value)

        if self._on_control_change:
            try:
                self._on_control_change(self._active_camera, name, value)
            except Exception:
                self._logger.debug("Control change callback failed", exc_info=True)

        # Update dependent control states if this is a parent control
        if any(parent == name for parent, _ in CONTROL_DEPENDENCIES.values()):
            self._update_dependent_control_states()

    def _reset_control(self, name: str) -> None:
        """Reset a control to its default value."""
        widget_info = self._control_widgets.get(name)
        if not widget_info:
            return

        ctrl = widget_info.get("control")
        var = widget_info.get("var")
        if not ctrl or not var or ctrl.default_value is None:
            return

        self._suppress_change = True
        try:
            var.set(ctrl.default_value)
            # Update value label if present
            val_label = widget_info.get("value_label")
            if val_label:
                val_label.config(text=self._format_value(float(ctrl.default_value), ctrl))
        finally:
            self._suppress_change = False

        # Trigger the change
        self._on_control_changed(name)

    def _apply_resolution(self) -> None:
        """Apply resolution/FPS settings."""
        if not self._active_camera:
            return

        settings = self._get_resolution_settings()
        self._latest[self._active_camera] = settings

        if self._on_apply_resolution:
            try:
                self._on_apply_resolution(self._active_camera, settings)
            except Exception:
                self._logger.debug("Resolution apply callback failed", exc_info=True)

    def _reprobe_camera(self) -> None:
        """Request reprobing of the active camera's capabilities."""
        if not self._active_camera:
            return
        if self._on_reprobe:
            try:
                self._on_reprobe(self._active_camera)
            except Exception:
                self._logger.debug("Reprobe callback failed", exc_info=True)

    def _handle_close(self) -> None:
        self.hide()

    # ------------------------------------------------------------------
    # UI refresh helpers
    # ------------------------------------------------------------------

    def _refresh_ui(self) -> None:
        """Refresh all UI sections."""
        if not self._window:
            return
        self._refresh_resolution_ui()
        self._rebuild_controls_section()
        self._refresh_info_section()

    def _refresh_resolution_ui(self) -> None:
        """Refresh resolution/FPS comboboxes."""
        if not self._window or not self._preview_res_var:
            return

        self._suppress_change = True
        try:
            if self._active_camera:
                settings = self._latest.get(self._active_camera, dict(DEFAULT_SETTINGS))
                opts = self._options.get(self._active_camera, {})

                # Update combobox values
                if self._preview_res_combo:
                    self._preview_res_combo["values"] = opts.get("preview_resolutions", [])
                if self._preview_fps_combo:
                    self._preview_fps_combo["values"] = opts.get("preview_fps_values", ["1", "2", "5", "10", "15"])
                if self._record_res_combo:
                    self._record_res_combo["values"] = opts.get("record_resolutions", [])
                if self._record_fps_combo:
                    self._record_fps_combo["values"] = opts.get("record_fps_values", ["15", "24", "30", "60"])

                # Set current values
                self._preview_res_var.set(settings.get("preview_resolution", ""))
                self._preview_fps_var.set(settings.get("preview_fps", "5"))
                self._record_res_var.set(settings.get("record_resolution", ""))
                self._record_fps_var.set(settings.get("record_fps", "15"))
            else:
                # Clear values
                self._preview_res_var.set("")
                self._preview_fps_var.set("5")
                self._record_res_var.set("")
                self._record_fps_var.set("15")
        finally:
            self._suppress_change = False

    def _refresh_info_section(self) -> None:
        """Refresh camera info labels."""
        if not self._active_camera:
            for label in self._info_labels.values():
                label.config(text="-")
            return

        info = self._camera_info.get(self._active_camera, {})
        for key, label in self._info_labels.items():
            label.config(text=info.get(key, "-"))

    def _apply_settings_to_ui(self, settings: Dict[str, str]) -> None:
        """Apply settings dict to resolution UI."""
        if not self._preview_res_var:
            return
        self._suppress_change = True
        try:
            if "preview_resolution" in settings:
                self._preview_res_var.set(settings["preview_resolution"])
            if "preview_fps" in settings:
                self._preview_fps_var.set(settings["preview_fps"])
            if "record_resolution" in settings:
                self._record_res_var.set(settings["record_resolution"])
            if "record_fps" in settings:
                self._record_fps_var.set(settings["record_fps"])
        finally:
            self._suppress_change = False

    def _get_resolution_settings(self) -> Dict[str, str]:
        """Get current resolution/FPS settings from UI."""
        return {
            "preview_resolution": (self._preview_res_var.get() or "").strip() if self._preview_res_var else "",
            "preview_fps": (self._preview_fps_var.get() or "").strip() if self._preview_fps_var else "5",
            "record_resolution": (self._record_res_var.get() or "").strip() if self._record_res_var else "",
            "record_fps": (self._record_fps_var.get() or "").strip() if self._record_fps_var else "15",
            "overlay": "true",
        }

    def _clamp_settings_to_options(self, camera_id: str) -> None:
        """Ensure stored settings are within available options."""
        latest = self._latest.setdefault(camera_id, dict(DEFAULT_SETTINGS))
        opts = self._options.get(camera_id, {})

        preview_res = opts.get("preview_resolutions", [])
        if preview_res and latest.get("preview_resolution") not in preview_res:
            latest["preview_resolution"] = preview_res[0]

        record_res = opts.get("record_resolutions", [])
        if record_res and latest.get("record_resolution") not in record_res:
            latest["record_resolution"] = record_res[0]

        preview_fps = opts.get("preview_fps_values", [])
        if preview_fps and latest.get("preview_fps") not in preview_fps:
            latest["preview_fps"] = preview_fps[0] if preview_fps else "5"

        record_fps = opts.get("record_fps_values", [])
        if record_fps and latest.get("record_fps") not in record_fps:
            latest["record_fps"] = record_fps[0] if record_fps else "15"

    def _update_title(self) -> None:
        if not self._window:
            return
        camera_label = self._active_camera or "No camera selected"
        try:
            self._window.title(f"Camera Settings - {camera_label}")
        except Exception:
            self._logger.debug("Unable to set settings window title", exc_info=True)


# Backwards compatibility alias
SettingsWindow = CameraSettingsWindow
