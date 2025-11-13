"""Level meter rendering helpers for the audio Tk view."""

from __future__ import annotations

import logging
from typing import Dict, Tuple

try:  # pragma: no cover - Tk unavailable on headless hosts
    import tkinter as tk
    from tkinter import ttk
except Exception:  # pragma: no cover
    tk = None  # type: ignore
    ttk = None  # type: ignore

from ..domain import DB_MAX, DB_MIN, DB_RED, DB_YELLOW, AudioSnapshot


class MeterPanel:
    """Manages the canvas widgets used to render audio level meters."""

    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger.getChild("MeterPanel")
        self._container: "ttk.Frame | None" = None  # type: ignore[assignment]
        self._meter_canvases: Dict[int, "tk.Canvas"] = {}
        self._canvas_items: Dict[int, Dict[str, int]] = {}
        self._rendered_devices: Tuple[int, ...] = ()

    def attach(self, parent) -> None:
        if tk is None or ttk is None:
            return
        if self._container is not None:
            return
        container = ttk.Frame(parent)
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(0, weight=0, minsize=170)
        container.columnconfigure(1, weight=1)
        self._container = container

    def rebuild(self, snapshot: AudioSnapshot) -> None:
        if tk is None or ttk is None or self._container is None:
            return
        desired_order = tuple(sorted(snapshot.selected_devices.keys()))
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
            self._container.rowconfigure(row_index, weight=0)
            device = snapshot.devices.get(device_id) or snapshot.selected_devices[device_id]

            label = ttk.Label(self._container, text=f"Dev{device_id}: {device.name}")
            label.grid(row=row_index, column=0, sticky="w", padx=(0, 6), pady=(0, 3))

            canvas = tk.Canvas(
                self._container,
                width=260,
                height=24,
                bg="#1a1a1a",
                highlightthickness=1,
                highlightbackground="gray",
            )
            canvas.grid(row=row_index, column=1, sticky="ew", pady=(0, 3))
            self._meter_canvases[device_id] = canvas

    def draw(self, snapshot: AudioSnapshot, *, force: bool = False) -> None:
        if tk is None or self._container is None:
            return
        for device_id, canvas in list(self._meter_canvases.items()):
            if not canvas.winfo_exists():
                continue
            meter = snapshot.level_meters.get(device_id)
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
                fill="#1a3a1a",
                outline="#2a4a2a",
            )
            x_offset += green_width
            items["bg_yellow"] = canvas.create_rectangle(
                x_offset,
                padding_y,
                x_offset + yellow_width,
                padding_y + meter_height,
                fill="#3a3a1a",
                outline="#4a4a2a",
            )
            x_offset += yellow_width
            items["bg_red"] = canvas.create_rectangle(
                x_offset,
                padding_y,
                x_offset + red_width,
                padding_y + meter_height,
                fill="#3a1a1a",
                outline="#4a2a2a",
            )
            items["level_green"] = canvas.create_rectangle(0, 0, 0, 0, fill="#00ff00", outline="")
            items["level_yellow"] = canvas.create_rectangle(0, 0, 0, 0, fill="#ffff00", outline="")
            items["level_red"] = canvas.create_rectangle(0, 0, 0, 0, fill="#ff0000", outline="")
            items["peak_line"] = canvas.create_line(0, 0, 0, 0, fill="#ffffff", width=2)
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
