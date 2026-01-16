"""Video stream viewer with optional gaze overlay."""

from __future__ import annotations

import io
import logging
from typing import TYPE_CHECKING, Any, Optional

try:
    import tkinter as tk
    from tkinter import ttk
except Exception:
    tk = None  # type: ignore
    ttk = None  # type: ignore

try:
    from PIL import Image
except Exception:
    Image = None  # type: ignore

try:
    from rpi_logger.core.ui.theme.colors import Colors

    HAS_THEME = True
except ImportError:
    HAS_THEME = False
    Colors = None  # type: ignore

from .base_viewer import BaseStreamViewer

if TYPE_CHECKING:
    import numpy as np

# Error logging flag (log-once pattern to avoid per-frame spam)
_logged_video_error = False


class VideoViewer(BaseStreamViewer):
    """Main video preview canvas with optional gaze overlay.

    Displays the scene camera video stream. When gaze overlay is enabled,
    the gaze indicator is composited onto the video frame before display.
    The video stretches to fill the available space.
    """

    def __init__(
        self,
        parent: "tk.Frame",
        logger: logging.Logger,
        *,
        width: int = 640,
        height: int = 480,
        row: int = 0,
    ) -> None:
        """Initialize the video viewer.

        Args:
            parent: Parent tkinter frame
            logger: Logger instance
            width: Initial canvas width in pixels
            height: Initial canvas height in pixels
            row: Grid row position
        """
        super().__init__(parent, "video", logger, row=row)
        self._canvas_width = width
        self._canvas_height = height
        self._canvas: Optional["tk.Canvas"] = None
        self._photo_ref = None
        self._gaze_overlay_enabled = True  # Gaze overlay on by default

    @property
    def gaze_overlay_enabled(self) -> bool:
        """Return whether gaze overlay is enabled."""
        return self._gaze_overlay_enabled

    def set_gaze_overlay_enabled(self, enabled: bool) -> None:
        """Enable or disable gaze overlay on video.

        Args:
            enabled: Whether to show gaze overlay
        """
        self._gaze_overlay_enabled = enabled
        self._logger.debug("Gaze overlay %s", "enabled" if enabled else "disabled")

    def build_ui(self) -> "ttk.Frame":
        """Build the video preview canvas."""
        if ttk is None or tk is None:
            raise RuntimeError("Tkinter not available")

        self._frame = ttk.Frame(self._parent)
        self._frame.columnconfigure(0, weight=1)
        self._frame.rowconfigure(0, weight=1)

        canvas_bg = Colors.BG_CANVAS if HAS_THEME and Colors else "#1e1e1e"

        self._canvas = tk.Canvas(
            self._frame,
            bg=canvas_bg,
            highlightthickness=0,
            borderwidth=0,
        )
        self._canvas.grid(row=0, column=0, sticky="nsew")

        return self._frame

    def update(self, frame: Optional["np.ndarray"], gaze_data: Any = None) -> None:
        """Update the video preview with a new frame.

        The frame is scaled to fill the available canvas space.

        Args:
            frame: BGR numpy array of the video frame, or None if no frame
            gaze_data: Optional gaze data for overlay (used by frame processor)
        """
        if not self._enabled or self._canvas is None:
            return

        if frame is None or Image is None:
            self._show_placeholder()
            return

        try:
            # Get current canvas size
            canvas_w = self._canvas.winfo_width()
            canvas_h = self._canvas.winfo_height()

            # Skip if canvas not yet realized
            if canvas_w <= 1 or canvas_h <= 1:
                return

            # Convert BGR to RGB
            rgb = frame[:, :, ::-1]
            image = Image.fromarray(rgb)

            # Scale image to fill canvas
            image = image.resize((canvas_w, canvas_h), Image.Resampling.LANCZOS)

            # Convert to PPM format for Tkinter PhotoImage
            ppm_data = io.BytesIO()
            image.save(ppm_data, format="PPM")
            photo = tk.PhotoImage(data=ppm_data.getvalue())

            # Update canvas
            self._canvas.delete("all")
            self._canvas.create_image(0, 0, anchor="nw", image=photo)

            # Keep reference to prevent garbage collection
            self._photo_ref = photo

        except Exception as exc:
            global _logged_video_error
            if not _logged_video_error:
                self._logger.debug("Video preview update failed: %s", exc)
                _logged_video_error = True

    def _show_placeholder(self) -> None:
        """Show placeholder text when no frame is available."""
        if self._canvas is None:
            return

        self._canvas.delete("all")
        canvas_w = self._canvas.winfo_width()
        canvas_h = self._canvas.winfo_height()
        text_color = Colors.FG_PRIMARY if HAS_THEME and Colors else "#ecf0f1"
        self._canvas.create_text(
            canvas_w // 2,
            canvas_h // 2,
            text="Waiting for frames...",
            fill=text_color,
        )

    def resize(self, width: int, height: int) -> None:
        """Resize the video canvas.

        Args:
            width: New width in pixels
            height: New height in pixels
        """
        self._canvas_width = width
        self._canvas_height = height
        if self._canvas:
            self._canvas.config(width=width, height=height)

    def cleanup(self) -> None:
        """Clean up video viewer resources."""
        self._photo_ref = None


__all__ = ["VideoViewer"]
