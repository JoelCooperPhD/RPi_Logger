"""Tk view for the Audio (Stub) module built on stub codex."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, Optional

try:  # pragma: no cover - Tk unavailable on headless hosts
    import tkinter as tk
    from tkinter import ttk
except Exception:  # pragma: no cover
    tk = None  # type: ignore
    ttk = None  # type: ignore

from ..constants import DB_MAX, DB_MIN, DB_RED, DB_YELLOW
from ..model import AudioSnapshot, AudioStubModel


SubmitCoroutine = Callable[[Awaitable[None], str], None]


@dataclass(slots=True)
class ViewCallbacks:
    toggle_device: Callable[[int, bool], Awaitable[None]]
    start_recording: Callable[[], Awaitable[None]]
    stop_recording: Callable[[], Awaitable[None]]


class AudioStubView:
    """Adapter that renders audio controls inside the stub codex view."""

    def __init__(
        self,
        vmc_view,
        model: AudioStubModel,
        callbacks: ViewCallbacks,
        submit_async: SubmitCoroutine,
        logger: logging.Logger,
        mode: str = "gui",
    ) -> None:
        self._vmc_view = vmc_view
        self._model = model
        self._callbacks = callbacks
        self._submit_callback = submit_async
        self.logger = logger.getChild("View")
        self.mode = mode
        self._meter_container: Optional[ttk.Frame] = None
        self._meter_canvases: Dict[int, tk.Canvas] = {}
        self._canvas_items: Dict[int, Dict[str, int]] = {}
        self._device_menu: Optional[tk.Menu] = None
        self._device_menu_vars: Dict[int, tk.BooleanVar] = {}
        self._control_frame: Optional[ttk.Frame] = None
        self._snapshot: Optional[AudioSnapshot] = None
        self.enabled = bool(vmc_view and tk and ttk)

        if not self.enabled:
            return

        self._vmc_view.build_stub_content(self._build_content)
        self._model.subscribe(self._on_snapshot)
        self._vmc_view.hide_io_stub()
        self._vmc_view.show_logger()
        self.logger.info("Audio stub view attached")

    # ------------------------------------------------------------------
    # Snapshot handling

    def _on_snapshot(self, snapshot: AudioSnapshot) -> None:
        self._snapshot = snapshot
        self._refresh_device_menu(snapshot)
        self._rebuild_meters(snapshot)

    # ------------------------------------------------------------------
    # Public helpers used by controller

    def draw_level_meters(self, *, force: bool = False) -> None:
        if not self.enabled or not tk:
            return
        snapshot = self._snapshot
        if not snapshot:
            return
        for device_id, canvas in list(self._meter_canvases.items()):
            if not canvas.winfo_exists():
                continue
            meter = snapshot.level_meters.get(device_id)
            if not meter:
                continue
            if not force and not meter.dirty and device_id in self._canvas_items:
                continue
            self._draw_meter(canvas, device_id, meter)
            if force:
                meter.clear_dirty()

    def _submit(self, coro: Awaitable[None], name: str) -> None:
        if self._submit_callback:
            self._submit_callback(coro, name)

    # ------------------------------------------------------------------
    # UI construction

    def _build_content(self, parent: tk.Widget) -> None:
        assert ttk is not None
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        container = ttk.Frame(parent)
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)
        container.rowconfigure(1, weight=0)

        self._meter_container = ttk.Frame(container)
        self._meter_container.grid(row=0, column=0, sticky="nsew")
        self._meter_container.columnconfigure(0, weight=1)

        self._control_frame = ttk.Frame(container)
        self._control_frame.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self._build_controls()

        if self.mode == "headless":
            parent.grid_remove()
            self.logger.info("Headless mode active; stub frame hidden")

        self._ensure_device_menu()

    def _build_controls(self) -> None:
        if not self._control_frame or ttk is None:
            return

        for child in list(self._control_frame.winfo_children()):
            child.destroy()

        start_btn = ttk.Button(
            self._control_frame,
            text="Start Recording",
            command=lambda: self._submit(self._callbacks.start_recording(), "view_start_recording"),
        )
        stop_btn = ttk.Button(
            self._control_frame,
            text="Stop Recording",
            command=lambda: self._submit(self._callbacks.stop_recording(), "view_stop_recording"),
        )
        start_btn.grid(row=0, column=0, padx=(0, 6))
        stop_btn.grid(row=0, column=1)

    def _ensure_device_menu(self) -> None:
        if not self.enabled or tk is None:
            return
        if self._device_menu is not None:
            return
        add_menu = getattr(self._vmc_view, "add_menu", None)
        if not callable(add_menu):
            self.logger.debug("View does not expose add_menu; skipping device menu setup")
            return
        self._device_menu = add_menu("Devices")

    def _refresh_device_menu(self, snapshot: AudioSnapshot) -> None:
        if not self.enabled or tk is None:
            return
        self._ensure_device_menu()
        menu = self._device_menu
        if menu is None:
            return

        menu.delete(0, tk.END)
        self._device_menu_vars.clear()

        if not snapshot.devices:
            menu.add_command(label="No devices detected", state=tk.DISABLED)
            return

        for device_id in sorted(snapshot.devices.keys()):
            device = snapshot.devices[device_id]
            var = tk.BooleanVar(value=device_id in snapshot.selected_devices)
            self._device_menu_vars[device_id] = var

            def _toggle(did=device_id, flag_var=var):
                self._submit(
                    self._callbacks.toggle_device(did, flag_var.get()),
                    f"device_toggle_{did}",
                )

            label = f"Device {device_id}: {device.name} ({device.channels}ch, {device.sample_rate:.0f}Hz)"
            menu.add_checkbutton(label=label, variable=var, command=_toggle)

    def _rebuild_meters(self, snapshot: AudioSnapshot) -> None:
        if not self.enabled or tk is None or ttk is None:
            return
        container = self._meter_container
        if not container:
            return

        for child in list(container.winfo_children()):
            child.destroy()

        self._meter_canvases.clear()
        self._canvas_items.clear()

        if not snapshot.selected_devices:
            return

        for row_index, device_id in enumerate(sorted(snapshot.selected_devices.keys())):
            container.rowconfigure(row_index, weight=0)
            frame = ttk.Frame(container)
            frame.grid(row=row_index, column=0, sticky="ew", pady=(0, 3))
            frame.columnconfigure(1, weight=1)

            device = snapshot.devices.get(device_id) or snapshot.selected_devices[device_id]
            label = ttk.Label(frame, text=f"Dev{device_id}: {device.name}", width=14)
            label.grid(row=0, column=0, sticky="w", padx=(0, 6))

            canvas = tk.Canvas(
                frame,
                width=260,
                height=24,
                bg="#1a1a1a",
                highlightthickness=1,
                highlightbackground="gray",
            )
            canvas.grid(row=0, column=1, sticky="ew")
            self._meter_canvases[device_id] = canvas

        self.draw_level_meters(force=True)

    def _draw_meter(self, canvas: tk.Canvas, device_id: int, meter) -> None:
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
