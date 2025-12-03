"""Tkinter view adapter that reuses the legacy DRT GUI inside the stub framework."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

from rpi_logger.core.logging_utils import ensure_structured_logger, get_module_logger
from vmc import LegacyTkViewBridge, StubCodexView

try:
    import tkinter as tk  # type: ignore
    from tkinter import ttk  # type: ignore
except Exception:  # pragma: no cover - tkinter unavailable in headless tests
    tk = None  # type: ignore
    ttk = None  # type: ignore

from rpi_logger.modules.DRT.drt_core.interfaces.gui.quick_status_panel import QuickStatusPanel
from rpi_logger.modules.DRT.drt_core.interfaces.gui.tkinter_gui import TkinterGUI
from rpi_logger.modules.DRT.drt_core.device_types import DRTDeviceType

ActionCallback = Optional[Callable[[str], Awaitable[None]]]


class _SystemPlaceholder:
    """Minimal stand-in until the runtime is bound to the GUI."""

    recording: bool = False
    trial_label: str = ""

    def __init__(self, args=None):
        self.config = getattr(args, 'config', {})
        self.config_file_path = getattr(args, 'config_file_path', None)

    async def start_recording(self) -> bool:  # pragma: no cover - never called directly
        return False

    async def stop_recording(self) -> bool:  # pragma: no cover - never called directly
        return False

    def get_device_handler(self, port: str):  # pragma: no cover - runtime replaces this
        return None


class _LoopAsyncBridge:
    """Lightweight bridge that schedules coroutines on the active asyncio loop."""

    def __init__(self) -> None:
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._logger = logging.getLogger(__name__ + "._LoopAsyncBridge")

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Remember the supervising loop so Tk callbacks can reuse it."""
        self.loop = loop
        self._logger.info(f"Async bridge bound to loop: {loop}")

    def run_coroutine(self, coro):
        """Schedule a coroutine to run on the bound event loop (thread-safe)."""
        loop = self._resolve_loop()
        self._logger.info(f"Scheduling coroutine on loop (loop running: {loop.is_running()})")
        # Use call_soon_threadsafe to schedule from Tk thread to asyncio thread
        loop.call_soon_threadsafe(lambda: loop.create_task(coro))

    def _resolve_loop(self) -> asyncio.AbstractEventLoop:
        if self.loop and not self.loop.is_closed():
            return self.loop
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError as exc:  # pragma: no cover - Tk thread without bound loop
            raise RuntimeError("Tkinter bridge has no running event loop bound") from exc
        self.loop = loop
        return loop


class DRTTkinterGUI(TkinterGUI):
    """Tkinter GUI variant that forwards recording controls via the stub controller."""

    def __init__(
        self,
        args,
        action_callback: ActionCallback,
        logger: Optional[logging.Logger] = None,
        embedded_parent: Optional["tk.Widget"] = None,
        quick_panel: Optional[QuickStatusPanel] = None,
    ):
        self._action_callback = action_callback
        self._plot_recording_state: Optional[bool] = None
        self.logger = ensure_structured_logger(logger, fallback_name="DRTTkinterGUI") if logger else get_module_logger("DRTTkinterGUI")
        super().__init__(_SystemPlaceholder(args), args, master=embedded_parent, quick_panel=quick_panel)

    async def _start_recording_async(self):  # type: ignore[override]
        if not self._action_callback:
            self.logger.error("Start recording requested before action callback ready")
            return
        await self._action_callback("start_recording")

    async def _stop_recording_async(self):  # type: ignore[override]
        if not self._action_callback:
            self.logger.error("Stop recording requested before action callback ready")
            return
        await self._action_callback("stop_recording")

    def sync_recording_state(self):  # type: ignore[override]
        super().sync_recording_state()
        self._sync_plotter_recording_state()

    def _sync_plotter_recording_state(self) -> None:
        recording = bool(getattr(self.system, "recording", False))
        if self._plot_recording_state == recording:
            return
        self._plot_recording_state = recording

        for tab in getattr(self, "device_tabs", {}).values():
            plotter = getattr(tab, "plotter", None)
            if not plotter:
                continue
            if recording:
                plotter.start_recording()
            else:
                plotter.stop_recording()

    def handle_session_started(self) -> None:
        self._plot_recording_state = None
        for tab in getattr(self, "device_tabs", {}).values():
            plotter = getattr(tab, "plotter", None)
            if plotter:
                plotter.start_session()

    def handle_session_stopped(self) -> None:
        self._plot_recording_state = None
        for tab in getattr(self, "device_tabs", {}).values():
            plotter = getattr(tab, "plotter", None)
            if plotter:
                plotter.stop()


class DRTView:
    """Adapter that exposes the legacy GUI through the stub supervisor interface."""

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
        self.quick_panel: Optional[QuickStatusPanel] = None
        self._runtime = None
        self._initial_session_dir: Optional[Path] = None
        self._active_session_dir: Optional[Path] = None
        self._session_visual_active = False

        self._init_quick_panel()
        self._bridge.mount(self._build_embedded_gui)
        self._stub_view.set_preview_title("DRT Controls")
        self.model.subscribe(self._on_model_change)

    # ------------------------------------------------------------------
    # Wiring helpers

    def _build_embedded_gui(self, parent) -> Optional[Any]:
        if tk is None:
            self.logger.warning("Tkinter unavailable; cannot mount DRT GUI")
            return None
        frame_cls = ttk.Frame if ttk is not None else tk.Frame  # type: ignore[assignment]
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
            quick_panel=self.quick_panel,
            embedded_parent=container,
        )
        gui.async_bridge = _LoopAsyncBridge()
        loop = getattr(self._stub_view, "_event_loop", None)
        if loop and isinstance(gui.async_bridge, _LoopAsyncBridge):
            gui.async_bridge.bind_loop(loop)
        self.gui = gui
        # Bind the runtime if it was set before the GUI was created
        if self._runtime:
            gui.system = self._runtime
            if isinstance(gui.async_bridge, _LoopAsyncBridge):
                runtime_loop = getattr(self._runtime, "_loop", None)
                if runtime_loop:
                    gui.async_bridge.bind_loop(runtime_loop)
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

    def attach_logging_handler(self) -> None:  # pragma: no cover - stub view wires logging
        self._stub_view.attach_logging_handler()

    def call_in_gui(self, func, *args, **kwargs) -> None:
        if tk is None:
            return
        root = getattr(self._stub_view, "root", None)
        if not root:
            return
        try:
            root.after(0, lambda: func(*args, **kwargs))
        except tk.TclError:  # pragma: no cover - Tk closing races
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

    def update_recording_state(self) -> None:
        if not self.gui:
            return
        self.call_in_gui(self.gui.sync_recording_state)

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

    def _init_quick_panel(self) -> None:
        if tk is None:
            return
        io_frame = getattr(self._stub_view, "io_view_frame", None)
        if not io_frame:
            return
        self._stub_view.set_io_stub_title("Session Output")
        panel = QuickStatusPanel(io_frame)
        panel.build(container=io_frame)
        self.quick_panel = panel
