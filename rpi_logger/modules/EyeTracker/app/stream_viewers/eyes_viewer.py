"""Eyes camera stream viewer with dual eye display."""

from __future__ import annotations

import io
import logging
from typing import TYPE_CHECKING, Optional

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


class EyesViewer(BaseStreamViewer):
    """Dual eye camera display showing left and right eye frames.

    The Neon eye tracker provides a combined 384x192 frame with left eye
    in the first 192 columns and right eye in the last 192 columns.
    This viewer splits and displays them either side by side or stacked vertically.
    Images stretch to fill available space.
    """

    EYE_CANVAS_SIZE = 192  # Native eye camera size

    def __init__(
        self,
        parent: "tk.Frame",
        logger: logging.Logger,
        *,
        row: int = 0,
        stacked: bool = False,
    ) -> None:
        """Initialize the eyes viewer.

        Args:
            parent: Parent tkinter frame
            logger: Logger instance
            row: Grid row position
            stacked: If True, stack eyes vertically (for side-by-side with video)
        """
        super().__init__(parent, "eyes", logger, row=row)
        self._stacked = stacked
        self._left_eye_canvas: Optional["tk.Canvas"] = None
        self._right_eye_canvas: Optional["tk.Canvas"] = None
        self._left_eye_photo_ref = None
        self._right_eye_photo_ref = None

    def build_ui(self) -> "ttk.Frame":
        """Build the dual eye camera display."""
        if ttk is None or tk is None:
            raise RuntimeError("Tkinter not available")

        self._frame = ttk.Frame(self._parent)

        canvas_bg = Colors.BG_CANVAS if HAS_THEME and Colors else "#1e1e1e"
        label_style = "Inframe.TLabel" if HAS_THEME else None

        if self._stacked:
            # Vertical layout: left eye on top, right eye below
            # No borders, no outlines
            self._left_eye_canvas = tk.Canvas(
                self._frame,
                bg=canvas_bg,
                highlightthickness=0,
                borderwidth=0,
            )
            self._left_eye_canvas.grid(row=0, column=0, sticky="nsew")

            # Left eye label
            left_label = ttk.Label(self._frame, text="L", width=2)
            if label_style:
                left_label.configure(style=label_style)
            left_label.grid(row=0, column=1, sticky="n", padx=(2, 0), pady=(2, 0))

            self._right_eye_canvas = tk.Canvas(
                self._frame,
                bg=canvas_bg,
                highlightthickness=0,
                borderwidth=0,
            )
            self._right_eye_canvas.grid(row=1, column=0, sticky="nsew")

            # Right eye label
            right_label = ttk.Label(self._frame, text="R", width=2)
            if label_style:
                right_label.configure(style=label_style)
            right_label.grid(row=1, column=1, sticky="n", padx=(2, 0), pady=(2, 0))

            # Configure rows to expand evenly, column 0 (canvases) gets weight
            self._frame.rowconfigure(0, weight=1, uniform="eyes_row")
            self._frame.rowconfigure(1, weight=1, uniform="eyes_row")
            self._frame.columnconfigure(0, weight=1)
        else:
            # Horizontal layout: left and right eyes side by side
            self._left_eye_canvas = tk.Canvas(
                self._frame,
                bg=canvas_bg,
                highlightthickness=0,
                borderwidth=0,
            )
            self._left_eye_canvas.grid(row=0, column=0, sticky="nsew", padx=(0, 2))

            self._right_eye_canvas = tk.Canvas(
                self._frame,
                bg=canvas_bg,
                highlightthickness=0,
                borderwidth=0,
            )
            self._right_eye_canvas.grid(row=0, column=1, sticky="nsew", padx=(2, 0))

            # Configure columns to expand evenly
            self._frame.columnconfigure(0, weight=1)
            self._frame.columnconfigure(1, weight=1)
            self._frame.rowconfigure(0, weight=1)

            # Labels
            left_label = ttk.Label(self._frame, text="Left Eye")
            if label_style:
                left_label.configure(style=label_style)
            left_label.grid(row=1, column=0, pady=(2, 0))

            right_label = ttk.Label(self._frame, text="Right Eye")
            if label_style:
                right_label.configure(style=label_style)
            right_label.grid(row=1, column=1, pady=(2, 0))

        return self._frame

    def update(self, eyes_frame: Optional["np.ndarray"]) -> None:
        """Update the eye camera display with a new combined frame.

        Args:
            eyes_frame: Combined 384x192 BGR numpy array with both eyes,
                       or None if no frame available
        """
        if not self._enabled:
            return

        if eyes_frame is None or Image is None:
            return

        try:
            # Eyes frame is 384x192 (left eye 0:192, right eye 192:384)
            h, w = eyes_frame.shape[:2]
            mid = w // 2

            # Split into left and right
            left_eye = eyes_frame[:, :mid]
            right_eye = eyes_frame[:, mid:]

            # Update left eye canvas
            self._update_eye_canvas(
                self._left_eye_canvas,
                left_eye,
                self._set_left_photo_ref,
            )

            # Update right eye canvas
            self._update_eye_canvas(
                self._right_eye_canvas,
                right_eye,
                self._set_right_photo_ref,
            )

        except Exception as exc:
            self._logger.debug("Eye preview update failed: %s", exc)

    def _update_eye_canvas(
        self,
        canvas: Optional["tk.Canvas"],
        eye_frame: "np.ndarray",
        set_photo_ref,
    ) -> None:
        """Update a single eye canvas with a frame.

        The frame is scaled to fill the available canvas space.

        Args:
            canvas: The canvas to update
            eye_frame: BGR numpy array for this eye
            set_photo_ref: Callback to store the photo reference
        """
        if canvas is None:
            return

        # Get current canvas size
        canvas_w = canvas.winfo_width()
        canvas_h = canvas.winfo_height()

        # Skip if canvas not yet realized
        if canvas_w <= 1 or canvas_h <= 1:
            return

        # Convert BGR to RGB
        rgb = eye_frame[:, :, ::-1]
        img = Image.fromarray(rgb)

        # Scale image to fill canvas
        img = img.resize((canvas_w, canvas_h), Image.Resampling.LANCZOS)

        # Convert to PPM for Tkinter
        ppm_data = io.BytesIO()
        img.save(ppm_data, format="PPM")
        photo = tk.PhotoImage(data=ppm_data.getvalue())

        # Update canvas
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=photo)

        # Keep reference
        set_photo_ref(photo)

    def _set_left_photo_ref(self, photo) -> None:
        """Store left eye photo reference."""
        self._left_eye_photo_ref = photo

    def _set_right_photo_ref(self, photo) -> None:
        """Store right eye photo reference."""
        self._right_eye_photo_ref = photo

    def cleanup(self) -> None:
        """Clean up eyes viewer resources."""
        self._left_eye_photo_ref = None
        self._right_eye_photo_ref = None


__all__ = ["EyesViewer"]
