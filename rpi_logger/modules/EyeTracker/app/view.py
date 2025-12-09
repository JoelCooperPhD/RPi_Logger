"""Neon EyeTracker view factory for VMC integration.

Implements the EyeTracker GUI following DRT/VOG patterns with:
- StubCodexView for VMC compatibility
- LegacyTkViewBridge for Tkinter integration
- Real-time video preview with gaze overlay
- Device status and recording state display
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional, TYPE_CHECKING

try:
    import tkinter as tk
    from tkinter import ttk
except Exception:
    tk = None  # type: ignore
    ttk = None  # type: ignore

try:
    from PIL import Image
except Exception:
    Image = None  # type: ignore

import numpy as np

from rpi_logger.core.logging_utils import ensure_structured_logger, get_module_logger
from vmc import LegacyTkViewBridge, StubCodexView

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

ActionCallback = Optional[Callable[..., Awaitable[None]]]
FrameProvider = Callable[[], Optional[np.ndarray]]


class _SystemPlaceholder:
    """Minimal stand-in until the runtime is bound to the GUI."""

    recording: bool = False

    def __init__(self, args=None):
        self.config = getattr(args, 'config', {})
        self.config_file_path = getattr(args, 'config_file_path', None)


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


class NeonEyeTrackerTkinterGUI:
    """Tkinter GUI for Neon EyeTracker with real-time video preview.

    Key features:
    - Real-time video preview with gaze overlay
    - Device status display (connected/disconnected)
    - Recording state indicator
    - Reconnect and configure controls
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
        self.logger = ensure_structured_logger(logger, fallback_name="NeonEyeTrackerGUI") if logger else get_module_logger("NeonEyeTrackerGUI")
        self.async_bridge: Optional[_LoopAsyncBridge] = None

        # Device state
        self._device_connected = False
        self._device_name: str = "None"
        self._recording = False

        # UI state variables
        self._status_var: Optional[tk.StringVar] = None
        self._recording_var: Optional[tk.StringVar] = None
        self._device_var: Optional[tk.StringVar] = None

        # Preview state
        self._preview_interval_ms = 100  # Default 10 Hz, overridden by view
        self._preview_after_handle: Optional[str] = None
        self._frame_provider: Optional[FrameProvider] = None
        self._canvas: Optional[tk.Canvas] = None
        self._photo_ref = None

        # Button references
        self._reconnect_btn = None
        self._configure_btn = None

        # UI references
        self.root = embedded_parent
        self._frame: Optional[tk.Frame] = None
        self._content_frame: Optional[tk.Frame] = None

        if embedded_parent:
            self._build_ui(embedded_parent)

    def _build_ui(self, parent: tk.Widget):
        """Build the embedded UI with preview canvas."""
        self.logger.info("Building NeonEyeTracker GUI")

        try:
            # Main frame
            self._frame = ttk.Frame(parent)
            self._frame.pack(fill=tk.BOTH, expand=True)
            self._frame.columnconfigure(0, weight=1)
            self._frame.rowconfigure(0, weight=1)

            # Content frame for preview
            self._content_frame = ttk.Frame(self._frame)
            self._content_frame.grid(row=0, column=0, sticky="NSEW")
            self._content_frame.columnconfigure(0, weight=1)
            self._content_frame.rowconfigure(0, weight=1)

            # Create preview canvas
            canvas_width = getattr(self.args, 'preview_width', 640) or 640
            canvas_height = getattr(self.args, 'preview_height', 480) or 480
            canvas_bg = Colors.BG_CANVAS if HAS_THEME and Colors else "#1e1e1e"

            self._canvas = tk.Canvas(
                self._content_frame,
                width=canvas_width,
                height=canvas_height,
                bg=canvas_bg
            )
            self._canvas.grid(row=0, column=0, sticky="nsew")

            # Initialize status variables
            self._status_var = tk.StringVar(value="Waiting for device...")
            self._recording_var = tk.StringVar(value="Idle")
            self._device_var = tk.StringVar(value="None")

            self.logger.info("NeonEyeTracker GUI built successfully")
        except Exception as e:
            self.logger.error("Failed to build GUI: %s", e, exc_info=True)

    def set_frame_provider(self, provider: FrameProvider) -> None:
        """Set the frame provider callback for preview updates."""
        self._frame_provider = provider

    def set_preview_interval(self, interval_ms: int) -> None:
        """Set preview update interval in milliseconds."""
        self._preview_interval_ms = max(50, interval_ms)

    def start_preview(self) -> None:
        """Start the preview update loop."""
        if self._canvas and self.root:
            self._schedule_preview()

    def _schedule_preview(self) -> None:
        """Schedule the next preview update."""
        if not self.root or not self._canvas:
            return
        self._preview_after_handle = self.root.after(
            self._preview_interval_ms,
            self._preview_tick
        )

    def _preview_tick(self) -> None:
        """Update preview canvas with latest frame."""
        if self._canvas is None:
            return

        frame = self._frame_provider() if self._frame_provider else None

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

    def stop_preview(self) -> None:
        """Stop the preview update loop."""
        if self._preview_after_handle and self.root:
            try:
                self.root.after_cancel(self._preview_after_handle)
            except tk.TclError:
                pass
            self._preview_after_handle = None

    # ------------------------------------------------------------------
    # Device state updates

    def on_device_connected(self, device_name: str) -> None:
        """Handle device connection."""
        self.logger.info("Device connected: %s", device_name)
        self._device_connected = True
        self._device_name = device_name
        if self._device_var:
            self._device_var.set(device_name or "Connected")
        if self._status_var:
            self._status_var.set("Streaming")
        self._update_button_states()

    def on_device_disconnected(self) -> None:
        """Handle device disconnection."""
        self.logger.info("Device disconnected")
        self._device_connected = False
        self._device_name = "None"
        if self._device_var:
            self._device_var.set("None")
        if self._status_var:
            self._status_var.set("Disconnected")
        self._update_button_states()

    def set_device_status(self, text: str, *, connected: bool) -> None:
        """Update device status display."""
        self._device_connected = connected
        if self._status_var:
            self._status_var.set(text)
        self._update_button_states()

    def set_device_info(self, device_name: str) -> None:
        """Update device name display."""
        self._device_name = device_name or "None"
        if self._device_var:
            self._device_var.set(self._device_name)

    def set_recording_state(self, active: bool) -> None:
        """Update recording state display."""
        self._recording = active
        if self._recording_var:
            self._recording_var.set("Recording" if active else "Idle")

    def _update_button_states(self) -> None:
        """Enable/disable buttons based on device state."""
        state = 'normal' if self._device_connected else 'disabled'
        if self._configure_btn:
            try:
                self._configure_btn.configure(state=state)
            except tk.TclError:
                pass

    # ------------------------------------------------------------------
    # Button callbacks

    def _on_reconnect_clicked(self) -> None:
        """Handle reconnect button click."""
        if hasattr(self.system, 'request_reconnect') and self.async_bridge:
            self.async_bridge.run_coroutine(self.system.request_reconnect())

    def _on_configure_clicked(self) -> None:
        """Handle configure button click."""
        self.logger.info("Configure button clicked")

        if not self.root:
            return

        try:
            from rpi_logger.modules.EyeTracker.tracker_core.interfaces.gui.config_window import EyeTrackerConfigWindow
            EyeTrackerConfigWindow(self.root, self.system)
        except ImportError as e:
            self.logger.warning("Config window not available: %s", e)
        except Exception as e:
            self.logger.error("Failed to create config window: %s", e, exc_info=True)

    # ------------------------------------------------------------------
    # Lifecycle

    def handle_window_close(self) -> None:
        """Handle window close event."""
        self.stop_preview()


