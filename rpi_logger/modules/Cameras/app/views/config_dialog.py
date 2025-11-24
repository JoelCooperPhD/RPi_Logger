"""Configuration dialog for per-camera settings."""

from __future__ import annotations

from typing import Dict, Optional

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.Cameras.app.widgets.settings_panel import SettingsPanel

try:  # pragma: no cover - GUI availability varies
    import tkinter as tk  # type: ignore
    from tkinter import ttk  # type: ignore
except Exception:  # pragma: no cover
    tk = None  # type: ignore
    ttk = None  # type: ignore


class ConfigDialog:
    """Stores pending configs and presents a Tk pop-out dialog."""

    def __init__(self, *, root=None, logger: LoggerLike = None, on_apply=None) -> None:
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._root = root
        self._on_apply = on_apply
        self.pending: Dict[str, Dict[str, str]] = {}
        self._window = None
        self._settings_panel: Optional[SettingsPanel] = None
        self._target_camera: Optional[str] = None

    def open(self, camera_id: Optional[str] = None, *, defaults: Optional[Dict[str, str]] = None) -> None:
        if tk is None or ttk is None or self._root is None:
            self._logger.info("Config dialog unavailable (tk/root missing)")
            return
        target = camera_id or "default"
        self._target_camera = target
        self._ensure_window()
        if defaults and self._settings_panel:
            self._settings_panel.apply(defaults)
        try:
            self._window.deiconify()
            self._window.lift()
            self._window.focus_force()
        except Exception:
            self._logger.debug("Config dialog focus failed", exc_info=True)
        self._logger.info("Config dialog opened for %s", target)

    def apply(self, camera_id: str, settings: Dict[str, str]) -> None:
        self.pending[camera_id] = settings
        if self._on_apply:
            try:
                self._on_apply(camera_id, settings)
            except Exception:
                self._logger.debug("Config apply callback failed", exc_info=True)
        self._logger.info("Config applied for %s: %s", camera_id, settings)

    def close(self) -> None:
        if self._window is None:
            return
        try:
            self._window.withdraw()
        except Exception:
            self._logger.debug("Config dialog close failed", exc_info=True)
        self._logger.info("Config dialog closed")

    # ------------------------------------------------------------------

    def _ensure_window(self) -> None:
        if self._window and self._window.winfo_exists():
            return
        self._window = tk.Toplevel(self._root)
        self._window.title("Camera Configuration")
        self._window.geometry("360x320")
        self._window.columnconfigure(0, weight=1)
        self._window.rowconfigure(0, weight=1)
        self._window.protocol("WM_DELETE_WINDOW", self.close)

        self._settings_panel = SettingsPanel(self._window, logger=self._logger)
        self._settings_panel.frame.grid(row=0, column=0, sticky="nsew")

        button_row = ttk.Frame(self._window)
        button_row.grid(row=1, column=0, sticky="e", pady=(8, 0), padx=(0, 6))
        ttk.Button(button_row, text="Apply", command=self._apply_clicked).grid(row=0, column=0, padx=4)
        ttk.Button(button_row, text="Close", command=self.close).grid(row=0, column=1, padx=4)

    def _apply_clicked(self) -> None:
        if not self._settings_panel or not self._target_camera:
            return
        settings = self._settings_panel.get_settings()
        self.apply(self._target_camera, settings)
