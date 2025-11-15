import asyncio
import logging
import time
from typing import Any, Optional

from rpi_logger.modules.base import BaseSystem, RecordingStateMixin
from .gps_handler import GPSHandler
from .recording import GPSRecordingManager
from .constants import (
    SERIAL_PORT,
    BAUD_RATE,
    FIX_TIMEOUT_SECONDS,
    DATA_WATCHDOG_SECONDS,
)

logger = logging.getLogger(__name__)


class GPSInitializationError(Exception):
    pass


class GPSSystem(BaseSystem, RecordingStateMixin):

    DEFER_DEVICE_INIT_IN_GUI = True

    def __init__(self, args):
        super().__init__(args)
        RecordingStateMixin.__init__(self)

        self.auto_start_recording = getattr(args, "auto_start_recording", False)
        self.gps_handler: Optional[GPSHandler] = None
        self.recording_manager: Optional[GPSRecordingManager] = None
        self.current_trial_number: int = 1
        self.serial_port = self._resolve_serial_port(args)
        self.baud_rate = self._resolve_baud_rate(args)
        self.fix_timeout = self._read_config_float("fix_timeout_seconds", FIX_TIMEOUT_SECONDS)
        self.data_watchdog_timeout = max(
            0.0,
            self._read_config_float(
                "data_watchdog_seconds",
                DATA_WATCHDOG_SECONDS,
                allow_zero=True,
            ),
        )
        self._gps_watchdog_task: Optional[asyncio.Task] = None
        self._handler_restart_lock = asyncio.Lock()

        logger.debug(
            "GPS serial configuration: port=%s baud=%d fix_timeout=%.1fs watchdog=%.1fs",
            self.serial_port,
            self.baud_rate,
            self.fix_timeout,
            self.data_watchdog_timeout,
        )

    async def _initialize_devices(self) -> None:
        logger.info(
            "Initializing GPS receiver on %s @ %d baud (timeout: %.1fs)...",
            self.serial_port,
            self.baud_rate,
            self.device_timeout,
        )

        self.lifecycle_timer.mark_phase("device_discovery_start")
        self.initialized = False

        discovery_attempts = 0
        deadline = time.monotonic() + max(self.device_timeout, 1.0)
        last_error: Optional[str] = None

        while time.monotonic() < deadline:
            discovery_attempts += 1
            handler: Optional[GPSHandler] = None

            try:
                if self._should_send_status() and discovery_attempts == 1:
                    from rpi_logger.core.commands import StatusMessage

                    StatusMessage.send(
                        "discovering",
                        {"device_type": "gps_receiver", "timeout": self.device_timeout},
                    )

                handler = GPSHandler(self.serial_port, self.baud_rate)
                await handler.start()

                logger.debug(
                    "Waiting up to %.1fs for initial GPS fix (attempt %d)",
                    self.fix_timeout,
                    discovery_attempts,
                )

                fix_acquired = await handler.wait_for_fix(timeout=self.fix_timeout)
                if not fix_acquired:
                    raise RuntimeError(
                        f"GPS fix not acquired within {self.fix_timeout:.1f}s"
                    )

                self.gps_handler = handler
                logger.info("GPS receiver locked with fix on attempt %d", discovery_attempts)

                if self._should_send_status():
                    from rpi_logger.core.commands import StatusMessage

                    StatusMessage.send(
                        "device_detected",
                        {"device_type": "gps_receiver", "port": self.serial_port},
                    )
                break
            except Exception as exc:
                last_error = str(exc)
                logger.debug("GPS initialization attempt %d failed: %s", discovery_attempts, exc)
            finally:
                if handler and handler is not self.gps_handler:
                    try:
                        await handler.stop()
                    except Exception as stop_exc:  # pragma: no cover - defensive logging
                        logger.debug("Error stopping provisional GPS handler: %s", stop_exc)

            if self.shutdown_event.is_set():
                raise KeyboardInterrupt("Device discovery cancelled")

            await asyncio.sleep(0.5)

        if not self.gps_handler:
            error_msg = (
                f"No GPS receiver found on {self.serial_port} "
                f"within {self.device_timeout} seconds"
            )
            if last_error:
                error_msg = f"{error_msg} (last error: {last_error})"
            logger.warning(error_msg)
            raise GPSInitializationError(error_msg)

        self.recording_manager = GPSRecordingManager(self.gps_handler)
        self.initialized = True

        self.lifecycle_timer.mark_phase("device_discovery_complete")
        self.lifecycle_timer.mark_phase("initialized")

        logger.info("GPS receiver initialized successfully")

        if self._should_send_status():
            from rpi_logger.core.commands import StatusMessage

            init_duration = self.lifecycle_timer.get_duration("device_discovery_start", "initialized")
            StatusMessage.send_with_timing(
                "initialized",
                init_duration,
                {
                    "device_type": "gps_receiver",
                    "port": self.serial_port,
                    "discovery_attempts": discovery_attempts,
                },
            )

        self._start_watchdog()

    def _start_watchdog(self) -> None:
        if self.data_watchdog_timeout <= 0:
            logger.debug("GPS watchdog disabled (timeout <= 0)")
            return

        if self._gps_watchdog_task and not self._gps_watchdog_task.done():
            return

        logger.debug(
            "Starting GPS data watchdog (stale threshold %.1fs)",
            self.data_watchdog_timeout,
        )
        self._gps_watchdog_task = self.create_background_task(
            self._gps_watchdog_loop(),
            name="gps_watchdog",
        )

    async def _gps_watchdog_loop(self) -> None:
        check_interval = max(0.5, self.data_watchdog_timeout / 3.0)

        try:
            while not self.shutdown_event.is_set():
                handler = self.gps_handler
                if not handler:
                    await asyncio.sleep(check_interval)
                    continue

                read_task = handler.read_task
                if not handler.running or read_task is None or read_task.done():
                    await self._restart_handler("read loop stopped")
                    await asyncio.sleep(check_interval)
                    continue

                age = handler.seconds_since_last_sentence()
                if age is not None and age > self.data_watchdog_timeout:
                    await self._restart_handler(
                        f"no GPS data for {age:.1f}s (threshold {self.data_watchdog_timeout:.1f}s)"
                    )
                    await asyncio.sleep(check_interval)
                    continue

                await asyncio.sleep(check_interval)
        except asyncio.CancelledError:
            logger.debug("GPS watchdog loop cancelled")
            raise
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("GPS watchdog error: %s", exc, exc_info=True)
        finally:
            logger.debug("GPS watchdog loop exited")

    async def _restart_handler(self, reason: str) -> None:
        if self.shutdown_event.is_set():
            return

        async with self._handler_restart_lock:
            if self.shutdown_event.is_set():
                return

            logger.warning("Restarting GPS handler (%s)", reason)
            previous = self.gps_handler
            self.gps_handler = None

            if previous:
                try:
                    await previous.stop()
                except Exception as exc:  # pragma: no cover - defensive logging
                    logger.debug("Error stopping previous GPS handler: %s", exc)

            attempts = 0
            backoff = 1.0
            restart_start = time.monotonic()

            while not self.shutdown_event.is_set():
                attempts += 1
                handler = GPSHandler(self.serial_port, self.baud_rate)
                try:
                    await handler.start()
                    if not await handler.wait_for_fix(timeout=self.fix_timeout):
                        raise RuntimeError(
                            f"GPS fix not acquired within {self.fix_timeout:.1f}s"
                        )

                    self.gps_handler = handler
                    if self.recording_manager:
                        self.recording_manager.set_gps_handler(handler)

                    logger.info(
                        "GPS handler restart succeeded after %d attempt(s) (%.1fs)",
                        attempts,
                        time.monotonic() - restart_start,
                    )
                    return
                except Exception as exc:
                    logger.warning("GPS handler restart attempt %d failed: %s", attempts, exc)
                    try:
                        await handler.stop()
                    except Exception as stop_exc:  # pragma: no cover - defensive logging
                        logger.debug("Failed to stop provisional handler: %s", stop_exc)

                    await asyncio.sleep(min(backoff, 5.0))
                    backoff = min(backoff * 2, 10.0)

            logger.debug("GPS handler restart aborted (shutdown requested)")

    def _resolve_serial_port(self, args: Any) -> str:
        config_value = self.config.get("serial_port") if hasattr(self, "config") else None
        port = getattr(args, "serial_port", None) or config_value or SERIAL_PORT
        return str(port)

    def _resolve_baud_rate(self, args: Any) -> int:
        config_value = self.config.get("baud_rate") if hasattr(self, "config") else None
        candidate = getattr(args, "baud_rate", None)
        if candidate in (None, ""):
            candidate = config_value

        try:
            baud = int(candidate)
            if baud <= 0:
                raise ValueError
            return baud
        except (TypeError, ValueError):
            if candidate is not None:
                logger.warning("Invalid baud rate '%s'; defaulting to %d", candidate, BAUD_RATE)
            return BAUD_RATE

    def _read_config_float(self, key: str, default: float, *, allow_zero: bool = False) -> float:
        raw_value = self.config.get(key) if hasattr(self, "config") else None
        if raw_value in (None, ""):
            return default

        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            logger.warning("Invalid %s value '%s'; defaulting to %.1f", key, raw_value, default)
            return default

        if value < 0:
            logger.warning("%s cannot be negative (%s) – using %.1f", key, raw_value, default)
            return default

        if value == 0 and not allow_zero:
            logger.warning("%s must be positive (%s) – using %.1f", key, raw_value, default)
            return default

        return value

    async def start_recording(self, trial_number: int = 1) -> bool:
        can_start, error_msg = self.validate_recording_start()
        if not can_start:
            logger.error("Cannot start recording: %s", error_msg)
            return False

        if not self.recording_manager:
            logger.error("Recording manager not initialized")
            return False

        self.current_trial_number = trial_number
        self._increment_recording_count()
        self.recording = True

        try:
            await self.recording_manager.start_recording(self.session_dir, trial_number)
            logger.info("Started GPS recording #%d (trial %d)", self.recording_count, trial_number)
            return True
        except Exception as e:
            logger.error("Failed to start recording: %s", e)
            self.recording = False
            return False

    async def stop_recording(self) -> bool:
        can_stop, error_msg = self.validate_recording_stop()
        if not can_stop:
            logger.warning("Cannot stop recording: %s", error_msg)
            return False

        self.recording = False

        if self.recording_manager:
            try:
                await self.recording_manager.stop_recording()
                logger.info("Recording stopped")
                return True
            except Exception as e:
                logger.error("Failed to stop recording: %s", e)
                return False

        return False

    def _create_mode_instance(self, mode_name: str) -> Any:
        if mode_name == "gui":
            from .modes.gui_mode import GUIMode
            return GUIMode(self, enable_commands=self.enable_gui_commands)
        else:
            raise ValueError(f"Unsupported mode: {mode_name}")

    async def cleanup(self) -> None:
        logger.info("GPS cleanup")
        self.running = False
        self.shutdown_event.set()

        if self.recording:
            await self.stop_recording()

        if self.gps_handler:
            handler = self.gps_handler
            self.gps_handler = None
            try:
                await handler.stop()
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.error("Failed to stop GPS handler cleanly: %s", exc, exc_info=True)

        if self.recording_manager:
            manager = self.recording_manager
            self.recording_manager = None
            try:
                await manager.cleanup()
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.error("Failed to cleanup GPS recording manager: %s", exc, exc_info=True)

        self._gps_watchdog_task = None
        self.initialized = False
        logger.info("GPS cleanup completed")
