"""Audio stream viewer with level meter display."""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Any, Optional

try:
    import tkinter as tk
    from tkinter import ttk
except Exception:
    tk = None  # type: ignore
    ttk = None  # type: ignore

try:
    import numpy as np

    HAS_NUMPY = True
except ImportError:
    np = None  # type: ignore
    HAS_NUMPY = False

try:
    from rpi_logger.core.ui.theme.colors import Colors

    HAS_THEME = True
except ImportError:
    HAS_THEME = False
    Colors = None  # type: ignore

from .base_viewer import BaseStreamViewer

if TYPE_CHECKING:
    pass


# Audio level constants
DB_MIN = -60.0
DB_MAX = 0.0
DB_YELLOW = -12.0  # Yellow zone starts at -12 dB
DB_RED = -3.0  # Red zone starts at -3 dB


class MeterColors:
    """Audio meter colors."""

    # Background zones (dark variants)
    BG_GREEN = "#1a3a1a"
    BG_GREEN_BORDER = "#2a4a2a"
    BG_YELLOW = "#3a3a1a"
    BG_YELLOW_BORDER = "#4a4a2a"
    BG_RED = "#3a1a1a"
    BG_RED_BORDER = "#4a2a2a"

    # Signal level colors
    LEVEL_GREEN = "#2ecc71"
    LEVEL_YELLOW = "#f39c12"
    LEVEL_RED = "#e74c3c"
    PEAK_LINE = "#ecf0f1"


def _init_meter_colors() -> None:
    """Initialize meter colors from theme if available."""
    if Colors is not None:
        MeterColors.LEVEL_GREEN = Colors.SUCCESS
        MeterColors.LEVEL_YELLOW = Colors.WARNING
        MeterColors.LEVEL_RED = Colors.ERROR
        MeterColors.PEAK_LINE = Colors.FG_PRIMARY


_init_meter_colors()


