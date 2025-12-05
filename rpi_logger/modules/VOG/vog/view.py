"""VOG view factory for VMC integration.

Implements the RS_Logger sVOG GUI pattern with real-time matplotlib plotting
for single-device support.
"""

from __future__ import annotations

import asyncio
import logging
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
    from .plotter import VOGPlotter, HAS_MATPLOTLIB
except ImportError:
    VOGPlotter = None
    HAS_MATPLOTLIB = False

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
    # Try relative import first (works when imported as rpi_logger.modules.VOG.vog.view)
    from ..vog_core.interfaces.gui.config_window import VOGConfigWindow
except ImportError:
    try:
        # Fall back to absolute import (works when imported as vog.view from MODULE_DIR)
        from rpi_logger.modules.VOG.vog_core.interfaces.gui.config_window import VOGConfigWindow
    except ImportError:
        VOGConfigWindow = None

ActionCallback = Optional[Callable[..., Awaitable[None]]]


class _SystemPlaceholder:
    """Minimal stand-in until the runtime is bound to the GUI."""

    recording: bool = False
    trial_label: str = ""

    def __init__(self, args=None):
        self.config = getattr(args, 'config', {})
        self.config_file_path = getattr(args, 'config_file_path', None)

    async def start_recording(self) -> bool:
        return False

    async def stop_recording(self) -> bool:
        return False

    def get_device_handler(self, port: str):
        return None


class _LoopAsyncBridge:
    """Lightweight bridge that schedules coroutines on the active asyncio loop.

    Uses run_coroutine_threadsafe for thread-safe scheduling from Tkinter callbacks.
    """

    def __init__(self) -> None:
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def run_coroutine(self, coro):
        loop = self._resolve_loop()
        # Use run_coroutine_threadsafe for thread-safe scheduling from Tk thread
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


