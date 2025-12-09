"""Tk-backed view for Cameras using the stub view's content hooks."""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, Optional

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.Cameras.app.views.adapter import ViewAdapter
from rpi_logger.modules.Cameras.app.widgets.metrics_display import MetricsDisplay
from rpi_logger.modules.Cameras.app.widgets.settings_panel import DEFAULT_SETTINGS, SettingsWindow

try:
    from rpi_logger.core.ui.theme.styles import Theme
    from rpi_logger.core.ui.theme.widgets import RoundedButton
    from rpi_logger.core.ui.theme.colors import Colors
    HAS_THEME = True
except ImportError:
    HAS_THEME = False
    Theme = None
    RoundedButton = None
    Colors = None


class CamerasView:
    """Composes the Cameras Tk UI (camera view, metrics, settings)."""

    def __init__(self, stub_view: Any = None, *, logger: LoggerLike = None) -> None:
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._stub_view = stub_view
        self._root = getattr(stub_view, "root", None)
        self._ui_thread = threading.current_thread()
        self._adapter = ViewAdapter(logger=self._logger)
        self._placeholder_label: Optional[Any] = None
        self._view_container: Any = None
        self._settings_menu: Any = None
        self._has_ui = False
        self._activate_handler: Optional[Callable[[Optional[str]], None]] = None
        self._active_camera_id: Optional[str] = None
        self._config_handler: Optional[Callable[[str, Dict[str, str]], None]] = None
        self._settings_window: Optional[SettingsWindow] = None
        self._settings_toggle_var: Optional[Any] = None
        self._metrics_display: Optional[MetricsDisplay] = None
        self._camera_options: Dict[str, Dict[str, list[str]]] = {}
        self._camera_settings: Dict[str, Dict[str, str]] = {}

    # ------------------------------------------------------------------ GUI wiring

    def attach(self) -> None:
        """Mount the Cameras UI inside the stub view frame, if available."""

        if not self._stub_view:
            self._logger.info("Cameras view running headless (stub view missing)")
            return

        try:
            import tkinter as tk  # type: ignore
            from tkinter import ttk  # type: ignore
        except Exception as exc:
            self._logger.warning("Tk unavailable for Cameras view: %s", exc)
            return
        self._ui_thread = threading.current_thread()

        def builder(parent) -> None:
            self._build_layout(parent, tk, ttk)

        self._adapter.set_root(self._root)
        self._stub_view.build_stub_content(builder)
        self._metrics_display = MetricsDisplay(self._root, logger=self._logger)
        self._metrics_display.install(self._stub_view, tk, ttk)
        self._has_ui = True
        self._logger.info("Cameras view attached")

    # ------------------------------------------------------------------ Layout

    def _build_layout(self, parent, tk, ttk) -> None:
        # Apply theme to root window if available
        if HAS_THEME and Theme is not None:
            try:
                root = parent.winfo_toplevel()
                Theme.apply(root)
            except Exception:
                pass

        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        # Simple container frame for the camera view (no notebook/tabs)
        if HAS_THEME and Colors is not None:
            container = tk.Frame(parent, bg=Colors.BG_FRAME)
        else:
            container = ttk.Frame(parent)
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)
        self._view_container = container
        self._adapter.attach(container)

        # Placeholder label shown when no cameras are connected
        if HAS_THEME and Colors is not None:
            lbl = tk.Label(
                container,
                text="Waiting for cameras...",
                anchor="center",
                bg=Colors.BG_FRAME,
                fg=Colors.FG_PRIMARY,
            )
        else:
            lbl = ttk.Label(
                container,
                text="Waiting for cameras...",
                anchor="center",
            )
        lbl.grid(row=0, column=0, sticky="nsew")
        self._placeholder_label = lbl

        # Pop-out windows and settings menu controls
        self._install_settings_window(tk)
        self._install_settings_menu(tk)

    def bind_handlers(
        self,
        *,
        apply_config: Optional[Callable[[str, Dict[str, str]], None]] = None,
        activate_camera: Optional[Callable[[Optional[str]], None]] = None,
    ) -> None:
        self._config_handler = apply_config
        self._activate_handler = activate_camera

    # ------------------------------------------------------------------ Public API

    def add_camera(self, camera_id: str, *, title: Optional[str] = None) -> None:
        if not self._has_ui:
            return
        self._remove_placeholder()
        self._adapter.add_camera(
            camera_id,
            title=title,
            apply_config_cb=self._apply_config_from_tab,
        )
        previous_active = self._active_camera_id
        if self._settings_window:
            self._settings_window.update_camera_defaults(camera_id)
            if camera_id in self._camera_settings:
                self._settings_window.set_camera_settings(camera_id, self._camera_settings[camera_id])
            opts = self._camera_options.get(camera_id)
            if opts:
                self._settings_window.update_camera_options(
                    camera_id,
                    preview_resolutions=opts.get("preview_resolutions"),
                    record_resolutions=opts.get("record_resolutions"),
                    preview_fps_values=opts.get("preview_fps_values"),
                    record_fps_values=opts.get("record_fps_values"),
                )
        if not self._active_camera_id:
            self._active_camera_id = camera_id
        if self._active_camera_id != previous_active:
            self._emit_active_camera_changed()
        self._sync_metrics_active_camera()
        self._sync_settings_active_camera()
        self.set_status(f"Camera {camera_id} added")

    def remove_camera(self, camera_id: str) -> None:
        if not self._has_ui:
            return
        previous_active = self._active_camera_id
        self._adapter.remove_camera(camera_id)
        if self._metrics_display:
            self._metrics_display.clear_camera(camera_id)
        if self._settings_window:
            self._settings_window.remove_camera(camera_id)
        if self._active_camera_id == camera_id:
            self._active_camera_id = self._adapter.first_camera_id()
        if not self._adapter.views:
            self._restore_placeholder()
        if self._active_camera_id != previous_active:
            self._emit_active_camera_changed()
        self._sync_metrics_active_camera()
        self._sync_settings_active_camera()
        self.set_status(f"Camera {camera_id} removed")

    def push_frame(self, camera_id: str, frame: Any) -> None:
        self._adapter.push_frame(camera_id, frame)

    def update_metrics(self, camera_id: str, metrics: Dict[str, Any]) -> None:
        if not self._metrics_display:
            return
        if self._root is None or threading.current_thread() is self._ui_thread:
            self._metrics_display.update_metrics(camera_id, metrics)
            return
        try:
            self._root.after(0, lambda: self._metrics_display.update_metrics(camera_id, metrics))
        except Exception:
            self._logger.debug("Failed to dispatch metrics update", exc_info=True)

    def set_status(self, message: str) -> None:
        self._logger.info(message)

    def get_active_camera_id(self) -> Optional[str]:
        return self._active_camera_id

    def set_active_camera(self, camera_id: Optional[str]) -> None:
        """Switch to displaying the specified camera."""
        if camera_id == self._active_camera_id:
            return
        previous_active = self._active_camera_id
        self._active_camera_id = camera_id
        self._adapter.set_active_camera(camera_id)
        if self._active_camera_id != previous_active:
            self._emit_active_camera_changed()
        self._sync_metrics_active_camera()
        self._sync_settings_active_camera()

    def _emit_active_camera_changed(self) -> None:
        if not self._activate_handler:
            return
        try:
            self._activate_handler(self._active_camera_id)
        except Exception:
            self._logger.debug("Active camera handler failed", exc_info=True)

    # ------------------------------------------------------------------ Internal helpers

    def _remove_placeholder(self) -> None:
        if self._placeholder_label:
            try:
                self._placeholder_label.grid_remove()
            except Exception:
                pass

    def _restore_placeholder(self) -> None:
        if not self._placeholder_label:
            return
        try:
            self._placeholder_label.grid()
        except Exception:
            pass
        previous_active = self._active_camera_id
        self._active_camera_id = None
        if previous_active is not None:
            self._emit_active_camera_changed()

    def _apply_config_from_tab(self, camera_id: str, settings: Dict[str, str]) -> None:
        self._apply_config(camera_id, settings)

    def _sync_metrics_active_camera(self) -> None:
        if self._metrics_display:
            self._metrics_display.set_active_camera(self._active_camera_id)

    def _install_settings_window(self, tk) -> None:
        if self._settings_toggle_var is None:
            self._settings_toggle_var = tk.BooleanVar(master=self._root, value=False)
        if self._settings_window is None:
            self._settings_window = SettingsWindow(self._root, logger=self._logger, on_apply=self._apply_config)
            self._settings_window.bind_toggle_var(self._settings_toggle_var)

    def _toggle_settings_window(self) -> None:
        if not self._settings_window or not self._settings_toggle_var:
            return
        visible = bool(self._settings_toggle_var.get())
        if visible:
            if self._active_camera_id and self._active_camera_id in self._camera_settings:
                self._settings_window.set_camera_settings(self._active_camera_id, self._camera_settings[self._active_camera_id])
            self._settings_window.set_active_camera(self._active_camera_id)
            self._settings_window.show()
            self._sync_settings_active_camera()
        else:
            self._settings_window.hide()

    def _sync_settings_active_camera(self) -> None:
        if self._settings_window:
            # Apply stored settings for the active camera before switching
            if self._active_camera_id and self._active_camera_id in self._camera_settings:
                self._settings_window.set_camera_settings(
                    self._active_camera_id, self._camera_settings[self._active_camera_id]
                )
            self._settings_window.set_active_camera(self._active_camera_id)
            if self._active_camera_id:
                opts = self._camera_options.get(self._active_camera_id)
                if opts:
                    self._settings_window.update_camera_options(
                        self._active_camera_id,
                        preview_resolutions=opts.get("preview_resolutions"),
                        record_resolutions=opts.get("record_resolutions"),
                        preview_fps_values=opts.get("preview_fps_values"),
                        record_fps_values=opts.get("record_fps_values"),
                    )

    def _install_settings_menu(self, tk) -> None:
        if self._settings_menu:
            return

        menu = None
        add_menu = getattr(self._stub_view, "add_menu", None)
        menubar = getattr(self._stub_view, "menubar", None)

        if callable(add_menu):
            try:
                menu = add_menu("Controls")
            except Exception:
                menu = None
        if menu is None and menubar is not None:
            try:
                menu = tk.Menu(menubar, tearoff=0)
                menubar.add_cascade(label="Controls", menu=menu)
            except Exception:
                menu = None

        if menu is None:
            self._logger.debug("Settings menu unavailable; skipping menu wiring")
            return

        self._settings_menu = menu

        if self._settings_toggle_var is not None:
            menu.add_checkbutton(
                label="Show Settings Window",
                variable=self._settings_toggle_var,
                command=self._toggle_settings_window,
            )

    def _apply_config(self, camera_id: Optional[str], settings: Dict[str, str]) -> None:
        if not camera_id:
            self.set_status("Select a camera before applying settings")
            return
        if self._config_handler:
            try:
                self._config_handler(camera_id, settings)
                self.set_status(f"Config applied for {camera_id}")
            except Exception:
                self._logger.debug("Config handler failed", exc_info=True)

    def update_camera_settings(self, camera_id: str, settings: Dict[str, str]) -> None:
        """Persist last-used settings for a camera and refresh UI defaults."""

        self._camera_settings[camera_id] = dict(settings)
        if self._settings_window:
            self._settings_window.set_camera_settings(camera_id, settings)
            if self._active_camera_id == camera_id and self._settings_window.has_panel():
                self._settings_window.apply_to_panel(settings)

    def update_camera_capabilities(self, camera_id: str, capabilities: Any) -> None:
        """Store per-camera options derived from capabilities and refresh settings UI."""

        modes = getattr(capabilities, "modes", None) or []

        def _fps_list() -> list[str]:
            fps_vals = {
                int(m.fps) if float(m.fps).is_integer() else round(float(m.fps), 2)
                for m in modes
                if hasattr(m, "fps")
            }
            fps_vals.update({1, 5, 10, 15})  # standard preview clamps
            return [str(v) for v in sorted(fps_vals, reverse=True)]

        sizes = []
        for m in modes:
            if hasattr(m, "width") and hasattr(m, "height"):
                sizes.append((m.width, m.height))

        unique_sizes = []
        seen = set()
        for size in sorted(sizes, key=lambda s: (s[0] * s[1], s[0], s[1]), reverse=True):
            if size in seen:
                continue
            seen.add(size)
            unique_sizes.append(size)

        # Record uses all available sizes (largest first)
        record_sizes = list(unique_sizes)

        # Preview uses only smaller resolutions suitable for UI display (max 640x480)
        # Sorted smallest first since preview should default to small
        MAX_PREVIEW_WIDTH, MAX_PREVIEW_HEIGHT = 640, 480
        preview_sizes = [
            s for s in unique_sizes
            if s[0] <= MAX_PREVIEW_WIDTH and s[1] <= MAX_PREVIEW_HEIGHT
        ]
        # Sort preview sizes smallest first (better default)
        preview_sizes = sorted(preview_sizes, key=lambda s: (s[0] * s[1], s[0], s[1]))
        # If no small sizes available, offer a few standard preview sizes
        if not preview_sizes:
            preview_sizes = [(320, 180), (320, 240), (640, 480)]

        preview_res = [f"{w}x{h}" for w, h in preview_sizes]
        record_res = [f"{w}x{h}" for w, h in record_sizes]
        preview_fps_values = ["1", "2", "5", "10", "15"]
        default_preview_fps = DEFAULT_SETTINGS.get("preview_fps", "5")
        record_fps_values = _fps_list()
        self._camera_options[camera_id] = {
            "preview_resolutions": preview_res,
            "record_resolutions": record_res,
            "preview_fps_values": preview_fps_values,
            "record_fps_values": record_fps_values,
        }

        # Align stored defaults with the available options to avoid stale hardcoded values.
        if self._settings_window:
            latest = self._settings_window.get_latest_settings(camera_id)
            updated = dict(latest)
            if preview_res:
                if updated.get("preview_resolution") not in preview_res:
                    updated["preview_resolution"] = preview_res[0]
            if record_res:
                if updated.get("record_resolution") not in record_res:
                    updated["record_resolution"] = record_res[0]
            if preview_fps_values:
                if updated.get("preview_fps") not in preview_fps_values:
                    updated["preview_fps"] = default_preview_fps if default_preview_fps in preview_fps_values else preview_fps_values[0]
            if record_fps_values:
                if updated.get("record_fps") not in record_fps_values:
                    updated["record_fps"] = record_fps_values[0]
            self._settings_window.set_latest_settings(camera_id, updated)

        self._logger.info(
            "Updated settings options for %s (resolutions=%s fps=%s/%s)",
            camera_id,
            preview_res,
            preview_fps_values,
            record_fps_values,
        )
        if self._settings_window:
            self._settings_window.update_camera_options(
                camera_id,
                preview_resolutions=preview_res,
                record_resolutions=record_res,
                preview_fps_values=preview_fps_values,
                record_fps_values=record_fps_values,
            )
            if self._active_camera_id == camera_id and self._settings_window.has_panel():
                self._settings_window.apply_to_panel(
                    self._settings_window.get_latest_settings(camera_id)
                )
