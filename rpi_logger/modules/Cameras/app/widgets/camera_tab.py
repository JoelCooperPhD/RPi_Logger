"""Tk widget representing a camera tab with a preview canvas."""

from __future__ import annotations

from typing import Optional, Callable, Dict, Any

from PIL import Image
import io

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
        self._photo_ref: Optional[tk.PhotoImage] = None
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
            if not hasattr(self, '_no_canvas_warned'):
                self._logger.warning("[CAMERA_TAB] %s: update_frame called but no canvas!", self.camera_id)
                self._no_canvas_warned = True
            return

        # Track frame count
        if not hasattr(self, '_frame_count'):
            self._frame_count = 0
        self._frame_count += 1

        try:
            color_format = str(getattr(frame, "color_format", "") or "").lower()
            assume_rgb = color_format == "rgb" or bool(getattr(frame, "_is_rgb", False))
            rgb_frame = to_rgb(ensure_uint8(frame), assume_rgb=assume_rgb)
            if rgb_frame is None:
                if self._frame_count <= 3:
                    self._logger.warning("[CAMERA_TAB] %s: to_rgb returned None!", self.camera_id)
                return
            image = Image.fromarray(rgb_frame)
        except Exception:
            self._logger.debug("[CAMERA_TAB] %s: Unable to convert frame", self.camera_id, exc_info=True)
            return

        if not self._logged_first_frame:
            self._logger.info(
                "[CAMERA_TAB] %s: FIRST FRAME RECEIVED! shape=%s mode=%s canvas=%dx%d",
                self.camera_id,
                getattr(image, "size", None),
                image.mode,
                self._canvas.winfo_width(),
                self._canvas.winfo_height(),
            )
            self._logged_first_frame = True
        elif self._frame_count % 60 == 0:
            self._logger.debug("[CAMERA_TAB] %s: frame #%d rendered", self.camera_id, self._frame_count)

        canvas_w = self._canvas.winfo_width()
        canvas_h = self._canvas.winfo_height()

        if canvas_w > 1 and canvas_h > 1:
            target_w = canvas_w
            target_h = canvas_h
            try:
                image = image.resize((target_w, target_h), Image.Resampling.BILINEAR)
            except Exception:
                image = image.resize((target_w, target_h))
            center_x = target_w // 2
            center_y = target_h // 2
        else:
            # Canvas not yet laid out by Tk - use anchor=nw at (0,0) with native size
            # so image is visible even before layout completes
            target_w = image.width
            target_h = image.height
            center_x = 0
            center_y = 0

        # Use native Tk PhotoImage with PPM to avoid PIL ImageTk issues on Python 3.13
        ppm_data = io.BytesIO()
        image.save(ppm_data, format="PPM")
        self._photo_ref = tk.PhotoImage(data=ppm_data.getvalue())

        if self._image_id is None:
            # Use anchor=nw when canvas not laid out, anchor=center when it is
            anchor = "center" if canvas_w > 1 and canvas_h > 1 else "nw"
            self._image_id = self._canvas.create_image(center_x, center_y, image=self._photo_ref, anchor=anchor)
        else:
            self._canvas.itemconfig(self._image_id, image=self._photo_ref)
            self._canvas.coords(self._image_id, center_x, center_y)
            # Update anchor if canvas size changed
            if canvas_w > 1 and canvas_h > 1:
                self._canvas.itemconfig(self._image_id, anchor="center")

        # No info label; canvas fills the tab area

    def update_metrics(self, metrics: Dict[str, Any]) -> None:
        return

    def destroy(self) -> None:
        if self.frame is not None:
            try:
                self.frame.destroy()
            except Exception:
                self._logger.debug("Camera tab destroy failed for %s", self.camera_id, exc_info=True)
