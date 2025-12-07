"""Tkinter view adapter that renders EyeTracker status inside the stub view.

Matches VOG/DRT styling patterns with Theme.apply(), RoundedButton, and
consistent color usage.
"""

from __future__ import annotations

import io
import logging
from typing import Callable, Optional, TYPE_CHECKING

import numpy as np

try:
    import tkinter as tk
    from tkinter import ttk
except Exception:  # pragma: no cover - defensive import
    tk = None  # type: ignore
    ttk = None  # type: ignore

try:
    from PIL import Image
except Exception:  # pragma: no cover - optional dependency
    Image = None  # type: ignore

try:
    from rpi_logger.core.ui.theme.styles import Theme
    from rpi_logger.core.ui.theme.colors import Colors
    from rpi_logger.core.ui.theme.widgets import RoundedButton
    HAS_THEME = True
except ImportError:
    HAS_THEME = False
    Theme = None  # type: ignore
    Colors = None  # type: ignore
    RoundedButton = None  # type: ignore

if TYPE_CHECKING:
    from rpi_logger.modules.EyeTracker.app.eye_tracker_runtime import EyeTrackerRuntime


FrameProvider = Callable[[], Optional[np.ndarray]]


class EyeTrackerViewAdapter:
    """UI helper that populates the stub frame with tracker widgets.

    Follows VOG/DRT styling patterns:
    - Theme.apply() for consistent theming
    - RoundedButton for interactive elements
    - 'Inframe.TLabel' style for labels
    - Consistent padding and colors
    """

    def __init__(
        self,
        view,
        *,
        model,
        logger: logging.Logger,
        frame_provider: FrameProvider,
        preview_hz: int,
        disabled_message: Optional[str] = None,
        runtime: Optional["EyeTrackerRuntime"] = None,
    ) -> None:
        self.view = view
        self.model = model
        self.logger = logger
        self.frame_provider = frame_provider
        self.preview_interval_ms = max(50, int(1000 / max(1, preview_hz)))
        self._disabled_message = disabled_message
        self._runtime = runtime

        self._preview_after_handle: Optional[str] = None
        self._status_var: Optional[tk.StringVar] = None if tk else None  # type: ignore[assignment]
        self._recording_var: Optional[tk.StringVar] = None if tk else None  # type: ignore[assignment]
        self._device_var: Optional[tk.StringVar] = None if tk else None  # type: ignore[assignment]
        self._canvas: Optional[tk.Canvas] = None  # type: ignore[assignment]
        self._photo_ref = None
        self._reconnect_btn: Optional[RoundedButton] = None
        self._configure_btn: Optional[RoundedButton] = None

        self._build()

    # ------------------------------------------------------------------
    # Construction helpers

    def _build(self) -> None:
        if tk is None or ttk is None or not self.view:
            self.logger.debug("Tkinter not available; skipping UI build")
            return

        # Apply theme to root window if available (matching VOG/DRT)
        if HAS_THEME and Theme is not None:
            try:
                root = self.view.root
                if root:
                    Theme.apply(root)
            except Exception as e:
                self.logger.debug("Could not apply theme: %s", e)

        def builder(parent: tk.Widget) -> None:
            parent.columnconfigure(0, weight=1)
            parent.rowconfigure(0, weight=1)

            canvas_width = self.model.saved_preview_width or 640
            canvas_height = self.model.saved_preview_height or 480
            canvas_bg = Colors.BG_CANVAS if HAS_THEME and Colors else "#1e1e1e"
            canvas = tk.Canvas(parent, width=canvas_width, height=canvas_height, bg=canvas_bg)
            canvas.grid(row=0, column=0, sticky="nsew")
            self._canvas = canvas

            if self._disabled_message:
                error_color = Colors.ERROR if HAS_THEME and Colors else "#e74c3c"
                canvas.create_text(
                    canvas.winfo_reqwidth() // 2,
                    canvas.winfo_reqheight() // 2,
                    text="Dependencies missing\nCheck logs",
                    fill=error_color,
                )

        self.view.build_stub_content(builder)
        if hasattr(self.view, "set_preview_title"):
            try:
                self.view.set_preview_title("Preview")
            except AttributeError:
                pass  # Method exists but may not be callable
        self._build_status_panel()
        if not self._disabled_message:
            self._schedule_preview()

    def _build_status_panel(self) -> None:
        """Build the status panel with VOG/DRT styling."""
        if tk is None or ttk is None or not self.view:
            return

        initial_status = self._disabled_message or "Searching..."
        self._status_var = tk.StringVar(value=initial_status)
        self._recording_var = tk.StringVar(value="Idle")
        self._device_var = tk.StringVar(value="None")

        def builder(parent: tk.Widget) -> None:
            parent.columnconfigure(0, weight=1)

            # Status LabelFrame (matching VOG/DRT pattern)
            status_lf = ttk.LabelFrame(parent, text="Device Status")
            status_lf.grid(row=0, column=0, sticky="new", padx=4, pady=(4, 2))
            status_lf.columnconfigure(1, weight=1)

            # Device row
            ttk.Label(status_lf, text="Device:", style='Inframe.TLabel').grid(
                row=0, column=0, sticky="w", padx=5, pady=2
            )
            ttk.Label(status_lf, textvariable=self._device_var, style='Inframe.TLabel').grid(
                row=0, column=1, sticky="e", padx=5, pady=2
            )

            # Status row
            ttk.Label(status_lf, text="Status:", style='Inframe.TLabel').grid(
                row=1, column=0, sticky="w", padx=5, pady=2
            )
            ttk.Label(status_lf, textvariable=self._status_var, style='Inframe.TLabel').grid(
                row=1, column=1, sticky="e", padx=5, pady=2
            )

            # Recording row
            ttk.Label(status_lf, text="Recording:", style='Inframe.TLabel').grid(
                row=2, column=0, sticky="w", padx=5, pady=2
            )
            ttk.Label(status_lf, textvariable=self._recording_var, style='Inframe.TLabel').grid(
                row=2, column=1, sticky="e", padx=5, pady=2
            )

            # Controls LabelFrame (matching VOG lens controls pattern)
            controls_lf = ttk.LabelFrame(parent, text="Controls")
            controls_lf.grid(row=1, column=0, sticky="new", padx=4, pady=2)
            controls_lf.columnconfigure(0, weight=1)
            controls_lf.columnconfigure(1, weight=1)

            # Use RoundedButton if available, otherwise fall back to ttk.Button
            if RoundedButton is not None and HAS_THEME and Colors is not None:
                btn_bg = Colors.BG_FRAME
                self._reconnect_btn = RoundedButton(
                    controls_lf, text="Reconnect",
                    command=self._on_reconnect_clicked,
                    width=80, height=32, style='default', bg=btn_bg
                )
                self._reconnect_btn.grid(row=0, column=0, padx=2, pady=4)

                self._configure_btn = RoundedButton(
                    controls_lf, text="Configure",
                    command=self._on_configure_clicked,
                    width=80, height=32, style='default', bg=btn_bg
                )
                self._configure_btn.grid(row=0, column=1, padx=2, pady=4)
                # Disable configure until device connected
                self._configure_btn.configure(state='disabled')
            else:
                self._reconnect_btn = ttk.Button(
                    controls_lf, text="Reconnect",
                    command=self._on_reconnect_clicked
                )
                self._reconnect_btn.grid(row=0, column=0, sticky="ew", padx=2, pady=4)

                self._configure_btn = ttk.Button(
                    controls_lf, text="Configure",
                    command=self._on_configure_clicked,
                    state='disabled'
                )
                self._configure_btn.grid(row=0, column=1, sticky="ew", padx=2, pady=4)

        self.view.set_io_stub_title("Eye Tracker")
        self.view.build_io_stub_content(builder)

    # ------------------------------------------------------------------
    # Button callbacks

    def _on_reconnect_clicked(self) -> None:
        """Handle reconnect button click."""
        if self._runtime:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._runtime.request_reconnect())
            except RuntimeError:
                self.logger.warning("No event loop available for reconnect")

    def _on_configure_clicked(self) -> None:
        """Handle configure button click - show config dialog."""
        self.logger.info("Configure button clicked")

        if not self._runtime:
            self.logger.warning("No runtime bound - cannot configure")
            return

        # Get root window for the dialog
        root = None
        if self.view:
            try:
                root = self.view.root
            except Exception as e:
                self.logger.error("Failed to get root window: %s", e)

        if not root:
            self.logger.warning("No root window available for config dialog")
            return

        try:
            from rpi_logger.modules.EyeTracker.tracker_core.interfaces.gui.config_window import EyeTrackerConfigWindow
            EyeTrackerConfigWindow(root, self._runtime)
        except ImportError as e:
            self.logger.warning("Config window not available: %s", e)
        except Exception as e:
            self.logger.error("Failed to create config window: %s", e, exc_info=True)

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
            text_color = Colors.FG_PRIMARY if HAS_THEME and Colors else "#ecf0f1"
            self._canvas.create_text(
                self._canvas.winfo_width() // 2,
                self._canvas.winfo_height() // 2,
                text="Waiting for frames...",
                fill=text_color,
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
        """Update device status display."""
        if self._status_var is not None:
            self._status_var.set(text)

        # Enable/disable configure button based on connection state
        if self._configure_btn is not None:
            state = 'normal' if connected else 'disabled'
            try:
                self._configure_btn.configure(state=state)
            except tk.TclError:
                pass  # Widget may be destroyed

    def set_device_info(self, device_name: str) -> None:
        """Update device name display."""
        if self._device_var is not None:
            self._device_var.set(device_name or "None")

    def set_recording_state(self, active: bool) -> None:
        """Update recording state display."""
        if self._recording_var is None:
            return
        status = "Active" if active else "Idle"
        self._recording_var.set(status)

    def bind_runtime(self, runtime: "EyeTrackerRuntime") -> None:
        """Bind runtime reference for button callbacks."""
        self._runtime = runtime

    # ------------------------------------------------------------------
    # Helpers

    def close(self) -> None:
        if not self.view or self._preview_after_handle is None:
            return
        try:
            self.view.root.after_cancel(self._preview_after_handle)
        except tk.TclError:
            pass  # Widget may be destroyed
        self._preview_after_handle = None