class AudioViewer(BaseStreamViewer):
    """Audio level meter visualization.

    Displays a horizontal VU-style meter showing current audio level
    with green/yellow/red zones and peak indicator.
    """

    def __init__(
        self,
        parent: "tk.Frame",
        logger: logging.Logger,
        *,
        row: int = 0,
    ) -> None:
        """Initialize the audio viewer.

        Args:
            parent: Parent tkinter frame
            logger: Logger instance
            row: Grid row position
        """
        super().__init__(parent, "audio", logger, row=row)
        self._canvas: Optional["tk.Canvas"] = None
        self._db_var: Optional["tk.StringVar"] = None
        self._canvas_items: dict[str, int] = {}
        self._peak_db = DB_MIN
        self._peak_hold_frames = 0
        self._last_width = 0
        self._last_height = 0

    def build_ui(self) -> "ttk.Frame":
        """Build the audio level meter display."""
        if ttk is None or tk is None:
            raise RuntimeError("Tkinter not available")

        self._frame = ttk.LabelFrame(self._parent, text="Audio", padding=(8, 4))
        self._frame.columnconfigure(0, weight=1)

        canvas_bg = Colors.BG_CANVAS if HAS_THEME and Colors else "#1e1e1e"
        canvas_border = Colors.BORDER if HAS_THEME and Colors else "#404055"

        # Level meter canvas
        self._canvas = tk.Canvas(
            self._frame,
            width=300,
            height=24,
            bg=canvas_bg,
            highlightthickness=1,
            highlightbackground=canvas_border,
        )
        self._canvas.grid(row=0, column=0, sticky="ew")

        # dB label
        label_style = "Inframe.TLabel" if HAS_THEME else None
        self._db_var = tk.StringVar(value="-- dB")
        db_label = ttk.Label(
            self._frame,
            textvariable=self._db_var,
            font=("Consolas", 9),
        )
        if label_style:
            db_label.configure(style=label_style)
        db_label.grid(row=0, column=1, padx=(8, 0))

        return self._frame

    def update(self, audio_data: Any) -> None:
        """Update the audio meter with new audio data.

        Args:
            audio_data: Audio frame from Pupil Labs API with av_frame attribute,
                       or None if no data available
        """
        if not self._enabled or self._canvas is None:
            return

        if audio_data is None:
            return

        try:
            # Extract audio samples and calculate RMS
            rms_db = self._calculate_rms_db(audio_data)

            # Update peak with hold
            if rms_db > self._peak_db:
                self._peak_db = rms_db
                self._peak_hold_frames = 30  # Hold for ~30 frames (3 seconds at 10Hz)
            elif self._peak_hold_frames > 0:
                self._peak_hold_frames -= 1
            else:
                # Decay peak
                self._peak_db = max(DB_MIN, self._peak_db - 1.0)

            # Update display
            self._draw_meter(rms_db, self._peak_db)

            # Update dB label
            if self._db_var:
                if rms_db > DB_MIN:
                    self._db_var.set(f"{rms_db:.1f} dB")
                else:
                    self._db_var.set("-- dB")

        except Exception as exc:
            self._logger.debug("Audio update failed: %s", exc)

    def _calculate_rms_db(self, audio_data: Any) -> float:
        """Calculate RMS level in dB from audio data.

        Args:
            audio_data: Audio frame from Pupil Labs API

        Returns:
            RMS level in dB
        """
        if not HAS_NUMPY:
            return DB_MIN

        # Try to get audio samples from Pupil Labs AudioFrame
        av_frame = getattr(audio_data, "av_frame", None)
        if av_frame is None:
            return DB_MIN

        try:
            # Get audio data as numpy array
            # PyAV frames have a to_ndarray() method
            if hasattr(av_frame, "to_ndarray"):
                samples = av_frame.to_ndarray()
            else:
                return DB_MIN

            # Flatten if needed and convert to float
            samples = samples.flatten().astype(np.float64)

            if len(samples) == 0:
                return DB_MIN

            # Normalize based on dtype
            # Common audio formats: int16, int32, float32
            if samples.dtype in (np.int16,):
                samples = samples / 32768.0
            elif samples.dtype in (np.int32,):
                samples = samples / 2147483648.0

            # Calculate RMS
            rms = np.sqrt(np.mean(samples ** 2))

            if rms < 1e-10:
                return DB_MIN

            # Convert to dB
            rms_db = 20.0 * math.log10(rms)
            return max(DB_MIN, min(DB_MAX, rms_db))

        except Exception:
            return DB_MIN

    def _draw_meter(self, rms_db: float, peak_db: float) -> None:
        """Draw the level meter on canvas.

        Args:
            rms_db: Current RMS level in dB
            peak_db: Peak level in dB
        """
        if self._canvas is None:
            return

        width = self._canvas.winfo_width()
        height = self._canvas.winfo_height()
        if width < 10 or height < 10:
            return

        # Rebuild canvas items if size changed
        if width != self._last_width or height != self._last_height:
            self._rebuild_meter_items(width, height)
            self._last_width = width
            self._last_height = height

        # Calculate positions
        padding_x = 5
        padding_y = 3
        usable_width = max(10, width - (2 * padding_x))
        meter_height = max(2, height - (2 * padding_y))

        total_range = DB_MAX - DB_MIN
        green_width = ((DB_YELLOW - DB_MIN) / total_range) * usable_width
        yellow_width = ((DB_RED - DB_YELLOW) / total_range) * usable_width

        # Calculate RMS position
        rms_position = max(DB_MIN, min(rms_db, DB_MAX))
        rms_fraction = (rms_position - DB_MIN) / total_range
        rms_width = rms_fraction * usable_width

        # Update level bars
        x_offset = padding_x
        remaining = rms_width

        def set_coords(item_id: int, start_x: float, end_x: float) -> None:
            self._canvas.coords(item_id, start_x, padding_y, end_x, padding_y + meter_height)

        # Green zone
        if remaining > 0:
            green_fill = min(remaining, green_width)
            set_coords(self._canvas_items["level_green"], x_offset, x_offset + green_fill)
            remaining -= green_fill
            x_offset = padding_x + green_fill
        else:
            set_coords(self._canvas_items["level_green"], 0, 0)

        # Yellow zone
        if remaining > 0:
            x_offset = padding_x + green_width
            yellow_fill = min(remaining, yellow_width)
            set_coords(self._canvas_items["level_yellow"], x_offset, x_offset + yellow_fill)
            remaining -= yellow_fill
        else:
            set_coords(self._canvas_items["level_yellow"], 0, 0)

        # Red zone
        if remaining > 0:
            x_offset = padding_x + green_width + yellow_width
            set_coords(self._canvas_items["level_red"], x_offset, x_offset + remaining)
        else:
            set_coords(self._canvas_items["level_red"], 0, 0)

        # Peak indicator
        if peak_db > DB_MIN:
            peak_position = max(DB_MIN, min(peak_db, DB_MAX))
            peak_fraction = (peak_position - DB_MIN) / total_range
            peak_x = padding_x + (peak_fraction * usable_width)
            self._canvas.coords(
                self._canvas_items["peak_line"],
                peak_x, padding_y, peak_x, padding_y + meter_height,
            )
        else:
            self._canvas.coords(self._canvas_items["peak_line"], 0, 0, 0, 0)

    def _rebuild_meter_items(self, width: int, height: int) -> None:
        """Rebuild canvas items for new size.

        Args:
            width: Canvas width
            height: Canvas height
        """
        if self._canvas is None:
            return

        self._canvas.delete("all")
        self._canvas_items.clear()

        padding_x = 5
        padding_y = 3
        usable_width = max(10, width - (2 * padding_x))
        meter_height = max(2, height - (2 * padding_y))

        total_range = DB_MAX - DB_MIN
        green_width = ((DB_YELLOW - DB_MIN) / total_range) * usable_width
        yellow_width = ((DB_RED - DB_YELLOW) / total_range) * usable_width
        red_width = ((DB_MAX - DB_RED) / total_range) * usable_width

        # Background zones
        x_offset = padding_x
        self._canvas_items["bg_green"] = self._canvas.create_rectangle(
            x_offset, padding_y,
            x_offset + green_width, padding_y + meter_height,
            fill=MeterColors.BG_GREEN, outline=MeterColors.BG_GREEN_BORDER,
        )
        x_offset += green_width

        self._canvas_items["bg_yellow"] = self._canvas.create_rectangle(
            x_offset, padding_y,
            x_offset + yellow_width, padding_y + meter_height,
            fill=MeterColors.BG_YELLOW, outline=MeterColors.BG_YELLOW_BORDER,
        )
        x_offset += yellow_width

        self._canvas_items["bg_red"] = self._canvas.create_rectangle(
            x_offset, padding_y,
            x_offset + red_width, padding_y + meter_height,
            fill=MeterColors.BG_RED, outline=MeterColors.BG_RED_BORDER,
        )

        # Level indicators (start hidden)
        self._canvas_items["level_green"] = self._canvas.create_rectangle(
            0, 0, 0, 0, fill=MeterColors.LEVEL_GREEN, outline="",
        )
        self._canvas_items["level_yellow"] = self._canvas.create_rectangle(
            0, 0, 0, 0, fill=MeterColors.LEVEL_YELLOW, outline="",
        )
        self._canvas_items["level_red"] = self._canvas.create_rectangle(
            0, 0, 0, 0, fill=MeterColors.LEVEL_RED, outline="",
        )

        # Peak indicator line
        self._canvas_items["peak_line"] = self._canvas.create_line(
            0, 0, 0, 0, fill=MeterColors.PEAK_LINE, width=2,
        )

    def reset(self) -> None:
        """Reset meter to minimum level."""
        self._peak_db = DB_MIN
        self._peak_hold_frames = 0
        if self._canvas:
            self._draw_meter(DB_MIN, DB_MIN)
        if self._db_var:
            self._db_var.set("-- dB")


__all__ = ["AudioViewer"]
