"""Tk view for the audio module built on the codex surface."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

try:  # pragma: no cover - Tk unavailable on display-less hosts
    import tkinter as tk
    from tkinter import ttk
except Exception:  # pragma: no cover
    tk = None  # type: ignore
    ttk = None  # type: ignore

from ..domain import AudioSnapshot, AudioState
from .device_menu import DeviceMenuController
from .meter_panel import MeterPanel


SubmitCoroutine = Callable[[Awaitable[None], str], None]


@dataclass(slots=True)
class ViewCallbacks:
    toggle_device: Callable[[int, bool], Awaitable[None]]


class AudioView:
    """Adapter that renders audio controls inside the codex view."""

    def __init__(
        self,
        vmc_view,
        model: AudioState,
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
        self._snapshot: Optional[AudioSnapshot] = None
        self.enabled = bool(vmc_view and tk and ttk and mode == "gui")
        self._menu_controller: DeviceMenuController | None = None
        self._meter_panel: MeterPanel | None = None

        if not self.enabled:
            if mode != "gui":
                self.logger.info("CLI mode selected; GUI disabled")
            elif not (tk and ttk):
                self.logger.info("Tk unavailable; running without GUI")
            else:
                self.logger.debug("GUI container not available; view disabled")
            return

        self._menu_controller = DeviceMenuController(self._vmc_view, self._submit, self.logger)
        self._meter_panel = MeterPanel(self.logger)
        self._vmc_view.build_stub_content(self._build_content)
        self._model.subscribe(self._on_snapshot)
        self._vmc_view.hide_io_stub()
        self._vmc_view.show_logger()
        self._rename_stub_label()
        self.logger.info("Audio view attached")

    # ------------------------------------------------------------------
    # Snapshot handling

    def _on_snapshot(self, snapshot: AudioSnapshot) -> None:
        self._snapshot = snapshot
        if self._menu_controller:
            self._menu_controller.refresh(snapshot, self._callbacks.toggle_device)
        if self._meter_panel:
            self._meter_panel.rebuild(snapshot)
            self._meter_panel.draw(snapshot, force=True)

    # ------------------------------------------------------------------
    # Public helpers used by controller

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

        if self._meter_panel:
            self._meter_panel.attach(container)

    def _rename_stub_label(self) -> None:
        stub_frame = getattr(self._vmc_view, "stub_frame", None)
        if stub_frame is not None and hasattr(stub_frame, "configure"):
            try:
                stub_frame.configure(text="Audio Control Panel")
            except Exception:
                self.logger.debug("Unable to rename stub frame", exc_info=True)
