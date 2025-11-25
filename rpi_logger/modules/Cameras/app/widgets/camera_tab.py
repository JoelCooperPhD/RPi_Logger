"""Tk widget representing a camera tab with a preview canvas."""

from __future__ import annotations

from typing import Optional, Callable, Dict, Any

from PIL import Image, ImageTk

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.Cameras.app.media.color_convert import to_rgb
from rpi_logger.modules.Cameras.app.media.frame_convert import ensure_uint8

try:  # pragma: no cover - GUI availability depends on host
    import tkinter as tk  # type: ignore
    from tkinter import ttk  # type: ignore
except Exception:  # pragma: no cover - headless hosts
    tk = None  # type: ignore
    ttk = None  # type: ignore


class CameraTab:
    """Tk-backed camera tab that renders preview frames."""

    def __init__(
        self,
        camera_id: str,
        parent,
        root=None,
        *,
        logger: LoggerLike = None,
        on_refresh: Optional[Callable[[], None]] = None,
        on_apply_config: Optional[Callable[[str, Dict[str, str]], None]] = None,
    ) -> None:
        self.camera_id = camera_id
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._root = root
        self.frame: Optional[tk.Widget] = None
        self._canvas: Optional[tk.Canvas] = None
        self._image_id: Optional[int] = None
        self._photo_ref: Optional[ImageTk.PhotoImage] = None
        self._on_refresh = on_refresh
        self._on_apply_config = on_apply_config
        self._logged_first_frame = False

        if tk is None or ttk is None:
            self._logger.warning("Tk unavailable; camera tab %s will be headless", camera_id)
            return

        self.frame = ttk.Frame(parent, padding="6")
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(0, weight=1)

        # Preview area
        self._canvas = tk.Canvas(self.frame, background="#0f1115", height=320, highlightthickness=0)
        self._canvas.grid(row=0, column=0, sticky="nsew")

    # ------------------------------------------------------------------

    def update_frame(self, frame) -> None:
        """Render the latest preview frame onto the canvas."""

        if self._canvas is None or tk is None:
            return

        try:
            color_format = str(getattr(frame, "color_format", "") or "").lower()
            assume_rgb = color_format == "rgb" or bool(getattr(frame, "_is_rgb", False))
            rgb_frame = to_rgb(ensure_uint8(frame), assume_rgb=assume_rgb)
            if rgb_frame is None:
                return
            image = Image.fromarray(rgb_frame)
        except Exception:
            self._logger.debug("Unable to convert frame for %s", self.camera_id, exc_info=True)
            return
        if not self._logged_first_frame:
            self._logger.info(
                "CameraTab %s received first frame shape=%s mode=%s canvas_size=%dx%d",
                self.camera_id,
                getattr(image, "size", None),
                image.mode,
                self._canvas.winfo_width(),
                self._canvas.winfo_height(),
            )
            self._logged_first_frame = True

        canvas_w = self._canvas.winfo_width()
        canvas_h = self._canvas.winfo_height()

        if canvas_w > 1 and canvas_h > 1:
            target_w = canvas_w
            target_h = canvas_h
            try:
                image = image.resize((target_w, target_h), Image.Resampling.LANCZOS)
            except Exception:
                image = image.resize((target_w, target_h))
        else:
            # Canvas not yet laid out by Tk, use native image size
            target_w = image.width
            target_h = image.height

        self._photo_ref = ImageTk.PhotoImage(image)
        center_x = target_w // 2
        center_y = target_h // 2

        if self._image_id is None:
            self._image_id = self._canvas.create_image(center_x, center_y, image=self._photo_ref)
        else:
            self._canvas.itemconfig(self._image_id, image=self._photo_ref)
            self._canvas.coords(self._image_id, center_x, center_y)

        # No info label; canvas fills the tab area

    def update_metrics(self, metrics: Dict[str, Any]) -> None:
        return

    def destroy(self) -> None:
        if self.frame is not None:
            try:
                self.frame.destroy()
            except Exception:
                self._logger.debug("Camera tab destroy failed for %s", self.camera_id, exc_info=True)
