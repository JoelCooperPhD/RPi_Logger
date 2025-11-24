"""View adapter that owns camera tabs and dispatches preview frames."""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional, Callable

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.Cameras.app.widgets.camera_tab import CameraTab


class ViewAdapter:
    """Maintains camera tabs and accepts preview frames."""

    def __init__(self, *, logger: LoggerLike = None) -> None:
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self.tabs: Dict[str, CameraTab] = {}
        self._notebook = None
        self._root = None
        self._ui_thread = threading.current_thread()
        self._tab_lookup: Dict[str, str] = {}

    def set_root(self, root) -> None:
        self._root = root
        self._ui_thread = threading.current_thread()

    def attach(self, notebook) -> None:
        """Bind to the Tk notebook used for camera tabs."""

        self._notebook = notebook

    def add_camera(
        self,
        camera_id: str,
        *,
        title: Optional[str] = None,
        refresh_cb: Optional[Callable[[], None]] = None,
        apply_config_cb: Optional[Callable[[str, Dict[str, str]], None]] = None,
    ) -> Optional[CameraTab]:
        if camera_id in self.tabs or not self._notebook:
            return None
        tab = CameraTab(
            camera_id,
            parent=self._notebook,
            root=self._root,
            logger=self._logger,
            on_refresh=refresh_cb,
            on_apply_config=apply_config_cb,
        )
        if tab.frame is None:
            self._logger.warning("Cannot build tab for %s (Tk unavailable)", camera_id)
            return None
        self.tabs[camera_id] = tab
        self._tab_lookup[str(tab.frame)] = camera_id
        label = title or camera_id
        try:
            self._notebook.add(tab.frame, text=label)
        except Exception:
            self._logger.warning("Unable to add tab for %s", camera_id, exc_info=True)
            self.tabs.pop(camera_id, None)
            self._tab_lookup.pop(str(tab.frame), None)
            return None
        self._logger.info("Added camera tab %s", camera_id)
        return tab

    def remove_camera(self, camera_id: str) -> None:
        tab = self.tabs.pop(camera_id, None)
        if not tab or not self._notebook or tab.frame is None:
            return
        try:
            self._notebook.forget(tab.frame)
        except Exception:
            self._logger.debug("Failed to remove tab frame for %s", camera_id, exc_info=True)
        self._tab_lookup.pop(str(tab.frame), None)
        tab.destroy()
        self._logger.info("Removed camera tab %s", camera_id)

    def push_frame(self, camera_id: str, frame: Any) -> None:
        tab = self.tabs.get(camera_id)
        if not tab:
            return
        self._dispatch(tab.update_frame, frame)

    def update_metrics(self, camera_id: str, metrics: Dict[str, Any]) -> None:
        tab = self.tabs.get(camera_id)
        if not tab:
            return
        self._dispatch(tab.update_metrics, metrics)

    def camera_id_for_tab(self, tab_id: Any) -> Optional[str]:
        if tab_id is None:
            return None
        return self._tab_lookup.get(str(tab_id))

    def first_camera_id(self) -> Optional[str]:
        return next(iter(self.tabs)) if self.tabs else None

    # ------------------------------------------------------------------

    def _dispatch(self, func, *args) -> None:
        if self._root is None or threading.current_thread() is self._ui_thread:
            func(*args)
            return
        try:
            self._root.after(0, lambda: func(*args))
        except Exception:
            self._logger.debug("Failed to dispatch to Tk thread", exc_info=True)
