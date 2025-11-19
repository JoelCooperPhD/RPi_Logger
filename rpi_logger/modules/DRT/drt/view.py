"""Tkinter view adapter that reuses the legacy DRT GUI inside the stub framework."""

from __future__ import annotations

import asyncio
from rpi_logger.core.logging_utils import get_module_logger
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

try:
    import tkinter as tk  # type: ignore
except Exception:  # pragma: no cover - tkinter unavailable in headless tests
    tk = None  # type: ignore

from rpi_logger.modules.DRT.drt_core.interfaces.gui.tkinter_gui import TkinterGUI

ActionCallback = Optional[Callable[[str], Awaitable[None]]]

logger = logging.getLogger(__name__)


class _SystemPlaceholder:
    """Minimal stand-in until the runtime is bound to the GUI."""

    recording: bool = False
    trial_label: str = ""

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

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Remember the supervising loop so Tk callbacks can reuse it."""
        self.loop = loop

    def run_coroutine(self, coro):
        loop = self._resolve_loop()
        return loop.create_task(coro)

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

    def __init__(self, args, action_callback: ActionCallback):
        self._action_callback = action_callback
        self._plot_recording_state: Optional[bool] = None
        super().__init__(_SystemPlaceholder(), args)

    async def _start_recording_async(self):  # type: ignore[override]
        if not self._action_callback:
            logger.error("Start recording requested before action callback ready")
            return
        await self._action_callback("start_recording")

    async def _stop_recording_async(self):  # type: ignore[override]
        if not self._action_callback:
            logger.error("Stop recording requested before action callback ready")
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
    ) -> None:
        self.args = args
        self.model = model
        self.action_callback = action_callback
        self.display_name = display_name or "DRT"
        self.logger = get_module_logger("DRTView")
        self.gui = DRTTkinterGUI(args, self._dispatch_action)
        self.gui.async_bridge = _LoopAsyncBridge()
        self.gui.set_close_handler(self._on_close)
        self._runtime = None
        self._close_requested = False
        self._window_duration_ms: float = 0.0
        self._loop_running = False
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None

        self.model.subscribe(self._on_model_change)
        self._initial_session_dir: Optional[Path] = None
        self._active_session_dir: Optional[Path] = None
        self._session_visual_active = False

    # ------------------------------------------------------------------
    # Wiring helpers

    def bind_runtime(self, runtime) -> None:
        """Allow the runtime to expose its API to the GUI once ready."""
        self._runtime = runtime
        self.gui.system = runtime
        if isinstance(self.gui.async_bridge, _LoopAsyncBridge):
            loop = getattr(runtime, "_loop", None)
            if loop:
                self.gui.async_bridge.bind_loop(loop)

    def attach_logging_handler(self) -> None:  # pragma: no cover - Tkinter widget already wires logging
        return

    def call_in_gui(self, func, *args, **kwargs) -> None:
        if tk is None or not hasattr(self.gui, 'root'):
            return
        try:
            self.gui.root.after(0, lambda: func(*args, **kwargs))
        except tk.TclError:  # pragma: no cover - Tk closing races
            return

    # ------------------------------------------------------------------
    # Runtime-to-view notifications

    def on_device_connected(self, port: str) -> None:
        self.call_in_gui(self.gui.on_device_connected, port)

    def on_device_disconnected(self, port: str) -> None:
        self.call_in_gui(self.gui.on_device_disconnected, port)

    def on_device_data(self, port: str, data_type: str, payload: Dict[str, Any]) -> None:
        self.call_in_gui(self.gui.on_device_data, port, data_type, payload)

    def update_recording_state(self) -> None:
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
            self.call_in_gui(self.gui.handle_session_started)
        else:
            self._active_session_dir = None
            if not self._session_visual_active:
                return
            self._session_visual_active = False
            self.call_in_gui(self.gui.handle_session_stopped)

    # ------------------------------------------------------------------
    # Lifecycle controls

    async def run(self) -> float:
        if tk is None:
            raise RuntimeError("Tkinter is not available on this platform")

        if self._event_loop is None:
            try:
                self._event_loop = asyncio.get_running_loop()
            except RuntimeError:
                self._event_loop = None

        if isinstance(self.gui.async_bridge, _LoopAsyncBridge) and self._event_loop:
            self.gui.async_bridge.bind_loop(self._event_loop)

        if self._loop_running:
            return 0.0

        self._loop_running = True
        opened = time.perf_counter()

        try:
            while not self._close_requested:
                try:
                    self.gui.root.update()
                except tk.TclError as exc:
                    self.logger.error("Tk root.update() failed: %s", exc, exc_info=exc)
                    break
                await asyncio.sleep(0.01)
        finally:
            self._window_duration_ms = max(0.0, (time.perf_counter() - opened) * 1000.0)
            self._loop_running = False

        return self._window_duration_ms

    async def cleanup(self) -> None:
        if tk is None:
            return
        try:
            self.gui.destroy_window()
        except tk.TclError:
            pass

    @property
    def window_duration_ms(self) -> float:
        return self._window_duration_ms

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

    def _on_close(self) -> None:
        if self._close_requested:
            return
        self._close_requested = True
        if self.action_callback:
            loop = self._event_loop
            if loop is None:
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
            if loop:
                loop.call_soon_threadsafe(lambda: loop.create_task(self.action_callback("quit")))
        try:
            self.gui.root.quit()
        except Exception:
            pass
