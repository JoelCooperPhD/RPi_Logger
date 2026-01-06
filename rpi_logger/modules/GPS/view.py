"""GPS view factory for VMC integration.

Implements the GPS module GUI with map preview and telemetry display,
following the VOG/DRT view pattern for consistency.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

from rpi_logger.core.logging_utils import ensure_structured_logger, get_module_logger
from vmc import LegacyTkViewBridge, StubCodexView

try:
    import tkinter as tk
    from tkinter import ttk
    HAS_TK = True
except ImportError:
    HAS_TK = False
    tk = None
    ttk = None

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    Image = None
    ImageTk = None

try:
    from rpi_logger.core.ui.theme.styles import Theme
    from rpi_logger.core.ui.theme.widgets import RoundedButton
    from rpi_logger.core.ui.theme.colors import Colors
    HAS_THEME = True
except ImportError:
    HAS_THEME = False
    Theme = None
    RoundedButton = None
    Colors = None

try:
    from .config_window import GPSConfigWindow
except ImportError:
    GPSConfigWindow = None

ActionCallback = Optional[Callable[..., Awaitable[None]]]

FIX_QUALITY_DESC = {
    0: "Invalid", 1: "GPS", 2: "DGPS", 3: "PPS",
    4: "RTK", 5: "Float RTK", 6: "Est", 7: "Manual", 8: "Sim"
}

CARDINAL_DIRS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


class _SystemPlaceholder:
    """Minimal stand-in until the runtime is bound to the GUI."""

    recording: bool = False
    trial_label: str = ""

    def __init__(self):
        self.config = {}

    def get_fix(self):
        """Return placeholder fix data."""
        return None


class _LoopAsyncBridge:
    """Lightweight bridge that schedules coroutines on the active asyncio loop."""

    def __init__(self) -> None:
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def run_coroutine(self, coro):
        loop = self._resolve_loop()
        return asyncio.run_coroutine_threadsafe(coro, loop)

    def _resolve_loop(self) -> asyncio.AbstractEventLoop:
        if self.loop and not self.loop.is_closed():
            return self.loop
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError as exc:
            raise RuntimeError("Tkinter bridge has no running event loop bound") from exc
        self.loop = loop
        return loop


class GPSTkinterGUI:
    """Tkinter GUI container for GPS module.

    The actual map and telemetry rendering is delegated to the runtime,
    which has the tile rendering and NMEA parsing logic.
    """

    def __init__(
        self,
        args,
        action_callback: ActionCallback,
        logger: Optional[logging.Logger] = None,
        embedded_parent: Optional["tk.Widget"] = None,
    ):
        self._action_callback = action_callback
        self.system = _SystemPlaceholder()
        self.args = args
        self.logger = ensure_structured_logger(logger, fallback_name="GPSTkinterGUI") if logger else get_module_logger("GPSTkinterGUI")
        self.async_bridge: Optional[_LoopAsyncBridge] = None

        # Device state
        self._device_id: Optional[str] = None
        self._port: Optional[str] = None
        self._connected = False
        self._connection_type: str = "UART"  # Default for GPS

        # Session state (matching VOG/DRT pattern)
        self._session_active = False
        self._running = False

        # UI references
        self.root = embedded_parent
        self._frame: Optional[tk.Frame] = None
        self._content_frame: Optional[tk.Frame] = None
        self._status_label: Optional[tk.Label] = None
        self._configure_btn: Optional[Any] = None
        self._map_canvas: Optional[tk.Canvas] = None
        self._map_photo = None  # Keep reference to prevent garbage collection

        # Split layout components
        self._paned_window: Optional[tk.PanedWindow] = None
        self._map_frame: Optional[tk.Frame] = None
        self._dashboard_frame: Optional[tk.Frame] = None
        self._zoom_in_btn = None
        self._zoom_out_btn = None
        self._telemetry_vars: Dict[str, tk.StringVar] = {}
        self._telemetry_labels: Dict[str, tk.Label] = {}
        self._zoom_callback: Optional[Callable] = None

        # Create UI
        if embedded_parent:
            self._build_ui(embedded_parent)

    def _build_ui(self, parent: tk.Widget):
        bg = Colors.BG_DARK if HAS_THEME and Colors else "gray20"
        fg = Colors.FG_PRIMARY if HAS_THEME and Colors else "white"
        fg_sec = Colors.FG_SECONDARY if HAS_THEME and Colors else "gray70"

        self._frame = tk.Frame(parent, bg=bg)
        self._frame.pack(fill=tk.BOTH, expand=True)
        self._frame.columnconfigure(0, weight=1)
        self._frame.rowconfigure(0, weight=1)

        self._content_frame = tk.Frame(self._frame, bg=bg)
        self._content_frame.grid(row=0, column=0, sticky="NSEW")
        self._content_frame.columnconfigure(0, weight=1)
        self._content_frame.rowconfigure(0, weight=1)

        # Status label for when no device is connected
        self._status_label = tk.Label(
            self._content_frame,
            text="Waiting for GPS device...",
            bg=bg,
            fg=fg_sec,
            font=("TkDefaultFont", 11),
        )
        self._status_label.grid(row=0, column=0)

        # PanedWindow for split layout (hidden until device connects)
        self._paned_window = tk.PanedWindow(
            self._content_frame,
            orient=tk.HORIZONTAL,
            bg=bg,
            sashwidth=4,
            sashrelief=tk.FLAT,
        )

        # Build map panel (left side)
        self._build_map_panel(self._paned_window)
        self._paned_window.add(self._map_frame, minsize=300, stretch="always")

        # Build dashboard panel (right side)
        self._build_dashboard_panel(self._paned_window)
        self._paned_window.add(self._dashboard_frame, minsize=180, stretch="never")

    def _build_map_panel(self, parent):
        bg = Colors.BG_FRAME if HAS_THEME and Colors else "gray25"

        self._map_frame = tk.Frame(parent, bg=bg)

        # Map canvas fills the frame
        self._map_canvas = tk.Canvas(self._map_frame, bg=bg, highlightthickness=0)
        self._map_canvas.pack(fill=tk.BOTH, expand=True)

        # Zoom button container - overlaid in top-right
        zoom_frame = tk.Frame(self._map_frame, bg=bg)
        zoom_frame.place(relx=1.0, rely=0.0, anchor="ne", x=-10, y=10)

        btn_bg = Colors.BTN_DEFAULT_BG if HAS_THEME and Colors else "#404040"
        btn_fg = Colors.BTN_DEFAULT_FG if HAS_THEME and Colors else "white"

        self._zoom_in_btn = tk.Button(
            zoom_frame, text="+", font=("TkDefaultFont", 14, "bold"),
            width=2, height=1, bg=btn_bg, fg=btn_fg,
            activebackground=Colors.BTN_DEFAULT_HOVER if HAS_THEME and Colors else "#505050",
            relief=tk.FLAT, command=self._on_zoom_in
        )
        self._zoom_in_btn.pack(pady=(0, 2))

        self._zoom_out_btn = tk.Button(
            zoom_frame, text="-", font=("TkDefaultFont", 14, "bold"),
            width=2, height=1, bg=btn_bg, fg=btn_fg,
            activebackground=Colors.BTN_DEFAULT_HOVER if HAS_THEME and Colors else "#505050",
            relief=tk.FLAT, command=self._on_zoom_out
        )
        self._zoom_out_btn.pack()

    def _build_dashboard_panel(self, parent):
        bg = Colors.BG_DARK if HAS_THEME and Colors else "gray20"
        fg = Colors.FG_PRIMARY if HAS_THEME and Colors else "white"
        fg_sec = Colors.FG_SECONDARY if HAS_THEME and Colors else "gray70"
        fg_muted = Colors.FG_MUTED if HAS_THEME and Colors else "gray50"

        self._dashboard_frame = tk.Frame(parent, bg=bg)

        # Title
        title = tk.Label(
            self._dashboard_frame, text="GPS TELEMETRY",
            bg=bg, fg=fg, font=("TkDefaultFont", 10, "bold")
        )
        title.pack(pady=(8, 4), padx=8, anchor="w")

        # Initialize all StringVars with placeholder values
        metrics = [
            "lat", "lon", "alt", "speed", "heading",
            "sats", "hdop", "fix_mode", "fix_quality", "gps_time"
        ]
        for m in metrics:
            self._telemetry_vars[m] = tk.StringVar(value="---")

        # POSITION group
        self._build_metric_group("POSITION", [
            ("Lat", "lat", ""),
            ("Lon", "lon", ""),
            ("Alt", "alt", "m"),
        ])

        # MOTION group
        self._build_metric_group("MOTION", [
            ("Speed", "speed", "mph"),
            ("Heading", "heading", ""),
        ])

        # SIGNAL group
        self._build_metric_group("SIGNAL", [
            ("Sats", "sats", ""),
            ("HDOP", "hdop", ""),
            ("Fix", "fix_mode", ""),
            ("Quality", "fix_quality", ""),
        ])

        # TIME group
        self._build_metric_group("TIME", [
            ("GPS", "gps_time", ""),
        ])

    def _build_metric_group(self, title: str, metrics: list):
        bg = Colors.BG_DARK if HAS_THEME and Colors else "gray20"
        bg_frame = Colors.BG_FRAME if HAS_THEME and Colors else "gray25"
        fg = Colors.FG_PRIMARY if HAS_THEME and Colors else "white"
        fg_sec = Colors.FG_SECONDARY if HAS_THEME and Colors else "gray70"

        # Group frame with border
        group = tk.Frame(self._dashboard_frame, bg=bg_frame, relief=tk.FLAT)
        group.pack(fill=tk.X, padx=6, pady=3)

        # Group title
        lbl = tk.Label(group, text=title, bg=bg_frame, fg=fg_sec, font=("TkDefaultFont", 8))
        lbl.pack(anchor="w", padx=4, pady=(2, 0))

        # Metrics
        for label_text, var_key, unit in metrics:
            row = tk.Frame(group, bg=bg_frame)
            row.pack(fill=tk.X, padx=4, pady=1)

            lbl = tk.Label(row, text=label_text, bg=bg_frame, fg=fg_sec,
                          font=("TkDefaultFont", 9), width=7, anchor="w")
            lbl.pack(side=tk.LEFT)

            val_lbl = tk.Label(row, textvariable=self._telemetry_vars[var_key],
                              bg=bg_frame, fg=fg, font=("TkFixedFont", 10), anchor="e")
            val_lbl.pack(side=tk.RIGHT, fill=tk.X, expand=True)
            self._telemetry_labels[var_key] = val_lbl

            if unit:
                unit_lbl = tk.Label(row, text=unit, bg=bg_frame, fg=fg_sec,
                                   font=("TkDefaultFont", 8), width=4, anchor="w")
                unit_lbl.pack(side=tk.RIGHT)

    def _on_zoom_in(self):
        if self._zoom_callback:
            self._zoom_callback(1)

    def _on_zoom_out(self):
        if self._zoom_callback:
            self._zoom_callback(-1)

    # ------------------------------------------------------------------
    # Value formatting helpers

    def _format_coord(self, val: Optional[float], is_lat: bool) -> str:
        if val is None:
            return "---"
        direction = ("N" if val >= 0 else "S") if is_lat else ("E" if val >= 0 else "W")
        return f"{abs(val):.6f} {direction}"

    def _format_float(self, val: Optional[float], decimals: int = 1) -> str:
        if val is None:
            return "---"
        return f"{val:.{decimals}f}"

    def _format_heading(self, deg: Optional[float]) -> str:
        if deg is None:
            return "---"
        idx = int((deg + 22.5) / 45) % 8
        cardinal = CARDINAL_DIRS[idx]
        return f"{deg:.0f}° {cardinal}"

    def _format_satellites(self, in_use: Optional[int], in_view: Optional[int]) -> str:
        u = str(in_use) if in_use is not None else "--"
        v = str(in_view) if in_view is not None else "--"
        return f"{u} / {v}"

    def _format_time(self, ts: Optional[datetime]) -> str:
        if ts is None:
            return "--:--:-- Z"
        return ts.strftime("%H:%M:%S Z")

    def _format_fix_quality(self, quality: Optional[int]) -> str:
        if quality is None:
            return "---"
        desc = FIX_QUALITY_DESC.get(quality, "?")
        return f"{quality} ({desc})"

    # ------------------------------------------------------------------
    # Dashboard update

    def update_dashboard(self, fix) -> None:
        if fix is None:
            # Reset to placeholders
            for var in self._telemetry_vars.values():
                var.set("---")
            self._telemetry_vars["sats"].set("-- / --")
            self._telemetry_vars["gps_time"].set("--:--:-- Z")
            return

        # Position
        self._telemetry_vars["lat"].set(self._format_coord(fix.latitude, is_lat=True))
        self._telemetry_vars["lon"].set(self._format_coord(fix.longitude, is_lat=False))
        self._telemetry_vars["alt"].set(self._format_float(fix.altitude_m, 1))

        # Motion
        self._telemetry_vars["speed"].set(self._format_float(fix.speed_mph, 1))
        self._telemetry_vars["heading"].set(self._format_heading(fix.course_deg))

        # Signal quality
        self._telemetry_vars["sats"].set(
            self._format_satellites(fix.satellites_in_use, fix.satellites_in_view)
        )
        self._telemetry_vars["hdop"].set(self._format_float(fix.hdop, 1))
        self._telemetry_vars["fix_mode"].set(fix.fix_mode or "No Fix")
        self._telemetry_vars["fix_quality"].set(self._format_fix_quality(fix.fix_quality))

        # Time
        self._telemetry_vars["gps_time"].set(self._format_time(fix.timestamp))

        # Color-code fix mode based on validity
        if "fix_mode" in self._telemetry_labels:
            lbl = self._telemetry_labels["fix_mode"]
            if fix.fix_mode == "3D":
                color = Colors.SUCCESS if HAS_THEME and Colors else "#2ecc71"
            elif fix.fix_mode == "2D":
                color = Colors.WARNING if HAS_THEME and Colors else "#f39c12"
            else:
                color = Colors.ERROR if HAS_THEME and Colors else "#e74c3c"
            lbl.configure(fg=color)

    def get_content_frame(self) -> Optional[tk.Widget]:
        """Get the content frame for runtime to populate."""
        return self._content_frame

    def on_device_connected(self, device_id: str, port: str = None):
        self.logger.info("GPS device connected: %s (port: %s)", device_id, port)
        self._device_id = device_id
        self._port = port
        self._connected = True

        # Hide status label and show paned window with map + dashboard
        if self._status_label:
            self._status_label.grid_forget()
        if self._paned_window:
            self._paned_window.grid(row=0, column=0, sticky="NSEW")

        self._update_window_title()

    def on_device_disconnected(self, device_id: str):
        self.logger.info("GPS device disconnected: %s", device_id)

        if self._device_id != device_id:
            return

        self._device_id = None
        self._port = None
        self._connected = False

        # Hide paned window and show status label
        if self._paned_window:
            self._paned_window.grid_forget()
        if self._status_label:
            self._status_label.configure(text="GPS device disconnected")
            self._status_label.grid(row=0, column=0)

        self._update_window_title()

    def update_map_display(self, pil_image, info_str: str = "", fix=None) -> None:
        if not self._map_canvas or not HAS_PIL or pil_image is None:
            return
        try:
            self._map_photo = ImageTk.PhotoImage(pil_image)
            self._map_canvas.delete("all")
            self._map_canvas.create_image(0, 0, image=self._map_photo, anchor="nw")
        except Exception as e:
            self.logger.warning("Failed to update map display: %s", e)

        # Update dashboard with fix data
        if fix is not None:
            self.update_dashboard(fix)

    def update_connection_status(self, connected: bool, error: Optional[str] = None):
        """Update connection status display."""
        if not self._connected:
            # Device not assigned yet
            return

        if self._status_label:
            if connected:
                self._status_label.grid_forget()
            else:
                msg = "Connection lost"
                if error:
                    msg = f"Connection error: {error}"
                self._status_label.configure(text=msg)
                self._status_label.grid(row=0, column=0)

    def _update_window_title(self) -> None:
        """Update window title based on instance ID or connected device."""
        if not self.root:
            return

        try:
            toplevel = self.root.winfo_toplevel()

            # Primary: Use instance_id if available (for multi-instance modules)
            if hasattr(self.args, 'instance_id') and self.args.instance_id:
                title = self.args.instance_id
            # Fallback: Build from device info (original logic)
            elif self._connected and self._port:
                # Format: "GPS(UART):serial0" (matching VOG/DRT pattern)
                port_short = self._port
                if '/' in port_short:
                    port_short = port_short.split('/')[-1]
                # Remove common prefixes
                if port_short.startswith('tty'):
                    port_short = port_short[3:]

                title = f"GPS({self._connection_type}):{port_short}"
            else:
                title = "GPS"

            toplevel.title(title)
            self.logger.debug("GPS window title set to: %s", title)
        except Exception as e:
            self.logger.warning("Failed to update window title: %s", e)

    # ------------------------------------------------------------------
    # Session state management (matching VOG/DRT pattern)

    def handle_session_started(self) -> None:
        """Handle session start (Start button) - prepare for recording."""
        self._session_active = True
        self.logger.debug("GPS session started")

    def handle_session_stopped(self) -> None:
        """Handle session stop (Stop button) - finalize session."""
        self._session_active = False
        self.logger.debug("GPS session stopped")

    # ------------------------------------------------------------------
    # Configuration dialog

    def _on_configure_clicked(self) -> None:
        """Handle configure button click - show config dialog."""
        self.logger.info("Configure button clicked for port: %s", self._port)

        if self._port is None:
            self.logger.warning("No device connected - cannot configure")
            return

        if GPSConfigWindow is None:
            self.logger.warning("Configuration dialog not available (import failed)")
            return

        # Check if runtime is properly bound (not placeholder)
        if isinstance(self.system, _SystemPlaceholder):
            self.logger.warning("Runtime not yet bound - cannot configure device")
            try:
                from tkinter import messagebox
                messagebox.showwarning(
                    "Not Ready",
                    "System not fully initialized. Please wait a moment and try again.",
                    parent=self._frame.winfo_toplevel() if self._frame else None
                )
            except Exception:
                pass
            return

        # Get root window for the dialog
        root = None
        if self._frame:
            try:
                root = self._frame.winfo_toplevel()
            except Exception as e:
                self.logger.error("Failed to get toplevel window: %s", e)

        if not root:
            self.logger.warning("No root window available for config dialog")
            return

        try:
            GPSConfigWindow(
                root,
                self._port,
                self.system,
                async_bridge=self.async_bridge,
                logger=self.logger,
            )
        except Exception as e:
            self.logger.error("Failed to create config window: %s", e, exc_info=True)

    def sync_recording_state(self):
        """Sync recording state with system."""
        # GPS doesn't have recording controls in the view
        pass

    def handle_window_close(self):
        """Handle window close event."""
        pass

    def show(self):
        """Show the GPS frame."""
        if self._frame:
            self._frame.pack(fill=tk.BOTH, expand=True)

    def hide(self):
        """Hide the GPS frame."""
        if self._frame:
            self._frame.pack_forget()


class GPSView:
    """Adapter that exposes the GPS GUI through the stub supervisor interface."""

    def __init__(
        self,
        args,
        model,
        action_callback: Optional[Callable[[str], Awaitable[None]]] = None,
        *,
        display_name: str,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.args = args
        self.model = model
        self.action_callback = action_callback
        self.display_name = display_name or "GPS"
        self.logger = ensure_structured_logger(logger, fallback_name="GPSView") if logger else get_module_logger("GPSView")
        stub_logger = self.logger.getChild("Stub")
        self._stub_view = StubCodexView(
            args,
            model,
            action_callback=action_callback,
            display_name=self.display_name,
            logger=stub_logger,
        )
        self._bridge = LegacyTkViewBridge(self._stub_view, logger=self.logger.getChild("Bridge"))
        self.gui: Optional[GPSTkinterGUI] = None
        self._runtime = None

        # Session state tracking (matching VOG/DRT pattern)
        self._initial_session_dir: Optional[Path] = None
        self._active_session_dir: Optional[Path] = None
        self._session_visual_active = False

        self._bridge.mount(self._build_embedded_gui)
        self._stub_view.set_preview_title("GPS Preview")
        self.model.subscribe(self._on_model_change)
        self._override_help_menu()
        self._finalize_menus()

    def _build_embedded_gui(self, parent) -> Optional[Any]:
        if not HAS_TK:
            self.logger.warning("Tkinter unavailable; cannot mount GPS GUI")
            return None

        # Apply theme to root window if available
        if HAS_THEME and Theme is not None:
            try:
                root = parent.winfo_toplevel()
                Theme.apply(root)
            except Exception as e:
                self.logger.debug("Could not apply theme: %s", e)

        frame_cls = ttk.Frame if ttk is not None else tk.Frame
        if hasattr(parent, "columnconfigure"):
            try:
                parent.columnconfigure(0, weight=1)
                parent.rowconfigure(0, weight=1)
            except Exception:
                pass

        container = frame_cls(parent)
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        gui = GPSTkinterGUI(
            self.args,
            self._dispatch_action,
            logger=self.logger.getChild("GUI"),
            embedded_parent=container,
        )
        gui.async_bridge = _LoopAsyncBridge()
        loop = getattr(self._stub_view, "_event_loop", None)
        if loop and isinstance(gui.async_bridge, _LoopAsyncBridge):
            gui.async_bridge.bind_loop(loop)
        self.gui = gui

        # Apply pending runtime binding if bind_runtime was called before GUI was created
        if self._runtime:
            gui.system = self._runtime
            gui._zoom_callback = self._handle_zoom_request
            self.logger.info("Applied pending runtime binding to GUI")

        return container

    def bind_runtime(self, runtime) -> None:
        self._runtime = runtime
        if not self.gui:
            self.logger.warning("bind_runtime called but self.gui is None")
            return
        self.gui.system = runtime
        self.gui._zoom_callback = self._handle_zoom_request
        self.logger.info("Runtime bound to GUI (system=%s)", type(runtime).__name__)
        if isinstance(self.gui.async_bridge, _LoopAsyncBridge):
            loop = getattr(runtime, "_loop", None)
            if loop:
                self.gui.async_bridge.bind_loop(loop)
        if hasattr(self._stub_view, 'set_data_subdir'):
            module_subdir = getattr(runtime, 'module_subdir', 'GPS')
            self._stub_view.set_data_subdir(module_subdir)

    def _handle_zoom_request(self, delta: int) -> None:
        if not self._runtime:
            return
        renderer = getattr(self._runtime, 'get_map_renderer', lambda: None)()
        if renderer:
            renderer.adjust_zoom(delta)
            # Update button states based on zoom limits
            if self.gui:
                self.call_in_gui(self._update_zoom_button_states, renderer)

    def _update_zoom_button_states(self, renderer) -> None:
        if not self.gui:
            return
        can_in = renderer.can_zoom_in() if hasattr(renderer, 'can_zoom_in') else True
        can_out = renderer.can_zoom_out() if hasattr(renderer, 'can_zoom_out') else True

        if self.gui._zoom_in_btn:
            self.gui._zoom_in_btn.configure(state="normal" if can_in else "disabled")
        if self.gui._zoom_out_btn:
            self.gui._zoom_out_btn.configure(state="normal" if can_out else "disabled")

    def get_content_frame(self) -> Optional[Any]:
        """Get the content frame for runtime to build UI into."""
        if self.gui:
            return self.gui.get_content_frame()
        return None

    def call_in_gui(self, func, *args, **kwargs) -> None:
        if not HAS_TK:
            return
        root = getattr(self._stub_view, "root", None)
        if not root:
            return
        try:
            root.after(0, lambda: func(*args, **kwargs))
        except tk.TclError:
            return

    # ------------------------------------------------------------------
    # Runtime-to-view notifications

    def on_device_connected(self, device_id: str, port: str = None) -> None:
        if not self.gui:
            return
        self.call_in_gui(self.gui.on_device_connected, device_id, port)

    def on_device_disconnected(self, device_id: str) -> None:
        if not self.gui:
            return
        self.call_in_gui(self.gui.on_device_disconnected, device_id)

    def update_connection_status(self, connected: bool, error: Optional[str] = None) -> None:
        if not self.gui:
            return
        self.call_in_gui(self.gui.update_connection_status, connected, error)

    def update_recording_state(self) -> None:
        if not self.gui:
            return
        self.call_in_gui(self.gui.sync_recording_state)

    def on_gps_data(self, device_id: str, fix, pil_image=None, info_str: str = "") -> None:
        if not self.gui:
            return
        # Always update dashboard with fix, update map only if we have an image
        if pil_image is not None:
            self.call_in_gui(self.gui.update_map_display, pil_image, info_str, fix)
        elif fix is not None:
            self.call_in_gui(self.gui.update_dashboard, fix)

    def set_window_title(self, title: str) -> None:
        """Set the window title."""
        if not HAS_TK:
            return
        root = getattr(self._stub_view, "root", None)
        if root:
            try:
                root.winfo_toplevel().title(title)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Stub view delegation for runtime UI building

    def set_preview_title(self, title: str) -> None:
        """Delegate to stub view."""
        self._stub_view.set_preview_title(title)

    def build_stub_content(self, builder_fn) -> None:
        """Allow runtime to build content into the preview area."""
        # Get the content frame from our GUI and pass to builder
        if self.gui:
            content_frame = self.gui.get_content_frame()
            if content_frame:
                # Clear existing content except status label
                for child in content_frame.winfo_children():
                    if child != self.gui._status_label:
                        child.destroy()
                builder_fn(content_frame)

    def build_telemetry_content(self, builder_fn) -> None:
        """Delegate telemetry panel building to stub view."""
        telemetry_builder = getattr(self._stub_view, "build_telemetry_content", None)
        if callable(telemetry_builder):
            telemetry_builder(builder_fn)

    def set_preview_sidecar_minsize(self, min_width: int) -> None:
        """Delegate sidecar configuration to stub view."""
        configure_sidecar = getattr(self._stub_view, "set_preview_sidecar_minsize", None)
        if callable(configure_sidecar):
            configure_sidecar(min_width)

    # ------------------------------------------------------------------
    # Lifecycle controls

    async def run(self) -> float:
        return await self._stub_view.run()

    async def cleanup(self) -> None:
        if self.gui:
            try:
                self.gui.handle_window_close()
            except Exception:
                pass
        self._bridge.cleanup()
        await self._stub_view.cleanup()
        self.gui = None

    def attach_logging_handler(self) -> None:
        self._stub_view.attach_logging_handler()

    @property
    def window_duration_ms(self) -> float:
        return getattr(self._stub_view, "window_duration_ms", 0.0)

    # ------------------------------------------------------------------
    # Help menu

    def _override_help_menu(self) -> None:
        """Replace the generic help menu command with GPS-specific help."""
        help_menu = getattr(self._stub_view, 'help_menu', None)
        if help_menu is None:
            return
        try:
            # Delete existing "Quick Start Guide" entry and add GPS-specific one
            help_menu.delete(0)
            help_menu.add_command(label="Quick Start Guide", command=self._show_gps_help)
        except Exception as e:
            self.logger.debug("Could not override help menu: %s", e)

    def _show_gps_help(self) -> None:
        """Show GPS-specific help dialog."""
        try:
            from .help_dialog import GPSHelpDialog
            root = getattr(self._stub_view, 'root', None)
            if root:
                GPSHelpDialog(root)
        except Exception as e:
            self.logger.error("Failed to show GPS help dialog: %s", e)

    def _finalize_menus(self) -> None:
        """Finalize View and File menus with standard items."""
        # Finalize View menu (adds Capture Stats, Logger)
        finalize_view = getattr(self._stub_view, "finalize_view_menu", None)
        if callable(finalize_view):
            finalize_view()

        # Finalize File menu (adds Quit)
        finalize_file = getattr(self._stub_view, "finalize_file_menu", None)
        if callable(finalize_file):
            finalize_file()

    # ------------------------------------------------------------------
    # Internal helpers

    async def _dispatch_action(self, action: str, **kwargs) -> None:
        if not self.action_callback:
            return
        await self.action_callback(action, **kwargs)

    def _on_model_change(self, prop: str, value) -> None:
        if prop == "recording":
            self.update_recording_state()
        elif prop == "session_dir":
            self._handle_session_dir_change(value)

    def _handle_session_dir_change(self, value) -> None:
        """Handle session directory changes to track session start/stop."""
        if value:
            try:
                path = Path(value)
            except (TypeError, ValueError):
                return

            # First session dir is set at startup, don't trigger session start
            if self._initial_session_dir is None:
                self._initial_session_dir = path
                return

            # Same path as already active - no change
            if self._session_visual_active and self._active_session_dir == path:
                return

            # New session started
            self._active_session_dir = path
            self._session_visual_active = True
            if self.gui:
                self.call_in_gui(self.gui.handle_session_started)
        else:
            # Session ended
            self._active_session_dir = None
            if not self._session_visual_active:
                return
            self._session_visual_active = False
            if self.gui:
                self.call_in_gui(self.gui.handle_session_stopped)
