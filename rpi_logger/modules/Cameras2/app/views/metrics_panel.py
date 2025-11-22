"""Metrics panel that renders the latest counters per camera."""

from __future__ import annotations

from typing import Dict, Any, Optional

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger

try:  # pragma: no cover - GUI availability varies
    import tkinter as tk  # type: ignore
    from tkinter import ttk  # type: ignore
except Exception:  # pragma: no cover - headless hosts
    tk = None  # type: ignore
    ttk = None  # type: ignore


class MetricsPanel:
    """Stores latest metrics for display."""

    def __init__(self, parent=None, *, logger: LoggerLike = None) -> None:
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self.latest: Dict[str, Dict[str, Any]] = {}
        self.frame: Optional[tk.Widget] = None
        self._text_var: Optional[tk.StringVar] = None
        self._active_camera_id: Optional[str] = None

        if parent is not None and tk is not None and ttk is not None:
            self.frame = ttk.LabelFrame(parent, text="Metrics", padding="8")
            self.frame.columnconfigure(0, weight=1)
            self.frame.rowconfigure(0, weight=1)
            self._text_var = tk.StringVar(value="No metrics yet")
            ttk.Label(
                self.frame,
                textvariable=self._text_var,
                justify="left",
                anchor="nw",
            ).grid(row=0, column=0, sticky="nsew")

    def update(self, camera_id: str, metrics: Dict[str, Any]) -> None:
        self.latest[camera_id] = metrics or {}
        if self._text_var:
            self._text_var.set(self._format_text())
        self._logger.debug("Metrics updated for %s: %s", camera_id, metrics)

    def set_active_camera(self, camera_id: Optional[str]) -> None:
        """Limit the rendered metrics to the selected camera, if provided."""

        self._active_camera_id = camera_id
        if self._text_var:
            self._text_var.set(self._format_text())

    # ------------------------------------------------------------------

    def _format_text(self) -> str:
        if not self.latest:
            return "No metrics yet"

        if self._active_camera_id:
            payload = self.latest.get(self._active_camera_id)
            lines: list[str] = [f"{self._active_camera_id}:"]
            if payload is None:
                lines.append("  (no data)")
            elif not payload:
                lines.append("  (no data)")
            else:
                for key, value in sorted(payload.items()):
                    lines.append(f"  {key}: {value}")
            return "\n".join(lines)

        lines: list[str] = []
        for camera_id, payload in self.latest.items():
            lines.append(f"{camera_id}:")
            if not payload:
                lines.append("  (no data)")
            else:
                for key, value in sorted(payload.items()):
                    lines.append(f"  {key}: {value}")
            lines.append("")
        return "\n".join(lines).strip()


class MetricsWindow:
    """Pop-out window that mirrors the latest metrics for the active camera."""

    def __init__(self, root=None, *, logger: LoggerLike = None) -> None:
        self._root = root
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._window: Optional[tk.Toplevel] = None
        self._panel: Optional[MetricsPanel] = None
        self._toggle_var: Optional[tk.BooleanVar] = None
        self._active_camera_id: Optional[str] = None
        self._latest: Dict[str, Dict[str, Any]] = {}

    def bind_toggle_var(self, var: tk.BooleanVar) -> None:
        self._toggle_var = var

    def set_active_camera(self, camera_id: Optional[str]) -> None:
        self._active_camera_id = camera_id
        if self._panel:
            self._panel.set_active_camera(camera_id)

    def update_metrics(self, camera_id: str, metrics: Dict[str, Any]) -> None:
        self._latest[camera_id] = metrics or {}
        if self._panel:
            self._panel.update(camera_id, metrics or {})
            self._panel.set_active_camera(self._active_camera_id)

    def remove_camera(self, camera_id: str) -> None:
        self._latest.pop(camera_id, None)
        if self._panel:
            self._panel.set_active_camera(self._active_camera_id)

    def show(self) -> None:
        if tk is None or self._root is None:
            return

        if self._window and self._window.winfo_exists():
            try:
                self._window.deiconify()
                self._window.lift()
            except Exception:
                self._logger.debug("Failed to reshow metrics window", exc_info=True)
        else:
            try:
                self._window = tk.Toplevel(self._root)
                self._window.title("Metrics")
                self._window.protocol("WM_DELETE_WINDOW", self._handle_close)
                self._panel = MetricsPanel(self._window, logger=self._logger)
                if self._panel.frame:
                    self._panel.frame.pack(fill="both", expand=True)
                for key, payload in self._latest.items():
                    self._panel.update(key, payload)
                self._panel.set_active_camera(self._active_camera_id)
            except Exception:
                self._logger.debug("Unable to construct metrics window", exc_info=True)
                self._window = None
                self._panel = None
                return

        if self._toggle_var:
            self._toggle_var.set(True)

    def hide(self) -> None:
        if self._window is None:
            if self._toggle_var:
                self._toggle_var.set(False)
            return
        try:
            self._window.withdraw()
        except Exception:
            try:
                self._window.destroy()
            except Exception:
                self._logger.debug("Unable to hide metrics window", exc_info=True)
            finally:
                self._window = None
                self._panel = None
        if self._toggle_var:
            self._toggle_var.set(False)

    def _handle_close(self) -> None:
        self.hide()
