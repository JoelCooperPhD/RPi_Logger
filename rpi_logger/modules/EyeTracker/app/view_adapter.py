"""Tkinter view adapter that renders EyeTracker status inside the stub view."""

from __future__ import annotations

import logging
from typing import Callable, Optional

import numpy as np

try:
    import tkinter as tk
    from tkinter import ttk
except Exception:  # pragma: no cover - defensive import
    tk = None  # type: ignore
    ttk = None  # type: ignore

import io

try:
    from PIL import Image
except Exception:  # pragma: no cover - optional dependency
    Image = None  # type: ignore


FrameProvider = Callable[[], Optional[np.ndarray]]


class EyeTrackerViewAdapter:
    """Lightweight UI helper that populates the stub frame with tracker widgets."""

    def __init__(
        self,
        view,
        *,
        model,
        logger: logging.Logger,
        frame_provider: FrameProvider,
        preview_hz: int,
        disabled_message: Optional[str] = None,
    ) -> None:
        self.view = view
        self.model = model
        self.logger = logger
        self.frame_provider = frame_provider
        self.preview_interval_ms = max(50, int(1000 / max(1, preview_hz)))
        self._disabled_message = disabled_message

        self._preview_after_handle: Optional[str] = None
        self._status_var: Optional[tk.StringVar] = None if tk else None  # type: ignore[assignment]
        self._recording_var: Optional[tk.StringVar] = None if tk else None  # type: ignore[assignment]
        self._canvas: Optional[tk.Canvas] = None  # type: ignore[assignment]
        self._photo_ref = None

        self._build()

    # ------------------------------------------------------------------
    # Construction helpers

    def _build(self) -> None:
        if tk is None or ttk is None or not self.view:
            self.logger.debug("Tkinter not available; skipping UI build")
            return

        def builder(parent: tk.Widget) -> None:
            parent.columnconfigure(0, weight=1)
            parent.rowconfigure(0, weight=1)

            canvas_width = self.model.saved_preview_width or 640
            canvas_height = self.model.saved_preview_height or 480
            canvas = tk.Canvas(parent, width=canvas_width, height=canvas_height, bg="#000000")
            canvas.grid(row=0, column=0, sticky="nsew")
            self._canvas = canvas

            if self._disabled_message:
                canvas.create_text(
                    canvas.winfo_reqwidth() // 2,
                    canvas.winfo_reqheight() // 2,
                    text="Dependencies missing\nCheck logs",
                    fill="#ff4444",
                )

        self.view.build_stub_content(builder)
        if hasattr(self.view, "set_preview_title"):
            try:
                self.view.set_preview_title("Preview")
            except Exception:
                pass
        self._build_status_panel()
        if not self._disabled_message:
            self._schedule_preview()

    def _build_status_panel(self) -> None:
        if tk is None or ttk is None or not self.view:
            return

        initial_status = self._disabled_message or "Device: searching..."
        self._status_var = tk.StringVar(value=initial_status)
        self._recording_var = tk.StringVar(value="Recording: idle")

        def builder(parent: tk.Widget) -> None:
            parent.columnconfigure(0, weight=1)
            status_label = ttk.Label(parent, textvariable=self._status_var, anchor="w")
            status_label.grid(row=0, column=0, sticky="ew")
            recording_label = ttk.Label(parent, textvariable=self._recording_var, anchor="w")
            recording_label.grid(row=1, column=0, sticky="ew", pady=(4, 0))

        self.view.set_io_stub_title("Module Status")
        self.view.build_io_stub_content(builder)

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
        if frame is None or Image is None:
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
                # Use native Tk PhotoImage with PPM to avoid PIL ImageTk issues
                ppm_data = io.BytesIO()
                image.save(ppm_data, format="PPM")
                photo = tk.PhotoImage(data=ppm_data.getvalue())
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

    # ------------------------------------------------------------------
    # Helpers

    def close(self) -> None:
        if not self.view or self._preview_after_handle is None:
            return
        try:
            self.view.root.after_cancel(self._preview_after_handle)
        except Exception:
            pass
        self._preview_after_handle = None
