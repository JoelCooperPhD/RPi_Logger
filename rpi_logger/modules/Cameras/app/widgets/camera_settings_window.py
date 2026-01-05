"""Camera settings window: resolution/FPS and live controls."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.base.camera_validator import CapabilityValidator

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

try:
    from rpi_logger.modules.Cameras.app.widgets.sensor_info_dialog import show_sensor_info

    HAS_SENSOR_DIALOG = True
except ImportError:
    HAS_SENSOR_DIALOG = False
    show_sensor_info = None  # type: ignore

if TYPE_CHECKING:
    from rpi_logger.modules.Cameras.camera_core.state import CameraCapabilities, ControlInfo, ControlType

DEFAULT_SETTINGS = {
    "preview_resolution": "", "preview_fps": "5",
    "record_resolution": "", "record_fps": "15",
    "overlay": "true", "record_audio": "true",
}

IMAGE_CONTROLS = ["Brightness", "Contrast", "Saturation", "Hue"]
EXPOSURE_FOCUS_CONTROLS = [
    "AutoExposure", "AeExposureMode", "Exposure", "ExposureTime", "Gain", "AnalogueGain",
    "AutoFocus", "FocusAutomaticContinuous", "AfMode", "Focus", "FocusAbsolute",
    "AwbMode", "WhiteBalanceBlueU", "WhiteBalanceRedV",
]
ESSENTIAL_CONTROLS = IMAGE_CONTROLS + EXPOSURE_FOCUS_CONTROLS

# Control dependencies: child -> (parent, enable_condition)
CONTROL_DEPENDENCIES = {
    "Gain": ("AutoExposure", lambda v: str(v).startswith("1:") or v is True),
    "Exposure": ("AutoExposure", lambda v: str(v).startswith("1:") or v is True),
    "FocusAbsolute": ("FocusAutomaticContinuous", lambda v: not v),
    "AnalogueGain": ("AeExposureMode", lambda v: v in ("Custom", "Off")),
    "ExposureTime": ("AeExposureMode", lambda v: v in ("Custom", "Off")),
}


class CameraSettingsWindow:
    """Pop-out window with resolution/FPS and camera controls."""

    def __init__(self, root=None, *, logger: LoggerLike = None,
                 on_apply_resolution: Optional[Callable[[str, Dict[str, str]], None]] = None,
                 on_control_change: Optional[Callable[[str, str, Any], None]] = None,
                 on_reprobe: Optional[Callable[[str], None]] = None) -> None:
        self._root = root
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._on_apply_resolution = on_apply_resolution
        self._on_control_change = on_control_change
        self._on_reprobe = on_reprobe
        self._window: Optional[tk.Toplevel] = None
        self._toggle_var: Optional[tk.BooleanVar] = None
        self._active_camera: Optional[str] = None
        self._latest: Dict[str, Dict[str, str]] = {}
        self._options: Dict[str, Dict[str, List[str]]] = {}
        self._capabilities: Dict[str, "CameraCapabilities"] = {}
        self._validators: Dict[str, CapabilityValidator] = {}
        self._camera_info: Dict[str, Dict[str, Any]] = {}
        self._preview_res_var: Optional[tk.StringVar] = None
        self._preview_fps_var: Optional[tk.StringVar] = None
        self._record_res_var: Optional[tk.StringVar] = None
        self._record_fps_var: Optional[tk.StringVar] = None
        self._record_audio_var: Optional[tk.BooleanVar] = None
        self._preview_res_combo = None
        self._preview_fps_combo = None
        self._record_res_combo = None
        self._record_fps_combo = None
        self._record_audio_cb = None
        self._record_audio_frame = None
        self._has_audio_sibling: Dict[str, bool] = {}
        self._control_widgets: Dict[str, Dict[str, Any]] = {}
        self._image_controls_card: Optional[tk.Widget] = None
        self._exposure_controls_card: Optional[tk.Widget] = None
        self._info_label: Optional[tk.Label] = None
        self._info_btn: Optional[tk.Widget] = None
        self._info_btn_enabled: bool = False
        self._suppress_change = False
        self._debounce_id: Optional[str] = None

    def bind_toggle_var(self, var: "tk.BooleanVar") -> None:
        self._toggle_var = var

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

    def set_camera_has_audio_sibling(self, camera_id: str, has_audio: bool) -> None:
        """Set whether camera has built-in mic (controls audio checkbox visibility)."""
        self._has_audio_sibling[camera_id] = has_audio
        if self._active_camera == camera_id:
            self._update_audio_checkbox_visibility()

    def set_camera_settings(self, camera_id: str, settings: Dict[str, str]) -> None:
        merged = dict(DEFAULT_SETTINGS)
        merged.update(settings or {})
        self._latest[camera_id] = merged
        self._clamp_settings_to_options(camera_id)
        if self._active_camera == camera_id:
            self._refresh_resolution_ui()

    def update_camera_options(self, camera_id: str, *,
                              preview_resolutions: Optional[List[str]] = None,
                              record_resolutions: Optional[List[str]] = None,
                              preview_fps_values: Optional[List[str]] = None,
                              record_fps_values: Optional[List[str]] = None) -> None:
        """Update available resolution/FPS options."""
        opts = self._options.setdefault(camera_id, {})
        if preview_resolutions is not None:
            opts["preview_resolutions"] = preview_resolutions
        if record_resolutions is not None:
            opts["record_resolutions"] = record_resolutions
        if preview_fps_values is not None:
            opts["preview_fps_values"] = preview_fps_values
        if record_fps_values is not None:
            opts["record_fps_values"] = record_fps_values
        self._clamp_settings_to_options(camera_id)
        if camera_id == self._active_camera:
            self._refresh_resolution_ui()

    def update_camera_capabilities(self, camera_id: str, capabilities: "CameraCapabilities", *,
                                    hw_model: Optional[str] = None, backend: Optional[str] = None,
                                    sensor_info: Optional[Dict[str, Any]] = None,
                                    display_name: Optional[str] = None) -> None:
        """Update capabilities, enabling control widgets."""
        old_caps = self._capabilities.get(camera_id)
        controls_changed = (old_caps.controls if old_caps else None) != (capabilities.controls if capabilities else None)
        self._capabilities[camera_id] = capabilities
        if capabilities:
            self._validators[camera_id] = CapabilityValidator(capabilities)
        backend_display = {"usb": "USB", "picam": "Pi Camera"}.get((backend or "").lower(), backend or "Unknown")
        mode_count = len({m.size for m in capabilities.modes if hasattr(m, "size")}) if capabilities and capabilities.modes else 0
        self._camera_info[camera_id] = {
            "model": display_name or hw_model or "Unknown",
            "backend": backend_display,
            "mode_count": str(mode_count),
            "sensor_info": sensor_info,
        }
        if camera_id == self._active_camera:
            if controls_changed:
                self._rebuild_controls_section()
            self._refresh_info_section()

    def remove_camera(self, camera_id: str) -> None:
        if self._active_camera == camera_id:
            self._active_camera = None
        self._refresh_ui()

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

        # Window background - darker for contrast with cards
        bg = Colors.BG_DARK if HAS_THEME and Colors else "#2b2b2b"

        main_frame = tk.Frame(self._window, bg=bg, padx=10, pady=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(0, weight=1)

        self._build_capture_card(main_frame, row=0)
        self._build_image_controls_card(main_frame, row=1)
        self._build_exposure_controls_card(main_frame, row=2)
        self._build_footer(main_frame, row=3)

    def _create_card(self, parent, row: int) -> tk.Frame:
        """Create a borderless card frame with subtle background differentiation."""
        bg = Colors.BG_FRAME if HAS_THEME and Colors else "#363636"
        card = tk.Frame(parent, bg=bg, padx=10, pady=8)
        card.grid(row=row, column=0, sticky="new", pady=(0, 8))
        card.columnconfigure(0, weight=1)
        return card

    def _build_capture_card(self, parent, row: int) -> None:
        """Build the capture settings card with resolution/FPS in horizontal layout."""
        card = self._create_card(parent, row)
        bg = Colors.BG_FRAME if HAS_THEME and Colors else "#363636"
        fg = Colors.FG_PRIMARY if HAS_THEME and Colors else "#ecf0f1"
        fg_secondary = Colors.FG_SECONDARY if HAS_THEME and Colors else "#95a5a6"

        # Configure grid columns: label | res combo | fps combo | "fps" label
        card.columnconfigure(1, weight=1)
        card.columnconfigure(2, weight=0)

        # Preview row
        tk.Label(card, text="Preview", bg=bg, fg=fg, anchor="w").grid(
            row=0, column=0, sticky="w", padx=(0, 10), pady=2
        )
        self._preview_res_var = tk.StringVar(value=DEFAULT_SETTINGS["preview_resolution"])
        self._preview_res_combo = ttk.Combobox(
            card, textvariable=self._preview_res_var, values=(), state="readonly", width=12
        )
        self._preview_res_combo.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=2)

        self._preview_fps_var = tk.StringVar(value=DEFAULT_SETTINGS["preview_fps"])
        self._preview_fps_combo = ttk.Combobox(
            card, textvariable=self._preview_fps_var, values=("1", "2", "5", "10", "15"),
            state="readonly", width=5
        )
        self._preview_fps_combo.grid(row=0, column=2, sticky="e", pady=2)
        tk.Label(card, text="fps", bg=bg, fg=fg_secondary, anchor="w").grid(
            row=0, column=3, sticky="w", padx=(4, 0), pady=2
        )

        # Record row
        tk.Label(card, text="Record", bg=bg, fg=fg, anchor="w").grid(
            row=1, column=0, sticky="w", padx=(0, 10), pady=2
        )
        self._record_res_var = tk.StringVar(value=DEFAULT_SETTINGS["record_resolution"])
        self._record_res_combo = ttk.Combobox(
            card, textvariable=self._record_res_var, values=(), state="readonly", width=12
        )
        self._record_res_combo.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=2)

        self._record_fps_var = tk.StringVar(value=DEFAULT_SETTINGS["record_fps"])
        self._record_fps_combo = ttk.Combobox(
            card, textvariable=self._record_fps_var, values=("15", "24", "30", "60"),
            state="readonly", width=5
        )
        self._record_fps_combo.grid(row=1, column=2, sticky="e", pady=2)
        tk.Label(card, text="fps", bg=bg, fg=fg_secondary, anchor="w").grid(
            row=1, column=3, sticky="w", padx=(4, 0), pady=2
        )

        # Audio recording checkbox (only visible when camera has built-in mic)
        self._record_audio_frame = tk.Frame(card, bg=bg)
        self._record_audio_frame.grid(row=2, column=0, columnspan=4, sticky="w", pady=(4, 0))
        self._record_audio_var = tk.BooleanVar(value=True)
        self._record_audio_cb = ttk.Checkbutton(
            self._record_audio_frame,
            text="Record audio (built-in mic)",
            variable=self._record_audio_var,
            command=self._on_audio_setting_changed,
        )
        self._record_audio_cb.pack(side=tk.LEFT)
        # Initially hidden until we know if camera has audio
        self._record_audio_frame.grid_remove()

        # Apply button row
        btn_frame = tk.Frame(card, bg=bg)
        btn_frame.grid(row=3, column=0, columnspan=4, sticky="e", pady=(6, 0))

        if HAS_THEME and RoundedButton is not None and Colors is not None:
            apply_btn = RoundedButton(
                btn_frame, text="Apply", command=self._apply_resolution,
                width=80, height=26, style="default", bg=bg
            )
            apply_btn.pack(side=tk.RIGHT)
        else:
            apply_btn = ttk.Button(btn_frame, text="Apply", command=self._apply_resolution)
            apply_btn.pack(side=tk.RIGHT)

    def _build_image_controls_card(self, parent, row: int) -> None:
        """Build the image adjustment controls card (Brightness, Contrast, etc.)."""
        card = self._create_card(parent, row)
        card.columnconfigure(1, weight=1)
        self._image_controls_card = card

        # Placeholder - will be populated when capabilities arrive
        bg = Colors.BG_FRAME if HAS_THEME and Colors else "#363636"
        fg = Colors.FG_SECONDARY if HAS_THEME and Colors else "#95a5a6"
        self._image_placeholder = tk.Label(card, text="No camera selected", bg=bg, fg=fg)
        self._image_placeholder.grid(row=0, column=0, columnspan=3, pady=6)

    def _build_exposure_controls_card(self, parent, row: int) -> None:
        """Build the exposure/focus controls card."""
        card = self._create_card(parent, row)
        card.columnconfigure(1, weight=1)
        self._exposure_controls_card = card

        # Placeholder - will be populated when capabilities arrive
        bg = Colors.BG_FRAME if HAS_THEME and Colors else "#363636"
        fg = Colors.FG_SECONDARY if HAS_THEME and Colors else "#95a5a6"
        self._exposure_placeholder = tk.Label(card, text="", bg=bg, fg=fg)
        self._exposure_placeholder.grid(row=0, column=0, columnspan=3, pady=6)

    def _build_footer(self, parent, row: int) -> None:
        """Build the footer with camera info and action buttons (no card background)."""
        bg = Colors.BG_DARK if HAS_THEME and Colors else "#2b2b2b"
        fg = Colors.FG_SECONDARY if HAS_THEME and Colors else "#95a5a6"

        footer = tk.Frame(parent, bg=bg)
        footer.grid(row=row, column=0, sticky="ew", pady=(4, 0))
        footer.columnconfigure(0, weight=1)

        # Camera info label (left side)
        self._info_label = tk.Label(footer, text="-", bg=bg, fg=fg, anchor="w")
        self._info_label.grid(row=0, column=0, sticky="w")

        # Buttons frame (right side)
        btn_frame = tk.Frame(footer, bg=bg)
        btn_frame.grid(row=0, column=1, sticky="e")

        if HAS_THEME and RoundedButton is not None and Colors is not None:
            self._info_btn = RoundedButton(
                btn_frame, text="Info", command=self._show_sensor_info,
                width=50, height=24, style="default", bg=bg
            )
            self._info_btn.pack(side=tk.LEFT, padx=(0, 6))

            reprobe_btn = RoundedButton(
                btn_frame, text="Reprobe", command=self._reprobe_camera,
                width=70, height=24, style="default", bg=bg
            )
            reprobe_btn.pack(side=tk.LEFT)
        else:
            self._info_btn = ttk.Button(btn_frame, text="Info", command=self._show_sensor_info, width=5)
            self._info_btn.pack(side=tk.LEFT, padx=(0, 6))

            reprobe_btn = ttk.Button(btn_frame, text="Reprobe", command=self._reprobe_camera, width=8)
            reprobe_btn.pack(side=tk.LEFT)

        # Initially disabled until we have sensor info
        self._info_btn_enabled = False
        self._set_info_btn_enabled(False)

    # ------------------------------------------------------------------
    # Controls section - dynamic rebuild
    # ------------------------------------------------------------------

    def _rebuild_controls_section(self) -> None:
        """Rebuild control widgets based on current camera's capabilities."""
        if not self._window:
            return

        self._control_widgets.clear()
        bg = Colors.BG_FRAME if HAS_THEME and Colors else "#363636"
        fg_muted = Colors.FG_SECONDARY if HAS_THEME and Colors else "#95a5a6"

        # Clear and rebuild image controls card
        if self._image_controls_card:
            for child in self._image_controls_card.winfo_children():
                child.destroy()

        # Clear and rebuild exposure controls card
        if self._exposure_controls_card:
            for child in self._exposure_controls_card.winfo_children():
                child.destroy()

        # Check if we have valid camera and controls
        if not self._active_camera:
            if self._image_controls_card:
                tk.Label(self._image_controls_card, text="No camera selected", bg=bg, fg=fg_muted).grid(
                    row=0, column=0, columnspan=3, pady=6
                )
            return

        caps = self._capabilities.get(self._active_camera)
        if not caps or not caps.controls:
            if self._image_controls_card:
                tk.Label(self._image_controls_card, text="No controls available", bg=bg, fg=fg_muted).grid(
                    row=0, column=0, columnspan=3, pady=6
                )
            return

        # Build image controls (Brightness, Contrast, Saturation, Hue)
        image_controls = []
        seen = set()
        for name in IMAGE_CONTROLS:
            if name in caps.controls and name not in seen:
                image_controls.append((name, caps.controls[name]))
                seen.add(name)

        if image_controls and self._image_controls_card:
            for row_idx, (name, ctrl) in enumerate(image_controls):
                self._build_control_widget(self._image_controls_card, row_idx, name, ctrl)
        elif self._image_controls_card:
            tk.Label(self._image_controls_card, text="No image controls", bg=bg, fg=fg_muted).grid(
                row=0, column=0, columnspan=3, pady=6
            )

        # Build exposure/focus controls
        exposure_controls = []
        for name in EXPOSURE_FOCUS_CONTROLS:
            if name in caps.controls and name not in seen:
                exposure_controls.append((name, caps.controls[name]))
                seen.add(name)

        if exposure_controls and self._exposure_controls_card:
            for row_idx, (name, ctrl) in enumerate(exposure_controls):
                self._build_control_widget(self._exposure_controls_card, row_idx, name, ctrl)
        elif self._exposure_controls_card:
            # Hide the card if no exposure/focus controls
            tk.Label(self._exposure_controls_card, text="", bg=bg, fg=fg_muted).grid(
                row=0, column=0, pady=0
            )

        # Apply initial dependent control states
        self._update_dependent_control_states()

    def _build_control_widget(self, parent, row: int, name: str, ctrl: "ControlInfo") -> None:
        """Build a single control widget based on control type."""
        from rpi_logger.modules.Cameras.camera_core.state import ControlType

        bg = Colors.BG_FRAME if HAS_THEME and Colors else "#363636"
        fg = Colors.FG_PRIMARY if HAS_THEME and Colors else "#ecf0f1"

        # Label
        display_name = self._format_control_name(name)
        tk.Label(parent, text=f"{display_name}:", bg=bg, fg=fg, anchor="w").grid(
            row=row, column=0, sticky="w", padx=(0, 8), pady=2
        )

        widget_info: Dict[str, Any] = {"control": ctrl, "name": name}

        if ctrl.control_type == ControlType.BOOLEAN:
            # Checkbutton
            var = tk.BooleanVar(value=bool(ctrl.current_value))
            cb = ttk.Checkbutton(parent, variable=var, command=lambda n=name: self._on_control_changed(n))
            cb.grid(row=row, column=1, sticky="w", pady=2)
            widget_info["var"] = var
            widget_info["widget"] = cb

        elif ctrl.control_type == ControlType.ENUM and ctrl.options:
            # Combobox for enum
            var = tk.StringVar(value=str(ctrl.current_value) if ctrl.current_value is not None else "")
            combo = ttk.Combobox(parent, textvariable=var, values=[str(o) for o in ctrl.options], state="readonly", width=14)
            combo.grid(row=row, column=1, sticky="ew", pady=2)
            combo.bind("<<ComboboxSelected>>", lambda e, n=name: self._on_control_changed(n))
            widget_info["var"] = var
            widget_info["widget"] = combo

        elif ctrl.min_value is not None and ctrl.max_value is not None:
            # Scale (slider) for numeric with range
            frame = tk.Frame(parent, bg=bg)
            frame.grid(row=row, column=1, sticky="ew", pady=2)
            frame.columnconfigure(0, weight=1)

            min_val = float(ctrl.min_value)
            max_val = float(ctrl.max_value)
            current = float(ctrl.current_value) if ctrl.current_value is not None else min_val

            var = tk.DoubleVar(value=current)

            # Determine resolution (step)
            resolution = ctrl.step if ctrl.step else 1.0
            if ctrl.control_type == ControlType.INTEGER:
                resolution = max(1, int(resolution))

            scale = ttk.Scale(frame, from_=min_val, to=max_val, variable=var, orient=tk.HORIZONTAL,
                              command=lambda v, n=name: self._on_scale_changed(n, v))
            scale.grid(row=0, column=0, sticky="ew")

            # Value label
            val_label = tk.Label(frame, text=self._format_value(current, ctrl), width=6, anchor="e", bg=bg, fg=fg)
            val_label.grid(row=0, column=1, padx=(4, 0))

            widget_info["var"] = var
            widget_info["widget"] = scale
            widget_info["value_label"] = val_label
            widget_info["resolution"] = resolution

        else:
            # Entry for unknown or unbounded
            var = tk.StringVar(value=str(ctrl.current_value) if ctrl.current_value is not None else "")
            entry = ttk.Entry(parent, textvariable=var, width=10)
            entry.grid(row=row, column=1, sticky="e", pady=2)
            entry.bind("<Return>", lambda e, n=name: self._on_control_changed(n))
            entry.bind("<FocusOut>", lambda e, n=name: self._on_control_changed(n))
            widget_info["var"] = var
            widget_info["widget"] = entry

        # Reset button (if default available)
        if ctrl.default_value is not None:
            reset_btn = ttk.Button(parent, text="R", width=2, command=lambda n=name: self._reset_control(n))
            reset_btn.grid(row=row, column=2, padx=(4, 0), pady=2)
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
        from rpi_logger.modules.Cameras.camera_core.state import ControlType

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
        from rpi_logger.modules.Cameras.camera_core.state import ControlType

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
        self._logger.debug("_apply_resolution called, active_camera=%s", self._active_camera)
        if not self._active_camera:
            self._logger.warning("No active camera set - cannot apply")
            return

        settings = self._get_resolution_settings()
        self._logger.debug("Settings to apply: %s", settings)
        self._latest[self._active_camera] = settings

        if self._on_apply_resolution:
            self._logger.debug("Calling _on_apply_resolution callback")
            try:
                self._on_apply_resolution(self._active_camera, settings)
            except Exception:
                self._logger.debug("Resolution apply callback failed", exc_info=True)
        else:
            self._logger.warning("No _on_apply_resolution callback registered")

    def _reprobe_camera(self) -> None:
        """Request reprobing of the active camera's capabilities."""
        if not self._active_camera:
            return
        if self._on_reprobe:
            try:
                self._on_reprobe(self._active_camera)
            except Exception:
                self._logger.debug("Reprobe callback failed", exc_info=True)

    def _on_audio_setting_changed(self) -> None:
        """Handle audio recording checkbox change."""
        if not self._active_camera or not self._record_audio_var:
            return
        value = self._record_audio_var.get()
        self._latest.setdefault(self._active_camera, dict(DEFAULT_SETTINGS))
        self._latest[self._active_camera]["record_audio"] = "true" if value else "false"
        self._logger.debug("Audio recording setting changed: %s", value)

        # Notify via resolution callback (settings changed)
        if self._on_apply_resolution:
            try:
                settings = self._get_resolution_settings()
                self._on_apply_resolution(self._active_camera, settings)
            except Exception:
                self._logger.debug("Audio setting apply callback failed", exc_info=True)

    def _update_audio_checkbox_visibility(self) -> None:
        """Show/hide audio checkbox based on whether camera has audio sibling."""
        if not self._record_audio_frame:
            return
        try:
            has_audio = self._has_audio_sibling.get(self._active_camera or "", False)
            if has_audio:
                self._record_audio_frame.grid()  # Show
            else:
                self._record_audio_frame.grid_remove()  # Hide
        except Exception:
            self._logger.debug("Unable to update audio checkbox visibility", exc_info=True)

    def _handle_close(self) -> None:
        # Cancel any pending debounce timer to prevent callback on destroyed window
        if self._debounce_id:
            try:
                self._window.after_cancel(self._debounce_id)
            except Exception:
                pass
            self._debounce_id = None
        self.hide()

    # ------------------------------------------------------------------
    # UI refresh helpers
    # ------------------------------------------------------------------

    def _refresh_ui(self) -> None:
        """Refresh all UI sections."""
        if not self._window:
            return
        self._refresh_resolution_ui()
        self._update_audio_checkbox_visibility()
        self._rebuild_controls_section()
        self._refresh_info_section()

    def _refresh_resolution_ui(self) -> None:
        """Refresh resolution/FPS comboboxes."""
        if not self._window or not self._preview_res_var:
            self._logger.debug("_refresh_resolution_ui: window=%s, var=%s - skipping",
                             self._window is not None, self._preview_res_var is not None)
            return

        self._suppress_change = True
        try:
            if self._active_camera:
                settings = self._latest.get(self._active_camera, dict(DEFAULT_SETTINGS))
                opts = self._options.get(self._active_camera, {})
                self._logger.debug("_refresh_resolution_ui: settings=%s, opts=%s", settings, opts)

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
                # Set audio recording checkbox
                if self._record_audio_var:
                    record_audio = settings.get("record_audio", "true").lower() == "true"
                    self._record_audio_var.set(record_audio)
            else:
                # Clear values
                self._preview_res_var.set("")
                self._preview_fps_var.set("5")
                self._record_res_var.set("")
                self._record_fps_var.set("15")
                if self._record_audio_var:
                    self._record_audio_var.set(True)
        finally:
            self._suppress_change = False

    def _refresh_info_section(self) -> None:
        """Refresh camera info in footer and info button state."""
        if not self._info_label:
            return

        if not self._active_camera:
            self._info_label.config(text="-")
            self._set_info_btn_enabled(False)
            return

        info = self._camera_info.get(self._active_camera, {})
        model = info.get("model", "Unknown")
        backend = info.get("backend", "")

        # Format as "Model (Backend)" or just "Model"
        if backend and backend != "Unknown":
            display_text = f"{model} ({backend})"
        else:
            display_text = model

        self._info_label.config(text=display_text)

        # Enable/disable info button based on whether we have sensor info
        has_sensor_info = bool(info.get("sensor_info"))
        self._set_info_btn_enabled(has_sensor_info)

    def _set_info_btn_enabled(self, enabled: bool) -> None:
        """Set the info button enabled/disabled state."""
        self._info_btn_enabled = enabled
        if not self._info_btn:
            return
        try:
            # RoundedButton has set_enabled method
            if hasattr(self._info_btn, 'set_enabled'):
                self._info_btn.set_enabled(enabled)
            else:
                # ttk.Button fallback
                self._info_btn.config(state="normal" if enabled else "disabled")
        except Exception:
            pass

    def _show_sensor_info(self) -> None:
        """Show detailed sensor/hardware information dialog."""
        if not self._active_camera or not self._window:
            return

        info = self._camera_info.get(self._active_camera, {})
        sensor_info = info.get("sensor_info")
        if not sensor_info:
            return

        camera_name = info.get("model", "Unknown Camera")

        if HAS_SENSOR_DIALOG and show_sensor_info:
            show_sensor_info(self._window, sensor_info, camera_name)
        else:
            self._logger.debug("Sensor info dialog not available")

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
            "record_audio": "true" if (self._record_audio_var and self._record_audio_var.get()) else "false",
        }

    def _clamp_settings_to_options(self, camera_id: str) -> None:
        """Ensure stored settings are within available options.

        Uses CapabilityValidator for proper validation if available,
        otherwise falls back to options-based clamping.
        """
        latest = self._latest.setdefault(camera_id, dict(DEFAULT_SETTINGS))

        # Use validator if available for proper capability-based validation
        validator = self._validators.get(camera_id)
        if validator:
            validated = validator.validate_settings(latest)
            latest.update(validated)
            return

        # Fallback: use available options for clamping
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
