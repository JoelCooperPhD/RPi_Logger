"""View adapter that owns the camera view and dispatches preview frames."""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional, Callable

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.Cameras.app.widgets.camera_tab import CameraView


class ViewAdapter:
    """Maintains a single camera view and accepts preview frames."""

    def __init__(self, *, logger: LoggerLike = None) -> None:
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._views: Dict[str, CameraView] = {}
        self._container = None
        self._root = None
        self._ui_thread = threading.current_thread()
        self._active_camera_id: Optional[str] = None
        self._frame_drop_logged: set[str] = set()
        self._frame_counts: Dict[str, int] = {}

    @property
    def tabs(self) -> Dict[str, CameraView]:
        """Backward compatibility alias for _views."""
        return self._views

    def set_root(self, root) -> None:
        self._root = root
        self._ui_thread = threading.current_thread()

    def attach(self, container) -> None:
        """Bind to the Tk container used for camera view."""
        self._container = container

    def add_camera(
        self,
        camera_id: str,
        *,
        title: Optional[str] = None,
        refresh_cb: Optional[Callable[[], None]] = None,
        apply_config_cb: Optional[Callable[[str, Dict[str, str]], None]] = None,
    ) -> Optional[CameraView]:
        self._logger.info("[ADAPTER] add_camera called: camera_id=%s title=%s", camera_id, title)

        if camera_id in self._views:
            self._logger.warning("[ADAPTER] Camera %s already has a view!", camera_id)
            return None
        if not self._container:
            self._logger.error("[ADAPTER] No container attached - cannot create view!")
            return None

        self._logger.debug("[ADAPTER] Creating CameraView for %s...", camera_id)
        view = CameraView(
            camera_id,
            parent=self._container,
            root=self._root,
            logger=self._logger,
            on_refresh=refresh_cb,
            on_apply_config=apply_config_cb,
        )
        if view.frame is None:
            self._logger.warning("[ADAPTER] Cannot build view for %s (Tk unavailable)", camera_id)
            return None

        self._views[camera_id] = view

        # Grid the view frame directly; only show if it's the active camera
        view.frame.grid(row=0, column=0, sticky="nsew")
        if self._active_camera_id is None:
            self._active_camera_id = camera_id
        else:
            # Hide non-active views
            view.frame.grid_remove()

        # Force Tk to compute layout
        if self._root:
            self._root.update_idletasks()

        self._logger.info("[ADAPTER] Camera view created: camera_id=%s (total views: %d)",
                         camera_id, len(self._views))
        return view

    def remove_camera(self, camera_id: str) -> None:
        view = self._views.pop(camera_id, None)
        if not view or view.frame is None:
            return
        view.destroy()
        self._logger.info("Removed camera view %s", camera_id)

        # Update active camera if needed
        if self._active_camera_id == camera_id:
            self._active_camera_id = next(iter(self._views), None)
            if self._active_camera_id:
                self._show_camera(self._active_camera_id)

    def set_active_camera(self, camera_id: Optional[str]) -> None:
        """Switch to displaying the specified camera."""
        if camera_id == self._active_camera_id:
            return
        if camera_id and camera_id not in self._views:
            self._logger.warning("[ADAPTER] Cannot activate unknown camera: %s", camera_id)
            return

        self._active_camera_id = camera_id
        self._show_camera(camera_id)

    def _show_camera(self, camera_id: Optional[str]) -> None:
        """Show only the specified camera's view."""
        for cid, view in self._views.items():
            if view.frame is None:
                continue
            if cid == camera_id:
                view.frame.grid()
            else:
                view.frame.grid_remove()

    def push_frame(self, camera_id: str, frame: Any) -> None:
        view = self._views.get(camera_id)
        if not view:
            if camera_id not in self._frame_drop_logged:
                self._logger.warning("[ADAPTER] push_frame: no view for %s - frame dropped", camera_id)
                self._frame_drop_logged.add(camera_id)
            return

        self._frame_counts[camera_id] = self._frame_counts.get(camera_id, 0) + 1
        count = self._frame_counts[camera_id]
        if count == 1:
            self._logger.info("[ADAPTER] push_frame: First frame for %s! shape=%s",
                            camera_id, frame.shape if hasattr(frame, 'shape') else 'unknown')
        elif count % 60 == 0:
            self._logger.debug("[ADAPTER] push_frame: %s frame #%d", camera_id, count)

        self._dispatch(view.update_frame, frame)

    def update_metrics(self, camera_id: str, metrics: Dict[str, Any]) -> None:
        view = self._views.get(camera_id)
        if not view:
            return
        self._dispatch(view.update_metrics, metrics)

    def camera_id_for_tab(self, tab_id: Any) -> Optional[str]:
        """Backward compatibility - returns active camera."""
        return self._active_camera_id

    def first_camera_id(self) -> Optional[str]:
        return next(iter(self._views)) if self._views else None

    # ------------------------------------------------------------------

    def _dispatch(self, func, *args) -> None:
        if self._root is None or threading.current_thread() is self._ui_thread:
            func(*args)
            return
        try:
            self._root.after(0, lambda: func(*args))
        except Exception:
            self._logger.debug("Failed to dispatch to Tk thread", exc_info=True)
