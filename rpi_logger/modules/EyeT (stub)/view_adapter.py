"""Tkinter view adapter that renders EyeT status inside the stub view."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Awaitable, Callable, Optional

import numpy as np

try:
    import tkinter as tk
    from tkinter import ttk
except Exception:  # pragma: no cover - defensive import
    tk = None  # type: ignore
    ttk = None  # type: ignore

try:
    from PIL import Image, ImageTk
except Exception:  # pragma: no cover - optional dependency
    Image = None  # type: ignore
    ImageTk = None  # type: ignore


FrameProvider = Callable[[], Optional[np.ndarray]]
ActionDispatcher = Callable[[str], None]
AsyncCallback = Callable[[], Awaitable[None]]
SnapshotCallback = Callable[[], Awaitable[Optional[Path]]]
ReconnectCallback = Callable[[], Awaitable[None]]


class EyeTViewAdapter:
    """Lightweight UI helper that populates the stub frame with tracker widgets."""

    def __init__(
        self,
        view,
        *,
        model,
        logger: logging.Logger,
        frame_provider: FrameProvider,
        preview_hz: int,
        action_dispatcher: Optional[ActionDispatcher],
        start_callback: Optional[AsyncCallback],
        stop_callback: Optional[AsyncCallback],
        snapshot_callback: Optional[SnapshotCallback],
        reconnect_callback: Optional[ReconnectCallback],
        disabled_message: Optional[str] = None,
    ) -> None:
        self.view = view
        self.model = model
        self.logger = logger
        self.frame_provider = frame_provider
        self.preview_interval_ms = max(50, int(1000 / max(1, preview_hz)))
        self._action_dispatcher = action_dispatcher
        self._start_callback = start_callback
        self._stop_callback = stop_callback
        self._snapshot_callback = snapshot_callback
        self._reconnect_callback = reconnect_callback
        self._disabled_message = disabled_message

        self._preview_after_handle: Optional[str] = None
        self._status_var: Optional[tk.StringVar] = None
        self._recording_var: Optional[tk.StringVar] = None
        self._snapshot_var: Optional[tk.StringVar] = None
        self._canvas: Optional[tk.Canvas] = None
        self._photo_ref = None

        self._build()

    # ------------------------------------------------------------------
    # Construction helpers

    def _build(self) -> None:
        if tk is None or ttk is None or not self.view:
            self.logger.debug("Tkinter not available; skipping UI build")
            return

        def builder(parent: tk.Widget) -> None:
            frame = ttk.Frame(parent, padding="6")
            frame.grid(row=0, column=0, sticky="nsew")
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(2, weight=1)

            self._status_var = tk.StringVar(value="Device: searching..." if not self._disabled_message else self._disabled_message)
            status_label = ttk.Label(frame, textvariable=self._status_var, anchor="w")
            status_label.grid(row=0, column=0, sticky="ew")

            controls = ttk.Frame(frame)
            controls.grid(row=1, column=0, sticky="ew", pady=(6, 6))
            controls.columnconfigure(4, weight=1)

            start_btn = ttk.Button(controls, text="Start Recording", command=self._on_start_clicked, width=18)
            start_btn.grid(row=0, column=0, padx=(0, 6))
            stop_btn = ttk.Button(controls, text="Stop", command=self._on_stop_clicked, width=10)
            stop_btn.grid(row=0, column=1, padx=(0, 6))
            snap_btn = ttk.Button(controls, text="Snapshot", command=self._on_snapshot_clicked, width=10)
            snap_btn.grid(row=0, column=2, padx=(0, 6))
            reconnect_btn = ttk.Button(controls, text="Reconnect", command=self._on_reconnect_clicked, width=12)
            reconnect_btn.grid(row=0, column=3, padx=(0, 6))

            self._recording_var = tk.StringVar(value="Recording: idle")
            recording_label = ttk.Label(frame, textvariable=self._recording_var, anchor="w")
            recording_label.grid(row=3, column=0, sticky="ew", pady=(6, 0))

            self._snapshot_var = tk.StringVar(value="")
            snapshot_label = ttk.Label(frame, textvariable=self._snapshot_var, anchor="w", font=("TkDefaultFont", 9, "italic"))
            snapshot_label.grid(row=4, column=0, sticky="ew")

            canvas = tk.Canvas(frame, width=self.model.saved_preview_width or 640, height=self.model.saved_preview_height or 480, bg="#000000")
            canvas.grid(row=2, column=0, sticky="nsew")
            self._canvas = canvas

            if self._disabled_message:
                canvas.create_text(
                    canvas.winfo_reqwidth() // 2,
                    canvas.winfo_reqheight() // 2,
                    text="Dependencies missing\nCheck logs",
                    fill="#ff4444",
                )

        self.view.build_stub_content(builder)
        self.view.hide_io_stub()
        if not self._disabled_message:
            self._schedule_preview()

    # ------------------------------------------------------------------
    # Button handlers

    def _on_start_clicked(self) -> None:
        self._dispatch_action("start_recording")
        if self._start_callback:
            asyncio.create_task(self._start_callback())

    def _on_stop_clicked(self) -> None:
        self._dispatch_action("stop_recording")
        if self._stop_callback:
            asyncio.create_task(self._stop_callback())

    def _on_snapshot_clicked(self) -> None:
        if not self._snapshot_callback:
            return
        asyncio.create_task(self._run_snapshot())

    def _on_reconnect_clicked(self) -> None:
        if self._reconnect_callback:
            asyncio.create_task(self._reconnect_callback())

    async def _run_snapshot(self) -> None:
        path = await self._snapshot_callback()  # type: ignore[misc]
        if path and self._snapshot_var:
            self._snapshot_var.set(f"Snapshot saved: {path.name}")
            self._clear_snapshot_label_later()

    def _clear_snapshot_label_later(self) -> None:
        if not self.view or tk is None:
            return
        self.view.root.after(4000, lambda: self._snapshot_var.set("") if self._snapshot_var else None)

    # ------------------------------------------------------------------
    # Preview loop

    def _schedule_preview(self) -> None:
        if not self.view or tk is None:
            return
        self._preview_after_handle = self.view.root.after(self.preview_interval_ms, self._preview_tick)

    def _preview_tick(self) -> None:
        frame = self.frame_provider() if self.frame_provider else None
        if self._canvas is None:
            return
        if frame is None or Image is None or ImageTk is None:
            self._canvas.delete("all")
            self._canvas.create_text(
                self._canvas.winfo_width() // 2,
                self._canvas.winfo_height() // 2,
                text="Waiting for frames...",
                fill="#eeeeee",
            )
        else:
            try:
                rgb = frame[:, :, ::-1]
                image = Image.fromarray(rgb)
                photo = ImageTk.PhotoImage(image)
                self._canvas.delete("all")
                self._canvas.create_image(
                    self._canvas.winfo_width() // 2,
                    self._canvas.winfo_height() // 2,
                    image=photo,
                )
                self._photo_ref = photo
            except Exception as exc:
                self.logger.debug("Preview update failed: %s", exc)
        self._schedule_preview()

    # ------------------------------------------------------------------
    # External updates

    def set_device_status(self, text: str, *, connected: bool) -> None:
        if self._status_var is None:
            return
        prefix = "Device: "
        self._status_var.set(f"{prefix}{text}")

    def set_recording_state(self, active: bool) -> None:
        if self._recording_var is None:
            return
        status = "Recording: active" if active else "Recording: idle"
        self._recording_var.set(status)

    def notify_snapshot(self, path: Path) -> None:
        if self._snapshot_var is None:
            return
        self._snapshot_var.set(f"Snapshot saved: {path.name}")
        self._clear_snapshot_label_later()

    # ------------------------------------------------------------------
    # Helpers

    def _dispatch_action(self, action: str) -> None:
        if not self._action_dispatcher:
            return
        try:
            self._action_dispatcher(action)
        except Exception as exc:
            self.logger.debug("Action dispatch failed: %s", exc)

    def close(self) -> None:
        if not self.view or self._preview_after_handle is None:
            return
        try:
            self.view.root.after_cancel(self._preview_after_handle)
        except Exception:
            pass
        self._preview_after_handle = None
