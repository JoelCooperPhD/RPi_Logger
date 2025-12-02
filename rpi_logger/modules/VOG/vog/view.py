"""VOG view factory for VMC integration."""

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
except Exception:
    tk = None
    ttk = None

ActionCallback = Optional[Callable[[str], Awaitable[None]]]


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
    """Tkinter GUI variant for VOG that forwards controls via the stub controller."""

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
        self.device_tabs: Dict[str, Any] = {}

        # Create UI
        if embedded_parent:
            self.root = embedded_parent
            self._build_ui(embedded_parent)
        else:
            self.root = None

    def _build_ui(self, parent):
        """Build the embedded UI."""
        # Status label
        self.status_label = ttk.Label(
            parent,
            text="VOG Module - Waiting for devices...",
            padding=10
        )
        self.status_label.pack(fill=tk.X)

        # Device notebook
        self.notebook = ttk.Notebook(parent)
        self.notebook.pack(expand=True, fill=tk.BOTH, padx=5, pady=5)

    def on_device_connected(self, port: str):
        """Handle device connection."""
        self.logger.info("Device connected: %s", port)

        if not hasattr(self, 'notebook'):
            return

        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text=port.split('/')[-1])

        # Simple device info
        label = ttk.Label(frame, text=f"sVOG Device: {port}", padding=20)
        label.pack(expand=True)

        # Peek buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(pady=10)

        peek_open_btn = ttk.Button(
            btn_frame,
            text="Peek Open",
            command=lambda: self._on_peek_open()
        )
        peek_open_btn.pack(side=tk.LEFT, padx=5)

        peek_close_btn = ttk.Button(
            btn_frame,
            text="Peek Close",
            command=lambda: self._on_peek_close()
        )
        peek_close_btn.pack(side=tk.LEFT, padx=5)

        self.device_tabs[port] = frame
        self._update_status()

    def on_device_disconnected(self, port: str):
        """Handle device disconnection."""
        self.logger.info("Device disconnected: %s", port)

        if port in self.device_tabs and hasattr(self, 'notebook'):
            tab = self.device_tabs.pop(port)
            try:
                tab_id = self.notebook.index(tab)
                self.notebook.forget(tab_id)
            except Exception:
                pass

        self._update_status()

    def on_device_data(self, port: str, data_type: str, data: Dict[str, Any]):
        """Handle data from device."""
        self.logger.debug("Data from %s: %s - %s", port, data_type, data)

    def sync_recording_state(self):
        """Sync recording state with system."""
        pass

    def handle_window_close(self):
        """Handle window close event."""
        pass

    def _update_status(self):
        """Update status label."""
        if not hasattr(self, 'status_label'):
            return
        device_count = len(self.device_tabs)
        if device_count == 0:
            self.status_label.config(text="VOG Module - Waiting for devices...")
        else:
            self.status_label.config(text=f"VOG Module - {device_count} device(s) connected")

    def _on_peek_open(self):
        """Handle peek open button."""
        if self._action_callback and self.async_bridge:
            self.async_bridge.run_coroutine(self._action_callback("peek_open"))

    def _on_peek_close(self):
        """Handle peek close button."""
        if self._action_callback and self.async_bridge:
            self.async_bridge.run_coroutine(self._action_callback("peek_close"))


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
        if tk is None:
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
        if tk is None:
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

    def on_device_connected(self, port: str) -> None:
        if not self.gui:
            return
        self.call_in_gui(self.gui.on_device_connected, port)

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

    async def _dispatch_action(self, action: str) -> None:
        if not self.action_callback:
            return
        await self.action_callback(action)

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
        else:
            self._active_session_dir = None
            if not self._session_visual_active:
                return
            self._session_visual_active = False
