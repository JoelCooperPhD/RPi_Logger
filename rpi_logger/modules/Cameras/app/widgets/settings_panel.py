"""Settings panel for preview/record configuration."""

from __future__ import annotations

from typing import Dict, Optional, Callable

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
try:  # pragma: no cover - GUI availability varies
    import tkinter as tk  # type: ignore
    from tkinter import ttk  # type: ignore
except Exception:  # pragma: no cover
    tk = None  # type: ignore
    ttk = None  # type: ignore

DEFAULT_SETTINGS = {
    "preview_resolution": "",
    "preview_fps": "5",
    "record_resolution": "",
    "record_fps": "15",
    "overlay": "true",
}


class SettingsPanel:
    """Stores selected settings and renders a small form."""

    def __init__(self, parent=None, *, logger: LoggerLike = None, on_change: Optional[Callable[[], None]] = None) -> None:
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self.selected: Dict[str, str] = {}
        self.frame: Optional[tk.Widget] = None
        self._preview_res_var: Optional[tk.StringVar] = None
        self._preview_fps_var: Optional[tk.StringVar] = None
        self._record_res_var: Optional[tk.StringVar] = None
        self._record_fps_var: Optional[tk.StringVar] = None
        self._preview_res_combo = None
        self._preview_fps_combo = None
        self._record_res_combo = None
        self._record_fps_combo = None
        self._on_change = on_change
        self._suppress_change = False

        if parent is not None and tk is not None and ttk is not None:
            self._build_ui(parent)

    # ------------------------------------------------------------------

    def get_settings(self) -> Dict[str, str]:
        if self._preview_res_var is None:
            return dict(self.selected)
        return {
            "preview_resolution": (self._preview_res_var.get() or "").strip(),
            "preview_fps": (self._preview_fps_var.get() or "").strip(),
            "record_resolution": (self._record_res_var.get() or "").strip(),
            "record_fps": (self._record_fps_var.get() or "").strip(),
            "overlay": "true",
        }

    def apply(self, settings: Dict[str, str]) -> None:
        """Update selected values and sync the UI controls."""

        self._suppress_change = True
        self.selected.update(settings)
        if self._preview_res_var and "preview_resolution" in settings:
            self._preview_res_var.set(str(settings["preview_resolution"]))
        if self._preview_fps_var and "preview_fps" in settings:
            self._preview_fps_var.set(str(settings["preview_fps"]))
        if self._record_res_var and "record_resolution" in settings:
            self._record_res_var.set(str(settings["record_resolution"]))
        if self._record_fps_var and "record_fps" in settings:
            self._record_fps_var.set(str(settings["record_fps"]))
        self._suppress_change = False
        self._logger.debug("Settings applied: %s", settings)

    def update_options(
        self,
        *,
        preview_resolutions: Optional[list[str]] = None,
        record_resolutions: Optional[list[str]] = None,
        preview_fps_values: Optional[list[str]] = None,
        record_fps_values: Optional[list[str]] = None,
    ) -> None:
        """Refresh combobox option lists based on camera capabilities."""

        def _set_combo(combo, values, var):
            if combo is None or values is None or not values:
                return
            combo["values"] = values
            if var and var.get() not in values:
                var.set(values[0])

        self._suppress_change = True
        try:
            _set_combo(self._preview_res_combo, preview_resolutions, self._preview_res_var)
            _set_combo(self._record_res_combo, record_resolutions, self._record_res_var)
            _set_combo(self._preview_fps_combo, preview_fps_values, self._preview_fps_var)
            _set_combo(self._record_fps_combo, record_fps_values, self._record_fps_var)
            # If vars are still empty and options exist, pick the first option.
            if self._preview_res_var and not self._preview_res_var.get() and preview_resolutions:
                self._preview_res_var.set(preview_resolutions[0])
            if self._record_res_var and not self._record_res_var.get() and record_resolutions:
                self._record_res_var.set(record_resolutions[0])
            if self._preview_fps_var and not self._preview_fps_var.get() and preview_fps_values:
                self._preview_fps_var.set(preview_fps_values[0])
            if self._record_fps_var and not self._record_fps_var.get() and record_fps_values:
                self._record_fps_var.set(record_fps_values[0])
        finally:
            self._suppress_change = False

    # ------------------------------------------------------------------

    def _build_ui(self, parent) -> None:
        assert tk is not None and ttk is not None

        self.frame = ttk.LabelFrame(parent, text="Settings", padding="10")
        self.frame.columnconfigure(1, weight=1)

        self._preview_res_var = tk.StringVar(value=DEFAULT_SETTINGS["preview_resolution"])
        self._preview_res_var.trace_add("write", self._on_var_changed)
        ttk.Label(self.frame, text="Preview Resolution").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=(0, 4))
        self._preview_res_combo = ttk.Combobox(
            self.frame,
            textvariable=self._preview_res_var,
            values=(),
            state="readonly",
        )
        self._preview_res_combo.grid(row=0, column=1, sticky="ew", pady=(0, 4))

        self._preview_fps_var = tk.StringVar(value=DEFAULT_SETTINGS["preview_fps"])
        self._preview_fps_var.trace_add("write", self._on_var_changed)
        ttk.Label(self.frame, text="Preview FPS").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=(0, 4))
        self._preview_fps_combo = ttk.Combobox(
            self.frame,
            textvariable=self._preview_fps_var,
            values=("1", "2", "5", "10", "15"),
            state="readonly",
        )
        self._preview_fps_combo.grid(row=1, column=1, sticky="ew", pady=(0, 4))

        self._record_res_var = tk.StringVar(value=DEFAULT_SETTINGS["record_resolution"])
        self._record_res_var.trace_add("write", self._on_var_changed)
        ttk.Label(self.frame, text="Record Resolution").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=(0, 4))
        self._record_res_combo = ttk.Combobox(
            self.frame,
            textvariable=self._record_res_var,
            values=(),
            state="readonly",
        )
        self._record_res_combo.grid(row=2, column=1, sticky="ew", pady=(0, 4))

        self._record_fps_var = tk.StringVar(value=DEFAULT_SETTINGS["record_fps"])
        self._record_fps_var.trace_add("write", self._on_var_changed)
        ttk.Label(self.frame, text="Record FPS").grid(row=3, column=0, sticky="w", padx=(0, 6), pady=(0, 4))
        self._record_fps_combo = ttk.Combobox(
            self.frame,
            textvariable=self._record_fps_var,
            values=("15", "24", "30", "60"),
            state="readonly",
        )
        self._record_fps_combo.grid(row=3, column=1, sticky="ew", pady=(0, 4))

    def _on_var_changed(self, *_args) -> None:
        if self._suppress_change or not self._on_change:
            return
        try:
            self._on_change()
        except Exception:
            self._logger.debug("Settings change callback failed", exc_info=True)


