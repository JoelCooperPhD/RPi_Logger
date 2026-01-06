"""Audio level meter panel."""

from __future__ import annotations

import logging

try:  # pragma: no cover - Tk unavailable on headless hosts
    import tkinter as tk
    from tkinter import ttk

    from rpi_logger.core.ui.theme.colors import Colors
except Exception:  # pragma: no cover
    tk = None  # type: ignore
    ttk = None  # type: ignore
    Colors = None  # type: ignore

from ..domain import DB_MAX, DB_MIN, DB_RED, DB_YELLOW, AudioSnapshot

class MeterColors:
    """Meter colors from theme palette."""
    BG_GREEN = "#1a3a1a"
    BG_GREEN_BORDER = "#2a4a2a"
    BG_YELLOW = "#3a3a1a"
    BG_YELLOW_BORDER = "#4a4a2a"
    BG_RED = "#3a1a1a"
    BG_RED_BORDER = "#4a2a2a"
    LEVEL_GREEN: str
    LEVEL_YELLOW: str
    LEVEL_RED: str
    PEAK_LINE: str


def _init_meter_colors() -> None:
    if Colors is not None:
        MeterColors.LEVEL_GREEN = Colors.SUCCESS
        MeterColors.LEVEL_YELLOW = Colors.WARNING
        MeterColors.LEVEL_RED = Colors.ERROR
        MeterColors.PEAK_LINE = Colors.FG_PRIMARY
    else:
        MeterColors.LEVEL_GREEN = "#2ecc71"
        MeterColors.LEVEL_YELLOW = "#f39c12"
        MeterColors.LEVEL_RED = "#e74c3c"
        MeterColors.PEAK_LINE = "#ecf0f1"


_init_meter_colors()


