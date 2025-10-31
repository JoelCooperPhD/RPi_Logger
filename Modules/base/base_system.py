
import asyncio
import logging
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from .lifecycle_metrics import LifecycleTimer


class ModuleInitializationError(RuntimeError):
    pass


class BaseSystem(ABC):

    # When True, device initialization is deferred until after GUI is created
    DEFER_DEVICE_INIT_IN_GUI = False

    def __init__(self, args: Any):
        self.args = args
        self.logger = logging.getLogger(self.__class__.__name__)
        self.running = False
        self.recording = False
        self.shutdown_event = asyncio.Event()
        self.initialized = False

        self.mode = getattr(args, "mode", "gui")
        self.mode_instance = None
        self.slave_mode = self.mode == "slave"
        self.headless_mode = self.mode == "headless"
        self.gui_mode = self.mode == "gui"

        self.enable_gui_commands = getattr(args, "enable_commands", False) or (
            self.gui_mode and not sys.stdin.isatty()
        )

        self.session_dir: Optional[Path] = getattr(args, "session_dir", None)
        if self.session_dir:
            self.session_label = self.session_dir.name
            self.logger.info("Session directory: %s", self.session_dir)

        self.trial_label: str = ""

        self.console = getattr(args, "console_stdout", sys.stdout)

        self.device_timeout = getattr(args, "discovery_timeout", 5.0)

        module_name = self.__class__.__name__.replace("System", "")
        self.lifecycle_timer = LifecycleTimer(module_name)

    @abstractmethod
    async def _initialize_devices(self) -> None:
        pass

    @abstractmethod
    def _create_mode_instance(self, mode_name: str) -> Any:
        pass

    async def run(self) -> None:
        try:
            if not (self.DEFER_DEVICE_INIT_IN_GUI and self.gui_mode):
                await self._initialize_devices()

            self.mode_instance = self._create_mode_instance(self.mode)
            await self.mode_instance.run()

        except KeyboardInterrupt:
            self.logger.info("%s cancelled by user", self.__class__.__name__)
            if self.slave_mode:
                self._send_slave_error("Cancelled by user")
            raise
        except Exception as e:
            self.logger.error("Unexpected error in run: %s", e)
            if self.slave_mode:
                self._send_slave_error(f"Unexpected error: {e}")
            raise

    async def start_recording(self) -> bool:
        self.logger.warning("%s does not implement start_recording", self.__class__.__name__)
        return False

    async def stop_recording(self) -> bool:
        self.logger.warning("%s does not implement stop_recording", self.__class__.__name__)
        return False

    @abstractmethod
    async def cleanup(self) -> None:
        pass

    def _should_send_status(self) -> bool:
        return self.slave_mode or self.enable_gui_commands

    async def _cleanup_with_timeout(self, coro, timeout: float, operation_name: str) -> bool:
        try:
            await asyncio.wait_for(coro, timeout=timeout)
            self.logger.info("%s completed successfully", operation_name)
            return True
        except asyncio.TimeoutError:
            self.logger.warning("%s did not complete within %.1fs", operation_name, timeout)
            return False
        except Exception as e:
            self.logger.error("%s failed: %s", operation_name, e, exc_info=True)
            return False

    async def _safe_cleanup(self) -> None:
        self.lifecycle_timer.mark_phase("cleanup_start")

        self.running = False
        self.shutdown_event.set()

        if self.recording:
            self.logger.info("Stopping recording before cleanup...")
            if hasattr(self, 'stop_recording'):
                try:
                    await self._cleanup_with_timeout(
                        self.stop_recording(),
                        timeout=5.0,
                        operation_name="Stop recording"
                    )
                except Exception as e:
                    self.logger.error("Error stopping recording during cleanup: %s", e)

        try:
            await self.cleanup()
        except Exception as e:
            self.logger.error("Error during module-specific cleanup: %s", e, exc_info=True)

        self.initialized = False

        self.lifecycle_timer.mark_phase("cleanup_complete")
        self.lifecycle_timer.log_summary()

        if self._should_send_status():
            from logger_core.commands import StatusMessage
            cleanup_duration = self.lifecycle_timer.get_duration("cleanup_start", "cleanup_complete")
            StatusMessage.send_with_timing("cleanup_complete", cleanup_duration)

    def _send_slave_error(self, message: str) -> None:
        try:
            from logger_core.commands import StatusMessage
            StatusMessage.send("error", {"message": message})
        except ImportError:
            self.logger.warning("Cannot send slave error - StatusMessage not available")

    def _send_slave_status(self, status: str, data: Optional[dict] = None) -> None:
        if self.slave_mode:
            try:
                from logger_core.commands import StatusMessage
                StatusMessage.send(status, data or {})
            except ImportError:
                self.logger.warning("Cannot send slave status - StatusMessage not available")
