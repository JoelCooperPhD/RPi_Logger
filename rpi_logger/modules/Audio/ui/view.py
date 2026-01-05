"""Audio Tk view."""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

try:  # pragma: no cover - Tk unavailable on display-less hosts
    import tkinter as tk
    from tkinter import ttk

    from rpi_logger.core.ui.theme.colors import Colors
except Exception:  # pragma: no cover
    tk = None  # type: ignore
    ttk = None  # type: ignore
    Colors = None  # type: ignore

from ..domain import AudioSnapshot, AudioState
from .meter_panel import MeterPanel


SubmitCoroutine = Callable[[Awaitable[None], str], None]


class AudioView:
    """Audio view adapter."""
    def __init__(
        self,
        vmc_view,
        model: AudioState,
        submit_async: SubmitCoroutine,
        logger: logging.Logger,
        mode: str = "gui",
    ) -> None:
        self._vmc_view = vmc_view
        self._model = model
        self._submit_callback = submit_async
        self.logger = logger.getChild("View")
        self.mode = mode
        self._snapshot: AudioSnapshot | None = None
        self.enabled = bool(vmc_view and tk and ttk and mode == "gui")
        self._meter_panel: MeterPanel | None = None
        self._device_label: ttk.Label | None = None

        if not self.enabled:
            if mode != "gui":
                self.logger.info("CLI mode selected; GUI disabled")
            elif not (tk and ttk):
                self.logger.info("Tk unavailable; running without GUI")
            else:
                self.logger.debug("GUI container not available; view disabled")
            return

        self._meter_panel = MeterPanel(self.logger)
        self._vmc_view.build_stub_content(self._build_content)
        self._model.subscribe(self._on_snapshot)
        self._rename_stub_label()
        self._finalize_menus()
        self.logger.info("Audio view attached")

    def _on_snapshot(self, snapshot: AudioSnapshot) -> None:
        self._snapshot = snapshot
        if self._device_label:
            text = self._build_device_label(snapshot)
            if text:
                self._device_label.configure(text=text)
                self._device_label.grid()
            else:
                self._device_label.grid_remove()
        if self._meter_panel:
            self._meter_panel.rebuild(snapshot)
            self._meter_panel.draw(snapshot, force=True)

    def draw_level_meters(self, *, force: bool = False) -> None:
        if not self.enabled or not tk:
            return
        snapshot = self._snapshot
        if not snapshot:
            return
        if self._meter_panel:
            self._meter_panel.draw(snapshot, force=force)

    def _submit(self, coro: Awaitable[None], name: str) -> None:
        if self._submit_callback:
            self._submit_callback(coro, name)

    def _build_content(self, parent: tk.Widget) -> None:
        assert ttk is not None
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        container = ttk.Frame(parent)
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=0)
        container.rowconfigure(1, weight=1)

        self._device_label = ttk.Label(
            container,
            text="Waiting for device assignment...",
            anchor="w",
            font=("TkDefaultFont", 10, "bold"),
        )
        self._device_label.grid(row=0, column=0, sticky="ew", pady=(0, 4))

        if self._meter_panel:
            meters_frame = ttk.Frame(container)
            meters_frame.grid(row=1, column=0, sticky="nsew")
            meters_frame.columnconfigure(0, weight=1)
            meters_frame.rowconfigure(0, weight=1)
            self._meter_panel.attach(meters_frame)

    def _rename_stub_label(self) -> None:
        stub_frame = getattr(self._vmc_view, "stub_frame", None)
        if stub_frame is not None and hasattr(stub_frame, "configure"):
            try:
                stub_frame.configure(text="Audio Control Panel")
            except Exception:
                self.logger.debug("Unable to rename stub frame", exc_info=True)

    def _finalize_menus(self) -> None:
        finalize_view = getattr(self._vmc_view, "finalize_view_menu", None)
        if callable(finalize_view):
            finalize_view(include_capture_stats=False)
        finalize_file = getattr(self._vmc_view, "finalize_file_menu", None)
        if callable(finalize_file):
            finalize_file()

    def _build_device_label(self, snapshot: AudioSnapshot) -> str:
        selected = list(snapshot.selected_devices.values())
        if selected:
            return ""
            
        devices = list(snapshot.devices.values())
        if not devices:
            return "No Audio Devices Found"
            
        names = ", ".join(sorted(info.name for info in devices if info.name))
        if not names:
            return f"{len(devices)} device(s) available"
        return f"Available Devices: {names}"
