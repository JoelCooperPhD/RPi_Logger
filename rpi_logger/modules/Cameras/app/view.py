"""Tk-backed view for Cameras using the stub view's content hooks."""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, Optional

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.Cameras.app.views.adapter import ViewAdapter
from rpi_logger.modules.Cameras.app.widgets.settings_panel import DEFAULT_SETTINGS, SettingsWindow


class CamerasView:
    """Composes the Cameras Tk UI (tabs, metrics, settings)."""

    def __init__(self, stub_view: Any = None, *, logger: LoggerLike = None) -> None:
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._stub_view = stub_view
        self._root = getattr(stub_view, "root", None)
        self._ui_thread = threading.current_thread()
        self._adapter = ViewAdapter(logger=self._logger)
        self._placeholder_tab: Optional[Any] = None
        self._notebook: Any = None
        self._settings_menu: Any = None
        self._has_ui = False
        self._activate_handler: Optional[Callable[[Optional[str]], None]] = None
        self._active_camera_id: Optional[str] = None
        self._refresh_handler: Optional[Callable[[], None]] = None
        self._config_handler: Optional[Callable[[str, Dict[str, str]], None]] = None
        self._settings_window: Optional[SettingsWindow] = None
        self._settings_toggle_var: Optional[Any] = None
        self._latest_metrics: Dict[str, Dict[str, Any]] = {}
        self._camera_options: Dict[str, Dict[str, list[str]]] = {}
        self._io_stub_fields: Dict[str, Any] = {}
        self._io_stub_history: Dict[str, Dict[str, str]] = {}
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
        self._install_io_stub_line(tk, ttk)
        self._has_ui = True
        self._logger.info("Cameras view attached")

    # ------------------------------------------------------------------ Layout

    def _build_layout(self, parent, tk, ttk) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        notebook = ttk.Notebook(parent)
        notebook.grid(row=0, column=0, sticky="nsew")
        notebook.enable_traversal()
        self._notebook = notebook
        self._adapter.attach(notebook)

        placeholder = ttk.Frame(notebook, padding="16")
        ttk.Label(
            placeholder,
            text="Waiting for cameras...",
            anchor="center",
        ).grid(row=0, column=0, sticky="nsew")
        placeholder.columnconfigure(0, weight=1)
        placeholder.rowconfigure(0, weight=1)
        self._placeholder_tab = placeholder
        notebook.add(placeholder, text="No Cameras")
        notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # Pop-out windows and settings menu controls
        self._install_settings_window(tk)
        self._install_settings_menu(tk)

    def _install_io_stub_line(self, tk, ttk) -> None:
        if not self._stub_view:
            return
        builder = getattr(self._stub_view, "build_io_stub_content", None)
        if not callable(builder):
            return
        if not self._io_stub_fields:
            for key in ("cam", "in", "rec", "tgt", "prv", "q", "wait"):
                self._io_stub_fields[key] = tk.StringVar(master=self._root, value="-")
        if not self._io_stub_history:
            self._io_stub_history = {}

        def _builder(frame) -> None:
            container = ttk.Frame(frame)
            container.grid(row=0, column=0, sticky="ew")
            for idx in range(6):
                container.columnconfigure(idx, weight=1, uniform="iofields")

            fields = [
                ("cam", "Cam"),
                ("in", "In (avg)"),
                ("rec", "Rec (out)"),
                ("tgt", "Tgt (rec)"),
                ("prv", "Prv (out)"),
                ("q", "Q (p/r)"),
                ("wait", "Wait (ms)"),
            ]
            for col, (key, label_text) in enumerate(fields):
                name = ttk.Label(container, text=label_text, anchor="center")
                val = ttk.Label(container, textvariable=self._io_stub_fields[key], anchor="center")
                try:
                    val.configure(font=("TkFixedFont", 9))
                except Exception:
                    pass
                name.grid(row=0, column=col, sticky="ew", padx=2)
                val.grid(row=1, column=col, sticky="ew", padx=2)

        try:
            builder(_builder)
        except Exception:
            self._logger.debug("IO stub content build failed", exc_info=True)
        self._update_io_stub_line()

    def bind_handlers(
        self,
        *,
        refresh: Optional[Callable[[], None]] = None,
        apply_config: Optional[Callable[[str, Dict[str, str]], None]] = None,
        activate_camera: Optional[Callable[[Optional[str]], None]] = None,
    ) -> None:
        self._refresh_handler = refresh
        self._config_handler = apply_config
        self._activate_handler = activate_camera

    # ------------------------------------------------------------------ Public API

    def add_camera(self, camera_id: str, *, title: Optional[str] = None) -> None:
        if not self._has_ui:
            return
        self._remove_placeholder()
        tab = self._adapter.add_camera(
            camera_id,
            title=title,
            refresh_cb=self._handle_refresh_clicked,
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
        self._latest_metrics.pop(camera_id, None)
        self._io_stub_history.pop(camera_id, None)
        if self._settings_window:
            self._settings_window.remove_camera(camera_id)
        if self._active_camera_id == camera_id:
            self._active_camera_id = self._adapter.first_camera_id()
        if not self._adapter.tabs:
            self._restore_placeholder()
        if self._active_camera_id != previous_active:
            self._emit_active_camera_changed()
        self._sync_metrics_active_camera()
        self._sync_settings_active_camera()
        self.set_status(f"Camera {camera_id} removed")

    def push_frame(self, camera_id: str, frame: Any) -> None:
        self._adapter.push_frame(camera_id, frame)

    def update_metrics(self, camera_id: str, metrics: Dict[str, Any]) -> None:
        self._latest_metrics[camera_id] = metrics or {}
        if self._root is None or threading.current_thread() is self._ui_thread:
            self._apply_metrics_update(camera_id)
            return
        try:
            self._root.after(0, lambda: self._apply_metrics_update(camera_id))
        except Exception:
            self._logger.debug("Failed to dispatch metrics update", exc_info=True)

    def set_status(self, message: str) -> None:
        self._logger.info(message)

    def get_active_camera_id(self) -> Optional[str]:
        return self._active_camera_id

    def _emit_active_camera_changed(self) -> None:
        if not self._activate_handler:
            return
        try:
            self._activate_handler(self._active_camera_id)
        except Exception:
            self._logger.debug("Active camera handler failed", exc_info=True)

    # ------------------------------------------------------------------ Internal helpers

    def _remove_placeholder(self) -> None:
        if self._placeholder_tab and self._notebook:
            try:
                self._notebook.forget(self._placeholder_tab)
            except Exception:
                pass
            self._placeholder_tab = None

    def _restore_placeholder(self) -> None:
        if self._placeholder_tab or not self._notebook:
            return
        try:
            import tkinter as tk  # type: ignore  # noqa: F401
            from tkinter import ttk  # type: ignore  # noqa: F401
        except Exception:
            return
        placeholder = ttk.Frame(self._notebook, padding="16")
        ttk.Label(placeholder, text="Waiting for cameras...", anchor="center").grid(row=0, column=0, sticky="nsew")
        placeholder.columnconfigure(0, weight=1)
        placeholder.rowconfigure(0, weight=1)
        self._placeholder_tab = placeholder
        self._notebook.add(placeholder, text="No Cameras")
        previous_active = self._active_camera_id
        self._active_camera_id = None
        if previous_active is not None:
            self._emit_active_camera_changed()

    def _on_tab_changed(self, event) -> None:
        if not self._notebook:
            return
        tab_id = self._notebook.select()
        camera_id = self._adapter.camera_id_for_tab(tab_id)
        self._active_camera_id = camera_id
        self._sync_metrics_active_camera()
        self._sync_settings_active_camera()
        self._emit_active_camera_changed()

    def _apply_config_from_tab(self, camera_id: str, settings: Dict[str, str]) -> None:
        self._apply_config(camera_id, settings)

    def _handle_refresh_clicked(self) -> None:
        self.set_status("Refreshing camera list...")
        if self._refresh_handler:
            try:
                self._refresh_handler()
            except Exception:
                self._logger.debug("Refresh handler failed", exc_info=True)

    def _apply_metrics_update(self, camera_id: str) -> None:
        self._update_io_stub_line()

    def _sync_metrics_active_camera(self) -> None:
        self._update_io_stub_line()

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
        self._update_io_stub_line()

    def _update_io_stub_line(self) -> None:
        if not self._io_stub_fields:
            return

        cam_id = self._active_camera_id or "-"
        payload = self._latest_metrics.get(cam_id, {}) if self._active_camera_id else {}

        def _fmt_num(value) -> str:
            try:
                return f"{float(value):5.1f}"
            except Exception:
                return "--.--"

        def _fmt_int(value) -> str:
            try:
                return f"{int(value):4d}"
            except Exception:
                return "--"

        values = {
            "cam": cam_id,
            "in": _fmt_num(payload.get("ingress_fps_avg") if "ingress_fps_avg" in payload else payload.get("record_ingest_fps_avg")),
            "rec": _fmt_num(payload.get("record_fps_avg")),
            "tgt": _fmt_num(payload.get("target_record_fps")),
            "prv": _fmt_num(payload.get("preview_fps_avg")),
            "q": f"{_fmt_int(payload.get('preview_queue'))}/{_fmt_int(payload.get('record_queue'))}",
            "wait": _fmt_num(payload.get("ingress_wait_ms")),
        }
        history = self._io_stub_history.setdefault(cam_id, {})

        def _is_placeholder(text: str) -> bool:
            return text in {"--.--", "--", "-", "--/--", "-/-", "-/-", None}  # type: ignore[arg-type]

        for key, var in self._io_stub_fields.items():
            new_val = values.get(key, "--")
            if _is_placeholder(new_val) and history.get(key):
                new_val = history[key]
            else:
                history[key] = new_val
            try:
                var.set(new_val)
            except Exception:
                self._logger.debug("Failed to update IO stub field %s", key, exc_info=True)

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
        menu.add_separator()
        menu.add_command(label="Refresh Camera Tabs", command=self._handle_refresh_clicked)

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
            if self._active_camera_id == camera_id and self._settings_window._panel:
                try:
                    self._settings_window._panel.apply(settings)
                except Exception:
                    self._logger.debug("Settings panel apply failed for %s", camera_id, exc_info=True)

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
            self._settings_window._latest.setdefault(camera_id, dict(DEFAULT_SETTINGS))
            latest = self._settings_window._latest[camera_id]
            if preview_res:
                if latest.get("preview_resolution") not in preview_res:
                    latest["preview_resolution"] = preview_res[0]
            if record_res:
                if latest.get("record_resolution") not in record_res:
                    latest["record_resolution"] = record_res[0]
            if preview_fps_values:
                if latest.get("preview_fps") not in preview_fps_values:
                    latest["preview_fps"] = default_preview_fps if default_preview_fps in preview_fps_values else preview_fps_values[0]
            if record_fps_values:
                if latest.get("record_fps") not in record_fps_values:
                    latest["record_fps"] = record_fps_values[0]

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
            if self._active_camera_id == camera_id and self._settings_window._panel:
                try:
                    self._settings_window._panel.apply(self._settings_window._latest.get(camera_id, dict(DEFAULT_SETTINGS)))
                except Exception:
                    self._logger.debug("Failed to apply normalized settings for %s", camera_id, exc_info=True)
