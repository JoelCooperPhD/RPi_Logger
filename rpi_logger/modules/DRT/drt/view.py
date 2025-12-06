"""DRT view factory for VMC integration.

Implements the modern DRT GUI pattern with real-time matplotlib plotting
for single-device support, following the VOG module architecture.
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
    from ..drt_core.interfaces.gui.drt_plotter import DRTPlotter
    HAS_MATPLOTLIB = True
except ImportError:
    try:
        from rpi_logger.modules.DRT.drt_core.interfaces.gui.drt_plotter import DRTPlotter
        HAS_MATPLOTLIB = True
    except ImportError:
        DRTPlotter = None
        HAS_MATPLOTLIB = False

try:
    from ..drt_core.interfaces.gui.drt_config_window import DRTConfigWindow
except ImportError:
    try:
        from rpi_logger.modules.DRT.drt_core.interfaces.gui.drt_config_window import DRTConfigWindow
    except ImportError:
        DRTConfigWindow = None

try:
    from ..drt_core.device_types import DRTDeviceType
except ImportError:
    from rpi_logger.modules.DRT.drt_core.device_types import DRTDeviceType

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

    def get_device_type(self, device_id: str):
        return None

    @property
    def xbee_connected(self) -> bool:
        return False

    async def rescan_xbee_network(self) -> None:
        pass


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


class DRTTkinterGUI:
    """Tkinter GUI for DRT with real-time plotting.

    Key features:
    - Real-time matplotlib plotting of stimulus state and reaction times
    - Results display (trial number, reaction time, click count)
    - Configuration dialog for device settings
    - Single device display (no tabs)
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
        self.logger = ensure_structured_logger(logger, fallback_name="DRTTkinterGUI") if logger else get_module_logger("DRTTkinterGUI")
        self.async_bridge: Optional[_LoopAsyncBridge] = None

        # Single device state
        self._port: Optional[str] = None
        self._device_type: DRTDeviceType = DRTDeviceType.SDRT
        self._plotter: Optional[DRTPlotter] = None

        # Results display variables
        self._trial_n: Optional[tk.StringVar] = None
        self._rt_var: Optional[tk.StringVar] = None
        self._click_count: Optional[tk.StringVar] = None
        self._battery_var: Optional[tk.StringVar] = None

        # Control buttons
        self._stm_on: Optional[Any] = None
        self._stm_off: Optional[Any] = None
        self._configure_btn: Optional[Any] = None

        # Session and recording state
        self._session_active = False
        self._running = False
        self._plot_recording_state: Optional[bool] = None

        # Stimulus state tracking
        self._stimulus_state: int = 0

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
        self.logger.info("=== DRTTkinterGUI._build_ui STARTING ===")
        self.logger.info("Parent widget: %s", parent)

        try:
            # Main frame
            self._frame = ttk.Frame(parent)
            self._frame.pack(fill=tk.BOTH, expand=True)
            self._frame.columnconfigure(0, weight=1)
            self._frame.rowconfigure(0, weight=1)
            self.logger.info("Created main frame: %s", self._frame)

            # Content frame
            self._content_frame = ttk.Frame(self._frame)
            self._content_frame.grid(row=0, column=0, sticky="NSEW")
            self._content_frame.columnconfigure(0, weight=1)
            self._content_frame.rowconfigure(0, weight=1)
            self.logger.info("Created content frame: %s", self._content_frame)

            # Build device UI immediately with default device type
            self._build_device_ui(None, DRTDeviceType.SDRT)
            self.logger.info("=== DRTTkinterGUI._build_ui COMPLETED ===")
        except Exception as e:
            self.logger.error("=== DRTTkinterGUI._build_ui FAILED: %s ===", e, exc_info=True)

    def _build_device_ui(self, port: Optional[str], device_type: DRTDeviceType):
        """Build UI components for the device.

        Args:
            port: Device port, or None if no device connected yet
            device_type: Device type enum
        """
        if not self._content_frame:
            return

        self._device_type = device_type
        type_str = device_type.value if hasattr(device_type, 'value') else str(device_type)

        # Add plotter (left side)
        if HAS_MATPLOTLIB and DRTPlotter is not None:
            try:
                self._plotter = DRTPlotter(self._content_frame, title="DRT - Detection Response Task")
                if port:
                    self._plotter.add_device(port)
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
        self._add_results(self._controls_panel, device_type)

        # Add configure button
        self._add_configure_button(self._controls_panel)

        # Disable configure button if no device connected yet
        if port is None and self._configure_btn:
            self._configure_btn.configure(state='disabled')

    def _add_manual_controls(self, parent: tk.Widget, device_type: DRTDeviceType):
        """Add stimulus control buttons."""
        lf = ttk.LabelFrame(parent, text="Stimulus")
        lf.grid(row=0, column=0, sticky="NEW", padx=4, pady=(4, 2))
        lf.grid_columnconfigure(0, weight=1)
        lf.grid_columnconfigure(1, weight=1)

        # Use RoundedButton if available, otherwise fall back to ttk.Button
        if RoundedButton is not None:
            btn_bg = Colors.BG_FRAME if Colors is not None else None
            self._stm_on = RoundedButton(lf, text="ON", command=self._on_stimulus_on,
                                         width=80, height=32, style='default', bg=btn_bg)
            self._stm_on.grid(row=0, column=0, padx=2, pady=2)

            self._stm_off = RoundedButton(lf, text="OFF", command=self._on_stimulus_off,
                                          width=80, height=32, style='default', bg=btn_bg)
            self._stm_off.grid(row=0, column=1, padx=2, pady=2)
        else:
            self._stm_on = ttk.Button(lf, text="ON", command=self._on_stimulus_on)
            self._stm_on.grid(row=0, column=0, sticky="NEWS", padx=2, pady=2)

            self._stm_off = ttk.Button(lf, text="OFF", command=self._on_stimulus_off)
            self._stm_off.grid(row=0, column=1, sticky="NEWS", padx=2, pady=2)

    def _add_results(self, parent: tk.Widget, device_type: DRTDeviceType):
        """Add results display (trial number, reaction time, click count)."""
        lf = ttk.LabelFrame(parent, text="Results")
        lf.grid(row=2, column=0, sticky="NEW", padx=4, pady=2)
        lf.grid_columnconfigure(1, weight=1)

        # Trial Number
        self._trial_n = tk.StringVar(value="0")
        ttk.Label(lf, text="Trial Number:", style='Inframe.TLabel').grid(row=0, column=0, sticky="W", padx=5)
        ttk.Label(lf, textvariable=self._trial_n, style='Inframe.TLabel').grid(row=0, column=1, sticky="E", padx=5)

        # Reaction Time
        self._rt_var = tk.StringVar(value="-")
        ttk.Label(lf, text="Reaction Time:", style='Inframe.TLabel').grid(row=1, column=0, sticky="W", padx=5)
        ttk.Label(lf, textvariable=self._rt_var, style='Inframe.TLabel').grid(row=1, column=1, sticky="E", padx=5)

        # Response Count
        self._click_count = tk.StringVar(value="0")
        ttk.Label(lf, text="Response Count:", style='Inframe.TLabel').grid(row=2, column=0, sticky="W", padx=5)
        ttk.Label(lf, textvariable=self._click_count, style='Inframe.TLabel').grid(row=2, column=1, sticky="E", padx=5)

        # Battery display for wDRT devices
        if device_type in (DRTDeviceType.WDRT_USB, DRTDeviceType.WDRT_WIRELESS):
            self._battery_var = tk.StringVar(value="---%")
            ttk.Label(lf, text="Battery:", style='Inframe.TLabel').grid(row=3, column=0, sticky="W", padx=5)
            ttk.Label(lf, textvariable=self._battery_var, style='Inframe.TLabel').grid(row=3, column=1, sticky="E", padx=5)

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

    def on_device_connected(self, port: str, device_type: DRTDeviceType = None):
        """Handle device connection - update port and enable configure button."""
        if device_type is None:
            device_type = DRTDeviceType.SDRT

        type_str = device_type.value if hasattr(device_type, 'value') else str(device_type)
        self.logger.info("%s device connected: %s", type_str, port)

        if self._port is not None:
            self.logger.warning("Device already connected at %s, ignoring new connection at %s", self._port, port)
            return

        self._port = port
        self._device_type = device_type

        # Update window title with device info
        self._update_window_title()

        # Add device to plotter if it exists
        if self._plotter:
            self._plotter.add_device(port)

        # Enable configure button now that device is connected
        if self._configure_btn:
            self._configure_btn.configure(state='normal')

    def on_device_disconnected(self, port: str, device_type: DRTDeviceType = None):
        """Handle device disconnection - clean up UI."""
        self.logger.info("Device disconnected: %s", port)

        if self._port != port:
            return

        # Clean up plotter
        if self._plotter:
            try:
                self._plotter.remove_device(port)
            except Exception:
                pass

        # Reset state
        self._port = None
        self._device_type = None

        # Disable configure button
        if self._configure_btn:
            self._configure_btn.configure(state='disabled')

        # Reset window title
        self._update_window_title()

        # Reset results
        if self._trial_n:
            self._trial_n.set("0")
        if self._rt_var:
            self._rt_var.set("-")
        if self._click_count:
            self._click_count.set("0")
        if self._battery_var:
            self._battery_var.set("---%")

    def _update_window_title(self) -> None:
        """Update window title based on connected device."""
        if not self.root:
            return

        try:
            toplevel = self.root.winfo_toplevel()
            if self._port and self._device_type:
                # Format: "DRT - USB:ACM0" or "DRT - Wireless:ACM0"
                # Extract short port name (e.g., "ACM0" from "/dev/ttyACM0")
                port_short = self._port
                if '/' in port_short:
                    port_short = port_short.split('/')[-1]
                if port_short.startswith('tty'):
                    port_short = port_short[3:]

                # Determine connection type from device_type
                device_type_str = self._device_type.value if hasattr(self._device_type, 'value') else str(self._device_type)
                device_type_lower = device_type_str.lower()
                if 'wireless' in device_type_lower:
                    conn_type = "Wireless"
                else:
                    conn_type = "USB"

                title = f"DRT - {conn_type}:{port_short}"
            else:
                title = "DRT"

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
        if data_type == 'stimulus':
            state_val = data.get('state', data.get('value', ''))
            try:
                if isinstance(state_val, bool):
                    state = 1 if state_val else 0
                elif isinstance(state_val, int):
                    state = state_val
                else:
                    state = int(state_val)
                self._stimulus_state = state
                if self._plotter:
                    self._plotter.update_stimulus_state(port, state)
            except (ValueError, TypeError):
                pass

        # Handle trial data updates
        elif data_type == 'trial' or data_type == 'data':
            trial_num = data.get('trial_number')
            rt = data.get('reaction_time')
            clicks = data.get('clicks', data.get('count'))
            battery = data.get('battery')

            if trial_num is not None and self._trial_n:
                self._trial_n.set(str(trial_num))
            if clicks is not None and self._click_count:
                self._click_count.set(str(clicks))
            if rt is not None:
                if self._rt_var:
                    if rt >= 0:
                        self._rt_var.set(f"{rt:.0f}")
                    else:
                        self._rt_var.set("Miss")
                if self._plotter:
                    is_hit = rt >= 0
                    self._plotter.update_trial(port, abs(rt), is_hit=is_hit)
            if battery is not None and self._battery_var:
                self._battery_var.set(f"{int(battery)}%")

        # Handle click count updates
        elif data_type == 'click':
            value = data.get('count', data.get('value', ''))
            if value and self._click_count:
                try:
                    self._click_count.set(str(int(value)))
                except (ValueError, TypeError):
                    pass

        # Handle battery updates
        elif data_type == 'battery':
            percent = data.get('percent')
            if percent is not None and self._battery_var:
                self._battery_var.set(f"{int(percent)}%")

        # Handle reaction time updates
        elif data_type == 'reaction_time':
            rt = data.get('reaction_time')
            if rt is not None and self._rt_var:
                if rt >= 0:
                    self._rt_var.set(f"{rt:.0f}")
                else:
                    self._rt_var.set("Miss")

    def on_xbee_dongle_status_change(self, status: str, detail: str) -> None:
        """Handle XBee dongle status changes (placeholder for compatibility)."""
        self.logger.info("XBee dongle status: %s %s", status, detail)

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
        if self._trial_n:
            self._trial_n.set('0')
        if self._rt_var:
            self._rt_var.set('-')
        if self._click_count:
            self._click_count.set('0')

    def handle_session_stopped(self) -> None:
        """Handle session stop (Stop button) - freeze plotter completely."""
        self._plot_recording_state = None
        self._session_active = False
        if self._plotter:
            self._plotter.stop()

    # ------------------------------------------------------------------
    # Button callbacks

    def _on_stimulus_on(self):
        """Handle stimulus ON button click."""
        if self._port is None:
            return
        handler = self.system.get_device_handler(self._port)
        if handler and self.async_bridge:
            self.async_bridge.run_coroutine(handler.set_stimulus(True))
            self._stimulus_state = 1
            if self._plotter:
                self._plotter.update_stimulus_state(self._port, 1)

    def _on_stimulus_off(self):
        """Handle stimulus OFF button click."""
        if self._port is None:
            return
        handler = self.system.get_device_handler(self._port)
        if handler and self.async_bridge:
            self.async_bridge.run_coroutine(handler.set_stimulus(False))
            self._stimulus_state = 0
            if self._plotter:
                self._plotter.update_stimulus_state(self._port, 0)

    def _on_configure_clicked(self):
        """Handle configure button click - show config dialog."""
        self.logger.info("Configure button clicked for port: %s", self._port)

        if self._port is None:
            self.logger.warning("No device connected - cannot configure")
            return

        if DRTConfigWindow is None:
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
            self.logger.warning("System not available for configuration")
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
            DRTConfigWindow(
                root,
                self._port,
                device_type=self._device_type,
                on_upload=lambda params: self._on_config_upload(params),
                on_iso_preset=lambda: self._on_config_iso(),
                on_get_config=lambda: self._on_config_get(),
            )
        except Exception as e:
            self.logger.error("Failed to create config window: %s", e, exc_info=True)

    def _on_config_upload(self, params: Dict[str, int]):
        """Handle config upload."""
        handler = self.system.get_device_handler(self._port)
        if handler and self.async_bridge:
            if self._device_type == DRTDeviceType.SDRT:
                self.async_bridge.run_coroutine(self._upload_sdrt_config(handler, params))
            else:
                self.async_bridge.run_coroutine(handler.send_command('set', params))

    async def _upload_sdrt_config(self, handler, params: Dict[str, int]) -> None:
        """Upload config to sDRT device using individual commands."""
        try:
            if 'lowerISI' in params:
                value = params['lowerISI']
                if value < 0:
                    self.logger.warning("Invalid lowerISI value: %d, skipping", value)
                else:
                    await handler.set_lower_isi(value)
            if 'upperISI' in params:
                value = params['upperISI']
                if value < 0:
                    self.logger.warning("Invalid upperISI value: %d, skipping", value)
                else:
                    await handler.set_upper_isi(value)
            if 'stimDur' in params:
                value = params['stimDur']
                if value < 0:
                    self.logger.warning("Invalid stimDur value: %d, skipping", value)
                else:
                    await handler.set_stim_duration(value)
            if 'intensity' in params:
                value = params['intensity']
                if not (0 <= value <= 100):
                    self.logger.warning("Invalid intensity value: %d, must be 0-100, skipping", value)
                else:
                    intensity = int(value * 2.55)
                    await handler.set_intensity(intensity)
            self.logger.info("sDRT config uploaded successfully")
        except Exception as e:
            self.logger.error("Failed to upload sDRT config: %s", e, exc_info=True)

    def _on_config_iso(self):
        """Handle ISO preset."""
        handler = self.system.get_device_handler(self._port)
        if handler and self.async_bridge:
            if self._device_type == DRTDeviceType.SDRT:
                self.async_bridge.run_coroutine(handler.set_iso_params())
            else:
                self.async_bridge.run_coroutine(handler.send_command('iso'))

    def _on_config_get(self):
        """Handle get config."""
        handler = self.system.get_device_handler(self._port)
        if handler and self.async_bridge:
            self.async_bridge.run_coroutine(handler.get_config())

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
        """Show the DRT frame."""
        if self._frame:
            self._frame.pack(fill=tk.BOTH, expand=True)

    def hide(self):
        """Hide the DRT frame."""
        if self._frame:
            self._frame.pack_forget()


