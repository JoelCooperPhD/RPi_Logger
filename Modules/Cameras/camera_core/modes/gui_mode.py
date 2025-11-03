
import asyncio
import logging
import time
from concurrent.futures import TimeoutError as FutureTimeout
from typing import TYPE_CHECKING

from Modules.base.modes import BaseGUIMode
from ..interfaces.gui import TkinterGUI
from ..commands import CommandHandler
from logger_core.commands import StatusMessage

if TYPE_CHECKING:
    from ..camera_system import CameraSystem


logger = logging.getLogger(__name__)


class GUIMode(BaseGUIMode):

    def __init__(self, camera_system: 'CameraSystem', enable_commands: bool = False):
        super().__init__(camera_system, enable_commands)

    def create_gui(self) -> TkinterGUI:
        gui = TkinterGUI(self.system, self.system.args)

        if self.system.cameras:
            gui.create_preview_canvases()

        return gui

    def create_command_handler(self, gui: TkinterGUI) -> CommandHandler:
        return CommandHandler(self.system, gui=gui)

    async def on_auto_start_recording(self) -> None:
        if self.gui:
            self.gui._start_recording()

    def update_preview(self) -> None:
        if self.gui and self.gui.root.winfo_exists():
            self.gui.update_preview_frames()

    async def on_devices_connected(self) -> None:
        if self.gui and self.gui.root.winfo_exists():
            self.gui.create_preview_canvases()
            self.gui.root.title(f"Camera System - {len(self.system.cameras)} Cameras")

    def create_tasks(self) -> list[asyncio.Task]:
        return super().create_tasks()

    async def cleanup(self) -> None:
        self.logger.info("Camera GUIMode cleanup")

    def sync_cleanup(self) -> None:
        """Perform a best-effort sync cleanup so the Tkinter thread never blocks."""
        bridge = getattr(self, "async_bridge", None)
        if not bridge or bridge.loop is None:
            self.logger.warning("Async bridge not available; skipping synchronous camera cleanup")
            return

        timeout_seconds = min(10.0, max(1.0, getattr(self.system, "shutdown_guard_timeout", 15.0) - 1.0))

        try:
            future = bridge.run_coroutine(self._async_sync_cleanup())
            self.logger.warning("Camera sync_cleanup: coroutine scheduled (future=%s)", future)
        except RuntimeError as exc:  # Bridge shutting down
            self.logger.warning("Failed to schedule async camera cleanup: %s", exc)
            setattr(self.system, "cleanup_failed", True)
            return

        start = time.perf_counter()
        cleanup_failed = False
        try:
            self.logger.warning("Camera sync_cleanup: waiting up to %.1fs for cleanup future", timeout_seconds)
            result = future.result(timeout=timeout_seconds)
            self.logger.warning("Camera sync_cleanup: future.result returned %s", result)
            cleanup_failed = not bool(result)
        except FutureTimeout:
            cleanup_failed = True
            self.logger.error("Camera cleanup timed out after %.1fs; continuing shutdown", timeout_seconds)
            future.cancel()
        except Exception as exc:
            cleanup_failed = True
            self.logger.error("Camera cleanup raised: %s", exc, exc_info=True)
            future.cancel()
        else:
            duration = time.perf_counter() - start
            self.logger.info("Camera sync cleanup finished in %.2fs", duration)
        finally:
            self.logger.warning("Camera sync_cleanup: future done=%s, cancelled=%s",
                                future.done(), future.cancelled())

        if cleanup_failed:
            setattr(self.system, "cleanup_failed", True)
            try:
                StatusMessage.send("warning", {
                    "module": "Camera",
                    "event": "cleanup_failed",
                    "message": "Camera GUI cleanup did not complete within timeout"
                })
            except Exception:
                self.logger.debug("Unable to send cleanup warning status", exc_info=True)
        else:
            setattr(self.system, "cleanup_failed", False)

    async def _async_sync_cleanup(self) -> None:
        cameras = [cam for cam in getattr(self.system, "cameras", []) if cam is not None]
        if not cameras:
            self.logger.debug("No active cameras to clean up")
            return True

        self.logger.warning("Camera async cleanup entered; stopping %d handler(s)", len(cameras))

        async def _cleanup_camera(cam):
            self.logger.warning("Camera %d: _cleanup_camera start", cam.cam_num)
            try:
                self.logger.warning("Camera %d: calling handler.cleanup() with timeout", cam.cam_num)
                summary = await asyncio.wait_for(cam.cleanup(), timeout=12.0)
                self.logger.warning("Camera %d: handler.cleanup() returned %s", cam.cam_num, summary)
            except asyncio.CancelledError:
                self.logger.warning("Camera %d: _cleanup_camera cancelled", cam.cam_num)
                raise
            except asyncio.TimeoutError:
                summary = {
                    "cam": cam.cam_num,
                    "status": "timeout",
                    "message": "Handler cleanup coroutine exceeded %.1fs" % 12.0,
                }
                self.logger.error("Camera %d cleanup coroutine timed out after %.1fs", cam.cam_num, 12.0)
                await self._force_stop_camera(cam)
            except Exception as exc:
                summary = {
                    "cam": cam.cam_num,
                    "status": "error",
                    "error": repr(exc),
                }
                self.logger.error("Camera %d cleanup raised: %s", cam.cam_num, exc, exc_info=True)
                await self._force_stop_camera(cam)

            if not isinstance(summary, dict):
                summary = {
                    "cam": cam.cam_num,
                    "status": "unknown",
                    "detail": summary,
                }

            success = summary.get("success", summary.get("status") == "success")
            if success:
                self.logger.info("Camera %d cleanup summary: %s", cam.cam_num, summary)
            else:
                self.logger.error("Camera %d cleanup summary indicates failure: %s", cam.cam_num, summary)

            return summary

        try:
            summaries = await asyncio.gather(*(_cleanup_camera(cam) for cam in cameras), return_exceptions=True)
            self.logger.warning("Camera async cleanup: asyncio.gather returned %s", summaries)
        except asyncio.CancelledError:
            self.logger.debug("Camera cleanup coroutine cancelled")
            return False
        except Exception as gather_exc:
            self.logger.error("Camera async cleanup: asyncio.gather raised %s", gather_exc, exc_info=True)
            raise

        failures = False
        normalized_summaries = []
        for cam, result in zip(cameras, summaries):
            if isinstance(result, Exception):
                failures = True
                self.logger.error("Camera %d cleanup raised exception: %s", cam.cam_num, result)
                normalized_summaries.append({
                    "cam": cam.cam_num,
                    "status": "error",
                    "error": repr(result),
                })
                continue

            summary = result if isinstance(result, dict) else {
                "cam": cam.cam_num,
                "status": "unknown",
                "detail": result,
            }
            normalized_summaries.append(summary)
            if not summary.get("success", summary.get("status") == "success"):
                failures = True

        self.logger.warning("Camera async cleanup: all handler coroutines finished; failures=%s", failures)

        if hasattr(self.system, "cameras"):
            self.system.cameras.clear()
        if hasattr(self.system, "preview_enabled"):
            self.system.preview_enabled.clear()
        if hasattr(self.system, "initialized"):
            self.system.initialized = False
        if hasattr(self.system, "recording"):
            self.system.recording = False

        self.system.cleanup_report = normalized_summaries
        self.system.cleanup_failed = failures

        return not failures

    async def _force_stop_camera(self, cam) -> None:
        loop = asyncio.get_running_loop()

        async def _call_with_timeout(func, timeout: float, description: str) -> bool:
            try:
                await asyncio.wait_for(loop.run_in_executor(None, func), timeout=timeout)
                self.logger.info("Camera %d: %s succeeded", cam.cam_num, description)
                return True
            except asyncio.TimeoutError:
                self.logger.error("Camera %d: %s timed out after %.1fs", cam.cam_num, description, timeout)
                return False
            except Exception as exc:
                self.logger.error("Camera %d: %s failed: %s", cam.cam_num, description, exc, exc_info=True)
                return False

        stop_fn = getattr(cam.picam2, "stop", None)
        if callable(stop_fn):
            await _call_with_timeout(stop_fn, 2.0, "picam2.stop")

        close_fn = getattr(cam.picam2, "close", None)
        if callable(close_fn):
            await _call_with_timeout(close_fn, 2.0, "picam2.close")

    def _on_recording_state_changed(self, is_recording: bool) -> None:
        """
        Disable/enable camera toggle menu items based on recording state.
        Camera selection should not change during recording.
        """
        if not self.gui:
            return

        state = 'disabled' if is_recording else 'normal'

        for i in range(len(self.system.cameras)):
            try:
                self.gui.view_menu.entryconfig(f"Camera {i}", state=state)
            except Exception:
                pass