class NeonEyeTrackerView:
    """Adapter that exposes the Neon EyeTracker GUI through the VMC supervisor interface.

    Follows DRT/VOG patterns for:
    - StubCodexView integration
    - LegacyTkViewBridge mounting
    - Runtime binding
    - Model observation
    """

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
        self.display_name = display_name or "EyeTracker-Neon"
        self.logger = ensure_structured_logger(logger, fallback_name="NeonEyeTrackerView") if logger else get_module_logger("NeonEyeTrackerView")

        stub_logger = self.logger.getChild("Stub")
        self._stub_view = StubCodexView(
            args,
            model,
            action_callback=action_callback,
            display_name=self.display_name,
            logger=stub_logger,
        )
        self._bridge = LegacyTkViewBridge(self._stub_view, logger=self.logger.getChild("Bridge"))
        self.gui: Optional[NeonEyeTrackerTkinterGUI] = None
        self._runtime: Optional["EyeTrackerRuntime"] = None

        self._bridge.mount(self._build_embedded_gui)
        self._stub_view.set_preview_title("Preview")
        self.model.subscribe(self._on_model_change)
        self._override_help_menu()

    def _build_embedded_gui(self, parent) -> Optional[Any]:
        """Build the embedded GUI within the VMC container."""
        self.logger.info("Building NeonEyeTracker embedded GUI")

        # Apply theme to root window
        try:
            root = parent.winfo_toplevel()
            if HAS_THEME and Theme is not None:
                Theme.apply(root)
        except Exception as e:
            self.logger.debug("Could not apply theme: %s", e)

        if hasattr(parent, "columnconfigure"):
            try:
                parent.columnconfigure(0, weight=1)
                parent.rowconfigure(0, weight=1)
            except Exception:
                pass

        container = ttk.Frame(parent)
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        gui = NeonEyeTrackerTkinterGUI(
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

        # Apply pending runtime binding if bind_runtime was called before GUI created
        if self._runtime:
            gui.system = self._runtime
            self.logger.info("Applied pending runtime binding to GUI")

        # Build IO stub content (status panel)
        self._build_io_stub_content()

        self.logger.info("NeonEyeTracker embedded GUI built successfully")
        return container

    def _build_io_stub_content(self) -> None:
        """Build the status panel in the IO stub area."""
        if not self.gui:
            return

        def builder(parent: tk.Widget) -> None:
            parent.columnconfigure(0, weight=1)

            # Status LabelFrame
            status_lf = ttk.LabelFrame(parent, text="Device Status")
            status_lf.grid(row=0, column=0, sticky="new", padx=4, pady=(4, 2))
            status_lf.columnconfigure(1, weight=1)

            # Device row
            ttk.Label(status_lf, text="Device:", style='Inframe.TLabel').grid(
                row=0, column=0, sticky="w", padx=5, pady=2
            )
            ttk.Label(status_lf, textvariable=self.gui._device_var, style='Inframe.TLabel').grid(
                row=0, column=1, sticky="e", padx=5, pady=2
            )

            # Status row
            ttk.Label(status_lf, text="Status:", style='Inframe.TLabel').grid(
                row=1, column=0, sticky="w", padx=5, pady=2
            )
            ttk.Label(status_lf, textvariable=self.gui._status_var, style='Inframe.TLabel').grid(
                row=1, column=1, sticky="e", padx=5, pady=2
            )

            # Recording row
            ttk.Label(status_lf, text="Recording:", style='Inframe.TLabel').grid(
                row=2, column=0, sticky="w", padx=5, pady=2
            )
            ttk.Label(status_lf, textvariable=self.gui._recording_var, style='Inframe.TLabel').grid(
                row=2, column=1, sticky="e", padx=5, pady=2
            )

            # Controls LabelFrame
            controls_lf = ttk.LabelFrame(parent, text="Controls")
            controls_lf.grid(row=1, column=0, sticky="new", padx=4, pady=2)
            controls_lf.columnconfigure(0, weight=1)
            controls_lf.columnconfigure(1, weight=1)

            # Use RoundedButton if available
            if RoundedButton is not None and HAS_THEME and Colors is not None:
                btn_bg = Colors.BG_FRAME
                self.gui._reconnect_btn = RoundedButton(
                    controls_lf, text="Reconnect",
                    command=self.gui._on_reconnect_clicked,
                    width=80, height=32, style='default', bg=btn_bg
                )
                self.gui._reconnect_btn.grid(row=0, column=0, padx=2, pady=4)

                self.gui._configure_btn = RoundedButton(
                    controls_lf, text="Configure",
                    command=self.gui._on_configure_clicked,
                    width=80, height=32, style='default', bg=btn_bg
                )
                self.gui._configure_btn.grid(row=0, column=1, padx=2, pady=4)
                self.gui._configure_btn.configure(state='disabled')
            else:
                self.gui._reconnect_btn = ttk.Button(
                    controls_lf, text="Reconnect",
                    command=self.gui._on_reconnect_clicked
                )
                self.gui._reconnect_btn.grid(row=0, column=0, sticky="ew", padx=2, pady=4)

                self.gui._configure_btn = ttk.Button(
                    controls_lf, text="Configure",
                    command=self.gui._on_configure_clicked,
                    state='disabled'
                )
                self.gui._configure_btn.grid(row=0, column=1, sticky="ew", padx=2, pady=4)

        self._stub_view.set_io_stub_title("EyeTracker-Neon")
        self._stub_view.build_io_stub_content(builder)

    def bind_runtime(self, runtime: "EyeTrackerRuntime") -> None:
        """Bind runtime to view, enabling button callbacks and frame provider."""
        self._runtime = runtime
        if self.gui:
            self.gui.system = runtime
            self.logger.info("Runtime bound to GUI (system=%s)", type(runtime).__name__)

            # Bind async bridge loop
            if isinstance(self.gui.async_bridge, _LoopAsyncBridge):
                loop = getattr(runtime, "_loop", None)
                if loop:
                    self.gui.async_bridge.bind_loop(loop)

            # Set up frame provider
            if hasattr(runtime, '_get_latest_frame'):
                self.gui.set_frame_provider(runtime._get_latest_frame)

            # Set preview interval from config
            preview_hz = max(1, int(getattr(self.args, "gui_preview_update_hz", 10)))
            self.gui.set_preview_interval(int(1000 / preview_hz))

            # Start preview loop
            self.gui.start_preview()

    def attach_logging_handler(self) -> None:
        """Attach logging handler to stub view."""
        self._stub_view.attach_logging_handler()

    def call_in_gui(self, func, *args, **kwargs) -> None:
        """Schedule a function call in the GUI thread."""
        root = getattr(self._stub_view, "root", None)
        if not root:
            return
        try:
            root.after(0, lambda: func(*args, **kwargs))
        except tk.TclError:
            return

    # ------------------------------------------------------------------
    # Runtime-to-view notifications

    def on_device_connected(self, device_name: str) -> None:
        """Handle device connection."""
        if not self.gui:
            return
        self.call_in_gui(self.gui.on_device_connected, device_name)

    def on_device_disconnected(self) -> None:
        """Handle device disconnection."""
        if not self.gui:
            return
        self.call_in_gui(self.gui.on_device_disconnected)

    def set_device_status(self, text: str, *, connected: bool) -> None:
        """Update device status display."""
        if not self.gui:
            return
        self.call_in_gui(self.gui.set_device_status, text, connected=connected)

    def set_device_info(self, device_name: str) -> None:
        """Update device name display."""
        if not self.gui:
            return
        self.call_in_gui(self.gui.set_device_info, device_name)

    def set_recording_state(self, active: bool) -> None:
        """Update recording state display."""
        if not self.gui:
            return
        self.call_in_gui(self.gui.set_recording_state, active)

    def update_recording_state(self) -> None:
        """Sync recording state from model."""
        recording = self.model.recording if hasattr(self.model, 'recording') else False
        self.set_recording_state(recording)

    # ------------------------------------------------------------------
    # Window control

    def set_window_title(self, title: str) -> None:
        """Delegate window title changes to the stub view."""
        self._stub_view.set_window_title(title)

    # ------------------------------------------------------------------
    # Lifecycle

    async def run(self) -> float:
        """Run the view event loop."""
        return await self._stub_view.run()

    async def cleanup(self) -> None:
        """Clean up view resources."""
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
        """Return window duration from stub view."""
        return getattr(self._stub_view, "window_duration_ms", 0.0)

    @property
    def root(self):
        """Return root window from stub view."""
        return getattr(self._stub_view, "root", None)

    # ------------------------------------------------------------------
    # Help menu

    def _override_help_menu(self) -> None:
        """Replace the generic help menu with EyeTracker-specific help."""
        help_menu = getattr(self._stub_view, 'help_menu', None)
        if help_menu is None:
            return
        try:
            help_menu.delete(0)
            help_menu.add_command(label="Quick Start Guide", command=self._show_help)
        except Exception as e:
            self.logger.debug("Could not override help menu: %s", e)

    def _show_help(self) -> None:
        """Show EyeTracker-specific help dialog."""
        try:
            from rpi_logger.modules.EyeTracker.tracker_core.interfaces.gui.help_dialog import EyeTrackerHelpDialog
            root = getattr(self._stub_view, 'root', None)
            if root:
                EyeTrackerHelpDialog(root)
        except Exception as e:
            self.logger.error("Failed to show help dialog: %s", e)

    # ------------------------------------------------------------------
    # Internal helpers

    async def _dispatch_action(self, action: str, **kwargs) -> None:
        """Dispatch action callback."""
        if not self.action_callback:
            return
        await self.action_callback(action, **kwargs)

    def _on_model_change(self, prop: str, value) -> None:
        """Handle model property changes."""
        if prop == "recording":
            self.update_recording_state()
