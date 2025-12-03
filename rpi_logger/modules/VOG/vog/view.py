"""VOG view factory for VMC integration.

Implements the RS_Logger sVOG GUI pattern with device-keyed maps,
real-time matplotlib plotting, and tabbed multi-device support.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

import numpy as np

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
    from .config_dialog import VOGConfigDialog
except ImportError:
    VOGConfigDialog = None

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
    """Lightweight bridge that schedules coroutines on the active asyncio loop."""

    def __init__(self) -> None:
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def run_coroutine(self, coro):
        loop = self._resolve_loop()
        return loop.create_task(coro)

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
    """Tkinter GUI for VOG with RS_Logger-style device maps and plotting.

    Key features:
    - Tabbed notebook for multi-device support
    - Real-time matplotlib plotting of stimulus state and shutter timing
    - Device-keyed dictionaries (maps) for state management
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

        # Device maps - keyed by port (e.g., '/dev/ttyACM0')
        # Each entry contains: frame, device_type, plot, stm_on, stm_off, configure, trl_n, tsot, tsct
        self.devices: Dict[str, Dict[str, Any]] = {}

        # Session and recording state (separate as in RS_Logger)
        # _session_active: True when Start pressed, False when Stop pressed
        # _running: True when Record is active, False when Paused
        self._session_active = False
        self._running = False
        self._plot_recording_state: Optional[bool] = None  # Track plotter sync state

        # Configuration dialog
        self._config_dialog: Optional[VOGConfigDialog] = None

        # UI references
        self.root = embedded_parent
        self._frame: Optional[tk.Frame] = None
        self._notebook: Optional[ttk.Notebook] = None

        # Create UI
        if embedded_parent:
            self._build_ui(embedded_parent)

    def _build_ui(self, parent: tk.Widget):
        """Build the embedded UI with notebook and controls."""
        # Main frame
        self._frame = ttk.Frame(parent)
        self._frame.pack(fill=tk.BOTH, expand=True)
        self._frame.columnconfigure(0, weight=1)
        self._frame.rowconfigure(0, weight=1)

        # Device notebook (tabs for each device)
        self._notebook = ttk.Notebook(self._frame)
        self._notebook.grid(row=0, column=0, sticky="NSEW")

    def build_tab(self, port: str, device_type: str = 'svog') -> Dict[str, Any]:
        """Build a tab for a device and return the widget map.

        This follows the RS_Logger pattern where build_tab returns a dict
        containing all the widgets and state for the device.
        """
        if not self._notebook:
            return {}

        tab_widgets: Dict[str, Any] = {}

        # Create tab frame - matches RS_Logger layout
        tab_frame = ttk.Frame(self._notebook, name=port.lower().replace('/', '_'))
        tab_frame.grid_columnconfigure(0, weight=1)  # Plotter column expands
        tab_frame.grid_rowconfigure(3, weight=1)  # Row 3 is spacer between Lens State and Results

        tab_widgets['frame'] = tab_frame
        tab_widgets['device_type'] = device_type

        # Add tab to notebook
        short_port = port.split('/')[-1]
        tab_text = f"{short_port} ({device_type.upper()})"
        self._notebook.add(tab_frame, text=tab_text)

        # Add plotter (left side, spanning rows)
        if HAS_MATPLOTLIB and VOGPlotter is not None:
            try:
                title = f"{device_type.upper()} - Visual Occlusion Glasses"
                plotter = VOGPlotter(tab_frame, title=title)
                plotter.add_device(port)
                tab_widgets['plot'] = plotter
            except Exception as e:
                self.logger.warning("Could not create plotter: %s", e)
                tab_widgets['plot'] = None
        else:
            tab_widgets['plot'] = None

        # Add manual controls (right side)
        self._add_manual_controls(tab_frame, tab_widgets, device_type)

        # Add results display
        self._add_results(tab_frame, tab_widgets)

        # Add configure button
        self._add_configure_button(tab_frame, tab_widgets, port)

        return tab_widgets

    def _add_manual_controls(self, parent: tk.Widget, tab_widgets: Dict, device_type: str):
        """Add lens control buttons."""
        lf = ttk.LabelFrame(parent, text="Lens State")
        lf.grid(row=1, column=1, sticky="NEWS")
        lf.grid_columnconfigure(0, weight=1)

        # Button labels differ by device type
        if device_type == 'wvog':
            open_text = "Open"
            close_text = "Close"
        else:
            open_text = "Clear"
            close_text = "Opaque"

        stm_on = ttk.Button(lf, text=open_text, command=self._on_lens_clear)
        stm_on.grid(row=0, column=0, sticky="NEWS", padx=2, pady=2)
        tab_widgets['stm_on'] = stm_on

        stm_off = ttk.Button(lf, text=close_text, command=self._on_lens_opaque)
        stm_off.grid(row=0, column=1, sticky="NEWS", padx=2, pady=2)
        tab_widgets['stm_off'] = stm_off

    def _add_results(self, parent: tk.Widget, tab_widgets: Dict):
        """Add results display (trial number, TSOT, TSCT)."""
        lf = ttk.LabelFrame(parent, text="Results")
        lf.grid(row=4, column=1, sticky="NEWS")
        lf.grid_columnconfigure(1, weight=1)

        # Trial Number
        tab_widgets['trl_n'] = tk.StringVar(value="0")
        ttk.Label(lf, text="Trial Number:").grid(row=0, column=0, sticky="W", padx=5)
        ttk.Label(lf, textvariable=tab_widgets['trl_n']).grid(row=0, column=1, sticky="E", padx=5)

        # TSOT - Total Shutter Open Time
        tab_widgets['tsot'] = tk.StringVar(value="0")
        ttk.Label(lf, text="TSOT (ms):").grid(row=1, column=0, sticky="W", padx=5)
        ttk.Label(lf, textvariable=tab_widgets['tsot']).grid(row=1, column=1, sticky="E", padx=5)

        # TSCT - Total Shutter Close Time
        tab_widgets['tsct'] = tk.StringVar(value="0")
        ttk.Label(lf, text="TSCT (ms):").grid(row=2, column=0, sticky="W", padx=5)
        ttk.Label(lf, textvariable=tab_widgets['tsct']).grid(row=2, column=1, sticky="E", padx=5)

    def _add_configure_button(self, parent: tk.Widget, tab_widgets: Dict, port: str):
        """Add device configuration button."""
        f = ttk.Frame(parent)
        f.grid(row=5, column=1, sticky="NEWS")
        f.grid_columnconfigure(0, weight=1)

        configure_btn = ttk.Button(
            f, text="Configure Unit",
            command=lambda p=port: self._on_configure_clicked(p)
        )
        configure_btn.grid(row=0, column=0, sticky="NEWS")
        tab_widgets['configure'] = configure_btn

    # ------------------------------------------------------------------
    # Device connection/disconnection

    def on_device_connected(self, port: str, device_type: str = 'svog'):
        """Handle device connection - create tab and register in devices map."""
        self.logger.info("%s device connected: %s", device_type.upper(), port)

        if port in self.devices:
            return

        # Build tab and store in devices map
        tab_widgets = self.build_tab(port, device_type)
        self.devices[port] = tab_widgets

    def on_device_disconnected(self, port: str):
        """Handle device disconnection - remove tab and clean up."""
        self.logger.info("Device disconnected: %s", port)

        if port not in self.devices:
            return

        tab_widgets = self.devices.pop(port)

        # Remove plotter device
        if tab_widgets.get('plot'):
            try:
                tab_widgets['plot'].remove_device(port)
            except Exception:
                pass

        # Remove tab from notebook
        if self._notebook and 'frame' in tab_widgets:
            try:
                self._notebook.forget(tab_widgets['frame'])
            except Exception:
                pass

    def on_device_data(self, port: str, data_type: str, data: Dict[str, Any]):
        """Handle data from device - update plots and displays."""
        self.logger.debug("on_device_data: port=%s type=%s data=%s", port, data_type, data)

        if port not in self.devices:
            self.logger.warning("on_device_data: port %s not in devices", port)
            return

        dev = self.devices[port]

        # Handle stimulus state updates
        if data_type == 'stimulus' or data.get('event') == 'stimulus':
            state = data.get('state', data.get('value'))
            self.logger.debug("Stimulus update: state=%s, plot=%s, running=%s", state, dev.get('plot'), self._running)
            if state is not None and dev.get('plot'):
                try:
                    plot = dev['plot']
                    self.logger.debug("Calling state_update: recording=%s, run=%s", plot.recording, plot.run)
                    plot.state_update(port, int(state))
                except (ValueError, TypeError) as e:
                    self.logger.error("state_update failed: %s", e)

        # Handle trial data updates
        elif data_type == 'data' or data.get('event') == 'data':
            trial = data.get('trial_number')
            opened = data.get('shutter_open')
            closed = data.get('shutter_closed')

            if trial is not None:
                dev['trl_n'].set(str(trial))
            if opened is not None:
                dev['tsot'].set(str(opened))
                if dev.get('plot'):
                    dev['plot'].tsot_update(port, int(opened))
            if closed is not None:
                dev['tsct'].set(str(closed))
                if dev.get('plot'):
                    dev['plot'].tsct_update(port, int(closed))

        # Handle config responses
        elif data_type == 'config' or data.get('event') == 'config':
            if self._config_dialog:
                # wVOG sends config dict with parsed values
                config_dict = data.get('config')
                if config_dict and isinstance(config_dict, dict):
                    # Map wVOG keys to config dialog keys
                    key_map = {
                        'open_time': 'configMaxOpen',
                        'opn': 'configMaxOpen',
                        'close_time': 'configMaxClose',
                        'cls': 'configMaxClose',
                        'debounce': 'configDebounce',
                        'dbc': 'configDebounce',
                        'experiment_type': 'configName',
                        'typ': 'configName',
                    }
                    for wvog_key, dialog_key in key_map.items():
                        if wvog_key in config_dict:
                            self._config_dialog.update_fields(dialog_key, str(config_dict[wvog_key]))
                    # wVOG doesn't report firmware version, use device type
                    self._config_dialog.update_fields('deviceVer', 'wVOG')
                else:
                    # sVOG sends keyword|value responses
                    keyword = data.get('keyword')
                    value = data.get('value')
                    if keyword and value is not None:
                        self._config_dialog.update_fields(keyword, str(value))

        # Handle version responses (also populate config dialog)
        elif data_type == 'version' or data.get('event') == 'version':
            if self._config_dialog:
                keyword = data.get('keyword')
                value = data.get('value')
                if keyword and value is not None:
                    self._config_dialog.update_fields(keyword, str(value))

    # ------------------------------------------------------------------
    # Recording state management (matches DRT pattern)

    def sync_recording_state(self):
        """Sync recording state with system - enable/disable controls."""
        recording = getattr(self.system, 'recording', False)
        self._running = recording
        self._sync_plotter_recording_state()
        self._sync_control_states()

    def _sync_plotter_recording_state(self) -> None:
        """Sync plotter recording state with system recording state."""
        recording = bool(getattr(self.system, 'recording', False))
        self.logger.info("_sync_plotter_recording_state: recording=%s, prev=%s, devices=%s",
                         recording, self._plot_recording_state, list(self.devices.keys()))
        if self._plot_recording_state == recording:
            self.logger.debug("  Recording state unchanged, skipping")
            return
        self._plot_recording_state = recording

        for port, dev in self.devices.items():
            plotter = dev.get('plot')
            self.logger.info("  Port %s: plotter=%s", port, plotter)
            if not plotter:
                continue
            if recording:
                self.logger.info("  Calling plotter.start_recording() for %s", port)
                plotter.start_recording()
                self.logger.info("  After start_recording: run=%s, recording=%s, session_active=%s",
                                 plotter.run, plotter.recording, plotter._session_active)
            else:
                self.logger.info("  Calling plotter.stop_recording() for %s", port)
                plotter.stop_recording()

    def _sync_control_states(self):
        """Enable/disable controls based on recording state."""
        recording = getattr(self.system, 'recording', False)
        state = 'disabled' if recording else 'normal'

        for port, dev in self.devices.items():
            if dev.get('stm_on'):
                dev['stm_on'].configure(state=state)
            if dev.get('stm_off'):
                dev['stm_off'].configure(state=state)
            if dev.get('configure'):
                dev['configure'].configure(state=state)

    def handle_session_started(self) -> None:
        """Handle session start (Start button) - clear and start plotters."""
        self._plot_recording_state = None
        self._session_active = True
        for port, dev in self.devices.items():
            plotter = dev.get('plot')
            if plotter:
                plotter.start_session()
            # Reset results
            dev['trl_n'].set('0')
            dev['tsot'].set('0')
            dev['tsct'].set('0')

    def handle_session_stopped(self) -> None:
        """Handle session stop (Stop button) - freeze plotters completely."""
        self._plot_recording_state = None
        self._session_active = False
        for port, dev in self.devices.items():
            plotter = dev.get('plot')
            if plotter:
                plotter.stop()

    # ------------------------------------------------------------------
    # Button callbacks

    def _get_active_port(self) -> Optional[str]:
        """Get the port of the currently selected tab."""
        if not self._notebook or not self.devices:
            return None

        try:
            current_tab = self._notebook.select()
            if current_tab:
                tab_text = self._notebook.tab(current_tab, 'text')
                # Find port by matching tab text
                for port in self.devices:
                    short_port = port.split('/')[-1]
                    if short_port in tab_text:
                        return port
        except Exception:
            pass

        # Fallback: return first device
        return next(iter(self.devices), None)

    def _on_lens_clear(self):
        """Handle lens clear/open button click."""
        if self._action_callback and self.async_bridge:
            self.async_bridge.run_coroutine(self._action_callback("peek_open"))

    def _on_lens_opaque(self):
        """Handle lens opaque/close button click."""
        if self._action_callback and self.async_bridge:
            self.async_bridge.run_coroutine(self._action_callback("peek_close"))

    def _on_configure_clicked(self, port: str):
        """Handle configure button click - show config dialog."""
        if VOGConfigDialog is None:
            self.logger.warning("Configuration dialog not available")
            return

        if self._config_dialog is None:
            self._config_dialog = VOGConfigDialog(action_callback=self._dispatch_config_action)

        root = getattr(self._notebook, 'winfo_toplevel', lambda: None)()
        self._config_dialog.show(port, parent=root)

        # Request current config from device (pass port to get config for specific device)
        if self._action_callback and self.async_bridge:
            self.async_bridge.run_coroutine(self._action_callback("get_config", port=port))

    async def _dispatch_config_action(self, action: str, data: Dict):
        """Handle config dialog actions."""
        if not self._action_callback:
            return
        # Forward as a combined action
        await self._action_callback(f"config_{action}")

    # ------------------------------------------------------------------
    # UI helpers

    def handle_window_close(self):
        """Handle window close event."""
        # Stop recording and session
        self._running = False
        self._session_active = False
        self._plot_recording_state = None
        # Stop all plotters
        for dev in self.devices.values():
            plotter = dev.get('plot')
            if plotter:
                plotter.stop()

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

    def _build_embedded_gui(self, parent) -> Optional[Any]:
        if not HAS_TK:
            self.logger.warning("Tkinter unavailable; cannot mount VOG GUI")
            return None

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
        return container

    def bind_runtime(self, runtime) -> None:
        """Allow the runtime to expose its API to the GUI once ready."""
        self._runtime = runtime
        if not self.gui:
            return
        self.gui.system = runtime
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

    def on_device_disconnected(self, port: str) -> None:
        if not self.gui:
            return
        self.call_in_gui(self.gui.on_device_disconnected, port)

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