class MeterPanel:
    """Manages the canvas widgets used to render audio level meters."""

    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger.getChild("MeterPanel")
        self._container: "ttk.Frame | None" = None  # type: ignore[assignment]
        self._meter_canvases: dict[int, "tk.Canvas"] = {}
        self._canvas_items: dict[int, dict[str, int]] = {}
        self._rendered_devices: tuple[int, ...] = ()

    def attach(self, parent) -> None:
        if tk is None or ttk is None:
            return
        if self._container is not None:
            return
        container = ttk.Frame(parent)
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        self._container = container

    def rebuild(self, snapshot: AudioSnapshot) -> None:
        if tk is None or ttk is None or self._container is None:
            return
        desired_order = (snapshot.device.device_id,) if snapshot.device else ()
        if desired_order == self._rendered_devices:
            return

        self._rendered_devices = desired_order

        for child in list(self._container.winfo_children()):
            child.destroy()

        self._meter_canvases.clear()
        self._canvas_items.clear()

        if not desired_order:
            return

        for row_index, device_id in enumerate(desired_order):
            self._container.rowconfigure(row_index, weight=1)
            device_frame = ttk.Frame(self._container)
            device_frame.grid(row=row_index, column=0, sticky="ew", pady=(0, 6))
            device_frame.columnconfigure(0, weight=1)
            canvas = tk.Canvas(
                device_frame,
                width=260,
                height=32,
                bg=Colors.BG_CANVAS if Colors else "#1e1e1e",
                highlightthickness=1,
                highlightbackground=Colors.BORDER if Colors else "#404055",
            )
            canvas.grid(row=1, column=0, sticky="ew")
            self._meter_canvases[device_id] = canvas

    def draw(self, snapshot: AudioSnapshot, *, force: bool = False) -> None:
        if tk is None or self._container is None:
            return
        for device_id, canvas in list(self._meter_canvases.items()):
            if not canvas.winfo_exists():
                continue
            meter = snapshot.level_meter if snapshot.device and snapshot.device.device_id == device_id else None
            if not meter:
                continue
            items = self._canvas_items.get(device_id)
            if not force and not meter.dirty and items:
                continue
            self._draw_meter(canvas, device_id, meter)

    def _draw_meter(self, canvas: "tk.Canvas", device_id: int, meter) -> None:
        width = canvas.winfo_width()
        height = canvas.winfo_height()
        if width < 10 or height < 10:
            return

        rms_db, peak_db = meter.get_db_levels()

        padding_x = 5
        padding_y = 3
        usable_width = max(10, width - (2 * padding_x))
        meter_height = max(2, height - (2 * padding_y))

        total_range = DB_MAX - DB_MIN
        green_width = ((DB_YELLOW - DB_MIN) / total_range) * usable_width
        yellow_width = ((DB_RED - DB_YELLOW) / total_range) * usable_width
        red_width = ((DB_MAX - DB_RED) / total_range) * usable_width

        items = self._canvas_items.get(device_id)
        if not items or items.get("width") != width or items.get("height") != height:
            canvas.delete("all")
            items = {"width": width, "height": height}
            x_offset = padding_x
            items["bg_green"] = canvas.create_rectangle(
                x_offset,
                padding_y,
                x_offset + green_width,
                padding_y + meter_height,
                fill=MeterColors.BG_GREEN,
                outline=MeterColors.BG_GREEN_BORDER,
            )
            x_offset += green_width
            items["bg_yellow"] = canvas.create_rectangle(
                x_offset,
                padding_y,
                x_offset + yellow_width,
                padding_y + meter_height,
                fill=MeterColors.BG_YELLOW,
                outline=MeterColors.BG_YELLOW_BORDER,
            )
            x_offset += yellow_width
            items["bg_red"] = canvas.create_rectangle(
                x_offset,
                padding_y,
                x_offset + red_width,
                padding_y + meter_height,
                fill=MeterColors.BG_RED,
                outline=MeterColors.BG_RED_BORDER,
            )
            items["level_green"] = canvas.create_rectangle(
                0, 0, 0, 0, fill=MeterColors.LEVEL_GREEN, outline=""
            )
            items["level_yellow"] = canvas.create_rectangle(
                0, 0, 0, 0, fill=MeterColors.LEVEL_YELLOW, outline=""
            )
            items["level_red"] = canvas.create_rectangle(
                0, 0, 0, 0, fill=MeterColors.LEVEL_RED, outline=""
            )
            items["peak_line"] = canvas.create_line(
                0, 0, 0, 0, fill=MeterColors.PEAK_LINE, width=2
            )
            self._canvas_items[device_id] = items

        rms_position = max(DB_MIN, min(rms_db, DB_MAX))
        rms_fraction = (rms_position - DB_MIN) / total_range
        rms_width = rms_fraction * usable_width

        def _set_coords(item_id: int, start_x: float, end_x: float) -> None:
            canvas.coords(item_id, start_x, padding_y, end_x, padding_y + meter_height)

        x_offset = padding_x
        remaining = rms_width

        if remaining > 0:
            green_fill = min(remaining, green_width)
            _set_coords(items["level_green"], x_offset, x_offset + green_fill)
            remaining -= green_fill
            x_offset += green_fill
        else:
            _set_coords(items["level_green"], 0, 0)

        if remaining > 0:
            yellow_fill = min(remaining, yellow_width)
            _set_coords(items["level_yellow"], x_offset, x_offset + yellow_fill)
            remaining -= yellow_fill
            x_offset += yellow_fill
        else:
            _set_coords(items["level_yellow"], 0, 0)

        if remaining > 0:
            red_fill = min(remaining, red_width)
            _set_coords(items["level_red"], x_offset, x_offset + red_fill)
        else:
            _set_coords(items["level_red"], 0, 0)

        if peak_db > DB_MIN:
            peak_position = max(DB_MIN, min(peak_db, DB_MAX))
            peak_fraction = (peak_position - DB_MIN) / total_range
            peak_x = padding_x + (peak_fraction * usable_width)
            canvas.coords(
                items["peak_line"],
                peak_x,
                padding_y,
                peak_x,
                padding_y + meter_height,
            )
        else:
            canvas.coords(items["peak_line"], 0, 0, 0, 0)

        meter.clear_dirty()


__all__ = ["MeterPanel"]