class SettingsWindow:
    """Pop-out window that holds the resolution/FPS settings for the active camera."""

    def __init__(self, root=None, *, logger: LoggerLike = None, on_apply: Optional[Callable[[str, Dict[str, str]], None]] = None) -> None:
        self._root = root
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._on_apply = on_apply
        self._window: Optional[tk.Toplevel] = None
        self._panel: Optional[SettingsPanel] = None
        self._toggle_var: Optional[tk.BooleanVar] = None
        self._active_camera: Optional[str] = None
        self._latest: Dict[str, Dict[str, str]] = {}
        self._options: Dict[str, Dict[str, list[str]]] = {}

    def bind_toggle_var(self, var: tk.BooleanVar) -> None:
        self._toggle_var = var

    def set_active_camera(self, camera_id: Optional[str]) -> None:
        self._active_camera = camera_id
        if camera_id:
            self._latest.setdefault(camera_id, dict(DEFAULT_SETTINGS))
            self._options.setdefault(
                camera_id,
                {"preview_resolutions": [], "record_resolutions": [], "fps_values": []},
            )
        if self._panel and camera_id:
            self._panel.apply(self._latest.get(camera_id, dict(DEFAULT_SETTINGS)))
            self._apply_options()
        self._update_title()

    def update_camera_defaults(self, camera_id: str) -> None:
        self._latest.setdefault(camera_id, dict(DEFAULT_SETTINGS))
        if self._panel and self._active_camera == camera_id:
            self._panel.apply(self._latest[camera_id])

    def set_camera_settings(self, camera_id: str, settings: Dict[str, str]) -> None:
        merged = dict(DEFAULT_SETTINGS)
        merged.update(settings or {})
        self._latest[camera_id] = merged
        if self._active_camera == camera_id and self._panel:
            try:
                self._panel.apply(merged)
            except Exception:
                self._logger.debug("Settings panel apply failed for %s", camera_id, exc_info=True)

    def remove_camera(self, camera_id: str) -> None:
        # Keep cached settings/options so they can be restored if the camera returns.
        if self._active_camera == camera_id:
            self._active_camera = None
        if self._panel and self._active_camera is None:
            self._panel.apply(dict(DEFAULT_SETTINGS))

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
        if self._active_camera and self._panel:
            self._panel.apply(self._latest.get(self._active_camera, dict(DEFAULT_SETTINGS)))
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
                self._panel = None
        if self._toggle_var:
            self._toggle_var.set(False)

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
        self._window.title("Settings")
        self._window.protocol("WM_DELETE_WINDOW", self._handle_close)
        self._window.columnconfigure(0, weight=1)
        self._window.rowconfigure(0, weight=1)

        self._panel = SettingsPanel(self._window, logger=self._logger, on_change=self._on_settings_changed)
        if self._panel.frame:
            self._panel.frame.grid(row=0, column=0, sticky="nsew")
        self._update_title()
        self._apply_options()

    def _on_settings_changed(self) -> None:
        if not self._panel or not self._active_camera:
            return
        settings = self._panel.get_settings()
        self._latest[self._active_camera] = settings
        if self._on_apply:
            try:
                self._on_apply(self._active_camera, settings)
            except Exception:
                self._logger.debug("Settings apply failed for %s", self._active_camera, exc_info=True)

    def _handle_close(self) -> None:
        self.hide()

    def _update_title(self) -> None:
        if not self._window:
            return
        camera_label = self._active_camera or "No camera selected"
        try:
            self._window.title(f"Settings - {camera_label}")
        except Exception:
            self._logger.debug("Unable to set settings window title", exc_info=True)

    def update_camera_options(
        self,
        camera_id: str,
        *,
        preview_resolutions: Optional[list[str]] = None,
        record_resolutions: Optional[list[str]] = None,
        preview_fps_values: Optional[list[str]] = None,
        record_fps_values: Optional[list[str]] = None,
    ) -> None:
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
            # Clamp stored values to the available options to avoid stale defaults.
            latest = self._latest.setdefault(camera_id, dict(DEFAULT_SETTINGS))
            opts = self._options.get(camera_id, {})
            if preview_resolutions and latest.get("preview_resolution") not in preview_resolutions:
                latest["preview_resolution"] = preview_resolutions[0]
            if record_resolutions and latest.get("record_resolution") not in record_resolutions:
                latest["record_resolution"] = record_resolutions[0]
            pv_fps = opts.get("preview_fps_values") or preview_fps_values
            rc_fps = opts.get("record_fps_values") or record_fps_values
            if pv_fps and latest.get("preview_fps") not in pv_fps:
                latest["preview_fps"] = pv_fps[0]
            if rc_fps and latest.get("record_fps") not in rc_fps:
                latest["record_fps"] = rc_fps[0]
            self._apply_options()
            if self._panel:
                try:
                    self._panel.apply(latest)
                except Exception:
                    self._logger.debug("Settings panel apply failed", exc_info=True)

    def _apply_options(self) -> None:
        if not self._panel or not self._active_camera:
            return
        opts = self._options.get(self._active_camera, {})
        self._panel.update_options(
            preview_resolutions=opts.get("preview_resolutions"),
            record_resolutions=opts.get("record_resolutions"),
            preview_fps_values=opts.get("preview_fps_values"),
            record_fps_values=opts.get("record_fps_values"),
        )