class VOGTkinterGUI:
    """Tkinter GUI for VOG with RS_Logger-style plotting.

    Key features:
    - Real-time matplotlib plotting of stimulus state and shutter timing
    - Results display (trial number, TSOT, TSCT)
    - Configuration dialog for device settings
    """

    def __init__(
        self,
        args,
        action_callback: ActionCallback,
        logger: Optional[logging.Logger] = None,
        embedded_parent: Optional["tk.Widget"] = None,
    ):
        self._action_callback = action_callback
        self.system = _SystemPlaceholder(args)
        self.args = args
        self.logger = ensure_structured_logger(logger, fallback_name="VOGTkinterGUI") if logger else get_module_logger("VOGTkinterGUI")
        self.async_bridge: Optional[_LoopAsyncBridge] = None

        # Single device state
        self._port: Optional[str] = None
        self._device_type: str = 'svog'
        self._plotter: Optional[VOGPlotter] = None

        # Results display variables
        self._trl_n: Optional[tk.StringVar] = None
        self._tsot: Optional[tk.StringVar] = None
        self._tsct: Optional[tk.StringVar] = None

        # Control buttons
        self._stm_on: Optional[Any] = None
        self._stm_off: Optional[Any] = None
        self._configure_btn: Optional[Any] = None

        # Session and recording state
        # _session_active: True when Start pressed, False when Stop pressed
        # _running: True when Record is active, False when Paused
        self._session_active = False
        self._running = False
        self._plot_recording_state: Optional[bool] = None

        # UI references
        self.root = embedded_parent
        self._frame: Optional[tk.Frame] = None
        self._content_frame: Optional[tk.Frame] = None
        self._controls_panel: Optional[tk.Frame] = None

        # Create UI
        if embedded_parent:
            self._build_ui(embedded_parent)

    def _build_ui(self, parent: tk.Widget):
        """Build the embedded UI with plotter and controls."""
        # Main frame
        self._frame = ttk.Frame(parent)
        self._frame.pack(fill=tk.BOTH, expand=True)
        self._frame.columnconfigure(0, weight=1)
        self._frame.rowconfigure(0, weight=1)

        # Content frame
        self._content_frame = ttk.Frame(self._frame)
        self._content_frame.grid(row=0, column=0, sticky="NSEW")
        self._content_frame.columnconfigure(0, weight=1)
        self._content_frame.rowconfigure(0, weight=1)

        # Build device UI immediately with default device type
        # Port is None until a device connects - configure button will be disabled
        self._build_device_ui(None, 'svog')

    def _build_device_ui(self, port: Optional[str], device_type: str):
        """Build UI components for the device.

        Args:
            port: Device port, or None if no device connected yet
            device_type: Device type ('svog' or 'wvog')
        """
        if not self._content_frame:
            return

        # Normalize device_type to string (may be enum or string)
        device_type = device_type.value if hasattr(device_type, 'value') else str(device_type)
        self._device_type = device_type

        # Add plotter (left side)
        if HAS_MATPLOTLIB and VOGPlotter is not None:
            try:
                title = f"{device_type.upper()} - Visual Occlusion Glasses"
                self._plotter = VOGPlotter(self._content_frame, title=title)
                self.logger.info("Created plotter for %s", port or "pending device")
            except Exception as e:
                self.logger.warning("Could not create plotter: %s", e)
                self._plotter = None
        else:
            self._plotter = None

        # Create right-side controls panel with visible border
        if HAS_THEME and Colors is not None:
            self._controls_panel = tk.Frame(
                self._content_frame,
                bg=Colors.BG_FRAME,
                highlightbackground=Colors.BORDER,
                highlightcolor=Colors.BORDER,
                highlightthickness=1
            )
        else:
            self._controls_panel = ttk.Frame(self._content_frame)
        self._controls_panel.grid(row=0, column=1, sticky="NS", padx=(4, 2), pady=2)
        self._controls_panel.grid_rowconfigure(1, weight=1)

        # Add manual controls
        self._add_manual_controls(self._controls_panel, device_type)

        # Add results display
        self._add_results(self._controls_panel)

        # Add configure button
        self._add_configure_button(self._controls_panel)

        # Disable configure button if no device connected yet
        if port is None and self._configure_btn:
            self._configure_btn.configure(state='disabled')

    def _add_manual_controls(self, parent: tk.Widget, device_type: str):
        """Add lens control buttons."""
        lf = ttk.LabelFrame(parent, text="Lens State")
        lf.grid(row=0, column=0, sticky="NEW", padx=4, pady=(4, 2))
        lf.grid_columnconfigure(0, weight=1)
        lf.grid_columnconfigure(1, weight=1)

        # Button labels differ by device type
        if device_type == 'wvog':
            open_text = "Open"
            close_text = "Close"
        else:
            open_text = "Clear"
            close_text = "Opaque"

        # Use RoundedButton if available, otherwise fall back to ttk.Button
        if RoundedButton is not None:
            btn_bg = Colors.BG_FRAME if Colors is not None else None
            self._stm_on = RoundedButton(lf, text=open_text, command=self._on_lens_clear,
                                         width=80, height=32, style='default', bg=btn_bg)
            self._stm_on.grid(row=0, column=0, padx=2, pady=2)

            self._stm_off = RoundedButton(lf, text=close_text, command=self._on_lens_opaque,
                                          width=80, height=32, style='default', bg=btn_bg)
            self._stm_off.grid(row=0, column=1, padx=2, pady=2)
        else:
            self._stm_on = ttk.Button(lf, text=open_text, command=self._on_lens_clear)
            self._stm_on.grid(row=0, column=0, sticky="NEWS", padx=2, pady=2)

            self._stm_off = ttk.Button(lf, text=close_text, command=self._on_lens_opaque)
            self._stm_off.grid(row=0, column=1, sticky="NEWS", padx=2, pady=2)

    def _add_results(self, parent: tk.Widget):
        """Add results display (trial number, TSOT, TSCT)."""
        lf = ttk.LabelFrame(parent, text="Results")
        lf.grid(row=2, column=0, sticky="NEW", padx=4, pady=2)
        lf.grid_columnconfigure(1, weight=1)

        # Trial Number
        self._trl_n = tk.StringVar(value="0")
        ttk.Label(lf, text="Trial Number:", style='Inframe.TLabel').grid(row=0, column=0, sticky="W", padx=5)
        ttk.Label(lf, textvariable=self._trl_n, style='Inframe.TLabel').grid(row=0, column=1, sticky="E", padx=5)

        # TSOT - Total Shutter Open Time
        self._tsot = tk.StringVar(value="0")
        ttk.Label(lf, text="TSOT (ms):", style='Inframe.TLabel').grid(row=1, column=0, sticky="W", padx=5)
        ttk.Label(lf, textvariable=self._tsot, style='Inframe.TLabel').grid(row=1, column=1, sticky="E", padx=5)

        # TSCT - Total Shutter Close Time
        self._tsct = tk.StringVar(value="0")
        ttk.Label(lf, text="TSCT (ms):", style='Inframe.TLabel').grid(row=2, column=0, sticky="W", padx=5)
        ttk.Label(lf, textvariable=self._tsct, style='Inframe.TLabel').grid(row=2, column=1, sticky="E", padx=5)

    def _add_configure_button(self, parent: tk.Widget):
        """Add device configuration button."""
        f = ttk.Frame(parent, style='Inframe.TFrame')
        f.grid(row=3, column=0, sticky="NEW", padx=4, pady=(2, 4))
        f.grid_columnconfigure(0, weight=1)

        # Use RoundedButton if available, otherwise fall back to ttk.Button
        if RoundedButton is not None:
            btn_bg = Colors.BG_FRAME if Colors is not None else None
            self._configure_btn = RoundedButton(
                f, text="Configure Unit",
                command=self._on_configure_clicked,
                width=120, height=32, style='default',
                bg=btn_bg
            )
            self._configure_btn.grid(row=0, column=0, pady=2)
        else:
            self._configure_btn = ttk.Button(
                f, text="Configure Unit",
                command=self._on_configure_clicked
            )
            self._configure_btn.grid(row=0, column=0, sticky="NEWS")

    # ------------------------------------------------------------------
    # Device connection/disconnection

    def on_device_connected(self, port: str, device_type: str = 'svog'):
        """Handle device connection - update port and enable configure button."""
        type_str = device_type.value if hasattr(device_type, 'value') else str(device_type)
        self.logger.info("%s device connected: %s", type_str.upper(), port)

        if self._port is not None:
            self.logger.warning("Device already connected at %s, ignoring new connection at %s", self._port, port)
            return

        self._port = port
        self._device_type = type_str

        # Update window title with device info
        self._update_window_title()

        # Enable configure button now that device is connected
        if self._configure_btn:
            self._configure_btn.configure(state='normal')

    def on_device_disconnected(self, port: str, device_type: str = None):
        """Handle device disconnection - clean up UI."""
        self.logger.info("Device disconnected: %s (type: %s)", port, device_type)

        if self._port != port:
            return

        # Clean up plotter
        if self._plotter:
            try:
                self._plotter.stop()
            except Exception:
                pass
            self._plotter = None

        # Clear controls panel
        if self._controls_panel:
            try:
                self._controls_panel.destroy()
            except Exception:
                pass
            self._controls_panel = None

        # Reset state
        self._port = None
        self._device_type = None
        self._stm_on = None
        self._stm_off = None
        self._configure_btn = None
        self._trl_n = None
        self._tsot = None
        self._tsct = None

        # Reset window title
        self._update_window_title()

    def _update_window_title(self) -> None:
        """Update window title based on connected device."""
        if not self.root:
            return

        try:
            toplevel = self.root.winfo_toplevel()
            if self._port and self._device_type:
                # Format: "VOG - USB:ACM0" or "VOG - Wireless:ACM0"
                # Extract short port name (e.g., "ACM0" from "/dev/ttyACM0")
                port_short = self._port
                if '/' in port_short:
                    port_short = port_short.split('/')[-1]
                if port_short.startswith('tty'):
                    port_short = port_short[3:]

                # Determine connection type from device_type
                device_type_lower = self._device_type.lower()
                if 'wireless' in device_type_lower:
                    conn_type = "Wireless"
                else:
                    conn_type = "USB"

                title = f"VOG - {conn_type}:{port_short}"
            else:
                title = "VOG"

            toplevel.title(title)
        except Exception as e:
            self.logger.warning("Failed to update window title: %s", e)

    def on_device_data(self, port: str, data_type: str, data: Dict[str, Any]):
        """Handle data from device - update plots and displays."""
        self.logger.debug("on_device_data: port=%s type=%s data=%s", port, data_type, data)

        if port != self._port:
            self.logger.warning("on_device_data: port %s does not match connected port %s", port, self._port)
            return

        # Handle stimulus state updates
        if data_type == 'stimulus' or data.get('event') == 'stimulus':
            state = data.get('state', data.get('value'))
            self.logger.debug("Stimulus update: state=%s, plotter=%s, running=%s", state, self._plotter, self._running)
            if state is not None and self._plotter:
                try:
                    self.logger.debug("Calling state_update: recording=%s, run=%s", self._plotter.recording, self._plotter.run)
                    self._plotter.state_update(int(state))
                except (ValueError, TypeError) as e:
                    self.logger.error("state_update failed: %s", e)

        # Handle trial data updates
        elif data_type == 'data' or data.get('event') == 'data':
            trial = data.get('trial_number')
            opened = data.get('shutter_open')
            closed = data.get('shutter_closed')

            if trial is not None and self._trl_n:
                self._trl_n.set(str(trial))
            if opened is not None:
                if self._tsot:
                    self._tsot.set(str(opened))
                if self._plotter:
                    self._plotter.tsot_update(int(opened))
            if closed is not None:
                if self._tsct:
                    self._tsct.set(str(closed))
                if self._plotter:
                    self._plotter.tsct_update(int(closed))

    # ------------------------------------------------------------------
    # Recording state management

    def sync_recording_state(self):
        """Sync recording state with system - enable/disable controls."""
        recording = getattr(self.system, 'recording', False)
        self._running = recording
        self._sync_plotter_recording_state()
        self._sync_control_states()

    def _sync_plotter_recording_state(self) -> None:
        """Sync plotter recording state with system recording state."""
        recording = bool(getattr(self.system, 'recording', False))
        if self._plot_recording_state == recording:
            return
        self._plot_recording_state = recording

        if self._plotter:
            if recording:
                self._plotter.start_recording()
            else:
                self._plotter.stop_recording()

    def _sync_control_states(self):
        """Enable/disable controls based on recording state."""
        recording = getattr(self.system, 'recording', False)
        state = 'disabled' if recording else 'normal'

        if self._stm_on:
            self._stm_on.configure(state=state)
        if self._stm_off:
            self._stm_off.configure(state=state)
        if self._configure_btn:
            self._configure_btn.configure(state=state)

    def handle_session_started(self) -> None:
        """Handle session start (Start button) - clear and start plotter."""
        self._plot_recording_state = None
        self._session_active = True
        if self._plotter:
            self._plotter.start_session()
        # Reset results
        if self._trl_n:
            self._trl_n.set('0')
        if self._tsot:
            self._tsot.set('0')
        if self._tsct:
            self._tsct.set('0')

    def handle_session_stopped(self) -> None:
        """Handle session stop (Stop button) - freeze plotter completely."""
        self._plot_recording_state = None
        self._session_active = False
        if self._plotter:
            self._plotter.stop()

    # ------------------------------------------------------------------
    # Button callbacks

    def _on_lens_clear(self):
        """Handle lens clear/open button click."""
        if self._action_callback and self.async_bridge:
            self.async_bridge.run_coroutine(self._action_callback("peek_open"))

    def _on_lens_opaque(self):
        """Handle lens opaque/close button click."""
        if self._action_callback and self.async_bridge:
            self.async_bridge.run_coroutine(self._action_callback("peek_close"))

    def _on_configure_clicked(self):
        """Handle configure button click - show config dialog."""
        self.logger.info("Configure button clicked for port: %s", self._port)

        if self._port is None:
            self.logger.warning("No device connected - cannot configure")
            return

        if VOGConfigWindow is None:
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

        if not self.system or not hasattr(self.system, 'get_device_handler'):
            self.logger.warning("System not available for configuration (system=%s)", type(self.system).__name__)
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
            VOGConfigWindow(root, self._port, self.system, self._device_type, async_bridge=self.async_bridge)
        except Exception as e:
            self.logger.error("Failed to create config window: %s", e, exc_info=True)

    # ------------------------------------------------------------------
    # UI helpers

    def handle_window_close(self):
        """Handle window close event."""
        self._running = False
        self._session_active = False
        self._plot_recording_state = None
        if self._plotter:
            self._plotter.stop()

    def show(self):
        """Show the VOG frame."""
        if self._frame:
            self._frame.pack(fill=tk.BOTH, expand=True)

    def hide(self):
        """Hide the VOG frame."""
        if self._frame:
            self._frame.pack_forget()


