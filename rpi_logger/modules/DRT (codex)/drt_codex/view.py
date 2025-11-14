"""Tkinter view adapter that reuses the legacy DRT GUI inside the stub framework."""

from __future__ import annotations

import asyncio
import logging
import time
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
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = None

    def run_coroutine(self, coro):
        if self.loop is None or self.loop.is_closed():
            self.loop = asyncio.get_event_loop()
        return self.loop.create_task(coro)


class CodexTkinterGUI(TkinterGUI):
    """TkinterGUI variant that forwards recording controls via the stub controller."""

    def __init__(self, args, action_callback: ActionCallback):
        self._action_callback = action_callback
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


class DRTCodexView:
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
        self.display_name = display_name or "DRT (codex)"
        self.logger = logger or logging.getLogger("DRTCodexView")
        self.gui = CodexTkinterGUI(args, self._dispatch_action)
        self.gui.async_bridge = _LoopAsyncBridge()
        self.gui.set_close_handler(self._on_close)
        self._runtime = None
        self._close_requested = False
        self._window_duration_ms: float = 0.0
        self._loop_running = False
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None

        self.model.subscribe(self._on_model_change)

    # ------------------------------------------------------------------
    # Wiring helpers

    def bind_runtime(self, runtime) -> None:
        """Allow the runtime to expose its API to the GUI once ready."""
        self._runtime = runtime
        self.gui.system = runtime

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
