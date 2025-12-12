"""GPS view factory for VMC integration.

Implements the GPS module GUI with map preview and telemetry display,
following the VOG/DRT view pattern for consistency.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

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

        # Create UI
        if embedded_parent:
            self._build_ui(embedded_parent)

    def _build_ui(self, parent: tk.Widget):
        """Build the embedded UI container."""
        # Main frame
        self._frame = ttk.Frame(parent)
        self._frame.pack(fill=tk.BOTH, expand=True)
        self._frame.columnconfigure(0, weight=1)
        self._frame.rowconfigure(0, weight=1)

        # Content frame - runtime will populate this
        self._content_frame = ttk.Frame(self._frame)
        self._content_frame.grid(row=0, column=0, sticky="NSEW")
        self._content_frame.columnconfigure(0, weight=1)
        self._content_frame.rowconfigure(0, weight=1)

        # Status label for when no device is connected
        if HAS_THEME and Colors is not None:
            self._status_label = tk.Label(
                self._content_frame,
                text="Waiting for GPS device...",
                bg=Colors.BG_FRAME,
                fg=Colors.FG_SECONDARY,
                font=("TkDefaultFont", 11),
            )
        else:
            self._status_label = ttk.Label(
                self._content_frame,
                text="Waiting for GPS device...",
            )
        self._status_label.grid(row=0, column=0)

    def get_content_frame(self) -> Optional[tk.Widget]:
        """Get the content frame for runtime to populate."""
        return self._content_frame

    def on_device_connected(self, device_id: str, port: str = None):
        """Handle device connection."""
        self.logger.info("GPS device connected: %s (port: %s)", device_id, port)
        self._device_id = device_id
        self._port = port
        self._connected = True

        # Hide status label - runtime will show map
        if self._status_label:
            self._status_label.grid_forget()

        # Update window title
        self._update_window_title()

    def on_device_disconnected(self, device_id: str):
        """Handle device disconnection."""
        self.logger.info("GPS device disconnected: %s", device_id)

        if self._device_id != device_id:
            return

        self._device_id = None
        self._port = None
        self._connected = False

        # Show status label
        if self._status_label:
            self._status_label.configure(text="GPS device disconnected")
            self._status_label.grid(row=0, column=0)

        self._update_window_title()

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
            self.logger.info("Applied pending runtime binding to GUI")

        return container

    def bind_runtime(self, runtime) -> None:
        """Allow the runtime to expose its API to the GUI once ready."""
        self._runtime = runtime
        if not self.gui:
            self.logger.warning("bind_runtime called but self.gui is None")
            return
        self.gui.system = runtime
        self.logger.info("Runtime bound to GUI (system=%s)", type(runtime).__name__)
        if isinstance(self.gui.async_bridge, _LoopAsyncBridge):
            loop = getattr(runtime, "_loop", None)
            if loop:
                self.gui.async_bridge.bind_loop(loop)
        # Set data folder subdirectory for File menu
        if hasattr(self._stub_view, 'set_data_subdir'):
            module_subdir = getattr(runtime, 'module_subdir', 'GPS')
            self._stub_view.set_data_subdir(module_subdir)

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