class VOGView:
    """Adapter that exposes the VOG GUI through the stub supervisor interface."""

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
        self.display_name = display_name or "VOG"
        self.logger = ensure_structured_logger(logger, fallback_name="VOGView") if logger else get_module_logger("VOGView")
        stub_logger = self.logger.getChild("Stub")
        self._stub_view = StubCodexView(
            args,
            model,
            action_callback=action_callback,
            display_name=self.display_name,
            logger=stub_logger,
        )
        self._bridge = LegacyTkViewBridge(self._stub_view, logger=self.logger.getChild("Bridge"))
        self.gui: Optional[VOGTkinterGUI] = None
        self._runtime = None
        self._initial_session_dir: Optional[Path] = None
        self._active_session_dir: Optional[Path] = None
        self._session_visual_active = False

        self._bridge.mount(self._build_embedded_gui)
        self._stub_view.set_preview_title("VOG Controls")
        self.model.subscribe(self._on_model_change)
        self._override_help_menu()

    def _build_embedded_gui(self, parent) -> Optional[Any]:
        if not HAS_TK:
            self.logger.warning("Tkinter unavailable; cannot mount VOG GUI")
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

        gui = VOGTkinterGUI(
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
            self.logger.info("Applied pending runtime binding to GUI (system=%s)", type(self._runtime).__name__)

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

    def attach_logging_handler(self) -> None:
        self._stub_view.attach_logging_handler()

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

    def on_device_connected(self, port: str, device_type: str = 'svog') -> None:
        if not self.gui:
            return
        self.call_in_gui(self.gui.on_device_connected, port, device_type)

    def on_device_disconnected(self, port: str, device_type: str = None) -> None:
        if not self.gui:
            return
        self.call_in_gui(self.gui.on_device_disconnected, port, device_type)

    def on_device_data(self, port: str, data_type: str, payload: Dict[str, Any]) -> None:
        if not self.gui:
            return
        self.call_in_gui(self.gui.on_device_data, port, data_type, payload)

    def update_recording_state(self) -> None:
        if not self.gui:
            return
        self.call_in_gui(self.gui.sync_recording_state)

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
        if value:
            try:
                path = Path(value)
            except (TypeError, ValueError):
                return

            if self._initial_session_dir is None:
                self._initial_session_dir = path
                return

            if self._session_visual_active and self._active_session_dir == path:
                return

            self._active_session_dir = path
            self._session_visual_active = True
            if self.gui:
                self.call_in_gui(self.gui.handle_session_started)
        else:
            self._active_session_dir = None
            if not self._session_visual_active:
                return
            self._session_visual_active = False
            if self.gui:
                self.call_in_gui(self.gui.handle_session_stopped)

    def _override_help_menu(self) -> None:
        """Replace the generic help menu command with VOG-specific help."""
        help_menu = getattr(self._stub_view, 'help_menu', None)
        if help_menu is None:
            return
        try:
            # Delete existing "Quick Start Guide" entry and add VOG-specific one
            help_menu.delete(0)
            help_menu.add_command(label="Quick Start Guide", command=self._show_vog_help)
        except Exception as e:
            self.logger.debug("Could not override help menu: %s", e)

    def _show_vog_help(self) -> None:
        """Show VOG-specific help dialog."""
        try:
            from .help_dialog import VOGHelpDialog
            root = getattr(self._stub_view, 'root', None)
            if root:
                VOGHelpDialog(root)
        except Exception as e:
            self.logger.error("Failed to show VOG help dialog: %s", e)