class DRTView:
    """Adapter that exposes the DRT GUI through the stub supervisor interface."""

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
        self.display_name = display_name or "DRT"
        self.logger = ensure_structured_logger(logger, fallback_name="DRTView") if logger else get_module_logger("DRTView")
        stub_logger = self.logger.getChild("Stub")
        self._stub_view = StubCodexView(
            args,
            model,
            action_callback=action_callback,
            display_name=self.display_name,
            logger=stub_logger,
        )
        self._bridge = LegacyTkViewBridge(self._stub_view, logger=self.logger.getChild("Bridge"))
        self.gui: Optional[DRTTkinterGUI] = None
        self._runtime = None
        self._initial_session_dir: Optional[Path] = None
        self._active_session_dir: Optional[Path] = None
        self._session_visual_active = False

        self._bridge.mount(self._build_embedded_gui)
        self._stub_view.set_preview_title("DRT Controls")
        self.model.subscribe(self._on_model_change)

    def _build_embedded_gui(self, parent) -> Optional[Any]:
        self.logger.info("=== DRTView._build_embedded_gui STARTING ===")
        self.logger.info("HAS_TK=%s, HAS_THEME=%s, HAS_MATPLOTLIB=%s", HAS_TK, HAS_THEME, HAS_MATPLOTLIB)

        if not HAS_TK:
            self.logger.warning("Tkinter unavailable; cannot mount DRT GUI")
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

        gui = DRTTkinterGUI(
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

        self.logger.info("=== DRTView._build_embedded_gui COMPLETED ===")
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

    def on_device_connected(self, device_id: str, device_type: DRTDeviceType = None) -> None:
        if not self.gui:
            return
        self.call_in_gui(self.gui.on_device_connected, device_id, device_type)

    def on_device_disconnected(self, device_id: str, device_type: DRTDeviceType = None) -> None:
        if not self.gui:
            return
        self.call_in_gui(self.gui.on_device_disconnected, device_id, device_type)

    def on_device_data(self, port: str, data_type: str, payload: Dict[str, Any]) -> None:
        if not self.gui:
            return
        self.call_in_gui(self.gui.on_device_data, port, data_type, payload)

    def on_xbee_dongle_status_change(self, status: str, detail: str) -> None:
        """Handle XBee dongle status changes."""
        self.logger.info("View: XBee dongle status change: %s %s", status, detail)
        if not self.gui:
            return
        self.call_in_gui(self.gui.on_xbee_dongle_status_change, status, detail)

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
