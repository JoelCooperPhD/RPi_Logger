"""GPS runtime that adapts the legacy GPS core onto the stub (codex) stack."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

from rpi_logger.core.commands import StatusMessage, StatusType

from vmc import ModuleRuntime, RuntimeContext
from vmc.runtime_helpers import BackgroundTaskManager, ShutdownGuard

from view_adapter import GPSViewAdapter

try:  # pragma: no cover - import exercised at runtime
    from rpi_logger.modules.GPS.gps_core.gps_handler import GPSHandler
    from rpi_logger.modules.GPS.gps_core.recording import GPSRecordingManager
except Exception as exc:  # pragma: no cover - defensive fallback when deps missing
    GPSHandler = None  # type: ignore[assignment]
    GPSRecordingManager = None  # type: ignore[assignment]
    GPS_IMPORT_ERROR = exc
else:
    GPS_IMPORT_ERROR = None


class GPSStubRuntime(ModuleRuntime):
    """Implements the async lifecycle hooks expected by the stub supervisor."""

    def __init__(self, context: RuntimeContext) -> None:
        self.args = context.args
        self.model = context.model
        self.controller = context.controller
        base_logger = context.logger or logging.getLogger("GPSStubRuntime")
        self.logger = base_logger.getChild("Runtime")
        self.view = context.view
        self.display_name = context.display_name
        self.module_dir = context.module_dir

        self.serial_port = str(getattr(self.args, "serial_port", "/dev/serial0"))
        self.baud_rate = int(getattr(self.args, "baud_rate", 9600))
        self.device_timeout = max(1.0, float(getattr(self.args, "device_timeout", 10.0)))
        self.discovery_retry = max(0.5, float(getattr(self.args, "discovery_retry", 3.0)))
        update_hz = float(getattr(self.args, "gps_update_hz", 10.0)) or 5.0
        self.update_interval = 1.0 / max(1.0, update_hz)
        self.map_center = getattr(self.args, "map_center", (40.7608, -111.8910))
        self.map_zoom = float(getattr(self.args, "map_zoom", 11.0))
        offline = getattr(self.args, "offline_tiles", None)
        self.offline_tiles = Path(offline).expanduser() if offline else None

        self.task_manager = BackgroundTaskManager("GPSTasks", self.logger)
        shutdown_timeout = max(5.0, float(getattr(self.args, "shutdown_timeout", 15.0)))
        self.shutdown_guard = ShutdownGuard(self.logger, timeout=shutdown_timeout)

        self.gps_handler: Optional[GPSHandler] = None  # type: ignore[assignment]
        self.recording_manager: Optional[GPSRecordingManager] = None  # type: ignore[assignment]
        self._device_task: Optional[asyncio.Task] = None
        self._update_task: Optional[asyncio.Task] = None
        self._shutdown = asyncio.Event()
        self._device_connected = False
        self._latest_data: Dict[str, Any] = {}
        self._session_dir: Optional[Path] = None
        self._view_adapter: Optional[GPSViewAdapter] = None
        self._auto_start_pending = bool(getattr(self.args, "auto_start_recording", False))
        self._import_error = GPS_IMPORT_ERROR

        self.model.subscribe(self._on_model_change)

    # ------------------------------------------------------------------
    # ModuleRuntime interface

    async def start(self) -> None:
        self.logger.info("Starting %s runtime (port=%s)", self.display_name, self.serial_port)

        self._attach_view()

        if self._import_error:
            message = f"Dependencies unavailable: {self._import_error}"
            self.logger.error(message)
            if self._view_adapter:
                self._view_adapter.show_error(message)
            return

        self._device_task = self.task_manager.create(self._device_loop(), name="GPSDeviceLoop")
        self._update_task = self.task_manager.create(self._update_loop(), name="GPSUpdateLoop")

    async def shutdown(self) -> None:
        if self._shutdown.is_set():
            return
        self._shutdown.set()

        await self.shutdown_guard.start()

        await self.task_manager.shutdown()

        await self._stop_recording_flow()
        await self._stop_gps_handler()

        await self.shutdown_guard.cancel()

    async def cleanup(self) -> None:
        if self.recording_manager:
            with contextlib.suppress(Exception):
                await self.recording_manager.cleanup()
        if self._view_adapter:
            self._view_adapter.close()
            self._view_adapter = None

    async def handle_command(self, command: Dict[str, Any]) -> bool:
        action = (command.get("command") or "").lower()
        if action == "start_recording":
            return await self._start_recording_flow(command)
        if action == "stop_recording":
            return await self._stop_recording_flow()
        return False

    async def healthcheck(self) -> bool:
        return bool(self._device_connected)

    async def on_session_dir_available(self, path: Path) -> None:
        self._session_dir = path
        if self._view_adapter:
            self._view_adapter.set_session_log_path(None)
        await self._maybe_auto_start()

    # ------------------------------------------------------------------
    # Device lifecycle

    async def _device_loop(self) -> None:
        while not self._shutdown.is_set():
            if self.gps_handler:
                try:
                    await asyncio.wait_for(self._shutdown.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                break

            try:
                await self._initialize_gps_handler()
                self._device_connected = True
                await self._monitor_handler()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.logger.warning("GPS handler disconnected: %s", exc, exc_info=True)
                if self._view_adapter:
                    self._view_adapter.show_error("GPS disconnected; retrying...")
            finally:
                self._device_connected = False
                await self._stop_gps_handler()

            if not self._shutdown.is_set():
                await asyncio.sleep(self.discovery_retry)

    async def _initialize_gps_handler(self) -> None:
        if GPSHandler is None:
            raise RuntimeError(f"GPS handler unavailable: {self._import_error}")

        start = time.perf_counter()
        attempts = 0
        discovery_reported = False
        last_error: Optional[Exception] = None

        while not self._shutdown.is_set():
            elapsed = time.perf_counter() - start
            if elapsed > self.device_timeout:
                break

            attempts += 1
            try:
                if not discovery_reported:
                    StatusMessage.send(
                        StatusType.DISCOVERING,
                        {"device_type": "gps_receiver", "port": self.serial_port, "timeout": self.device_timeout},
                    )
                    discovery_reported = True

                handler = GPSHandler(self.serial_port, self.baud_rate)
                await handler.start()

                has_fix = await handler.wait_for_fix(timeout=2.0)
                if has_fix:
                    self.gps_handler = handler
                    self.recording_manager = GPSRecordingManager(handler)
                    StatusMessage.send(
                        StatusType.DEVICE_DETECTED,
                        {"device_type": "gps_receiver", "port": self.serial_port},
                    )
                    init_elapsed = (time.perf_counter() - start) * 1000.0
                    StatusMessage.send_with_timing(
                        StatusType.INITIALIZED,
                        init_elapsed,
                        {
                            "device_type": "gps_receiver",
                            "port": self.serial_port,
                            "discovery_attempts": attempts,
                        },
                    )
                    if self._view_adapter:
                        self._view_adapter.set_device_status("connected", connected=True, has_fix=True)
                    self.logger.info("GPS receiver initialized after %d attempt(s)", attempts)
                    await self._maybe_auto_start()
                    return

                self.logger.info("GPS fix not acquired on attempt %d, retrying...", attempts)
                await handler.stop()
                await asyncio.sleep(0.5)
            except Exception as exc:
                last_error = exc
                self.logger.debug("GPS discovery attempt %d failed: %s", attempts, exc, exc_info=True)
                with contextlib.suppress(Exception):
                    await self._stop_gps_handler()
                await asyncio.sleep(min(1.0, self.discovery_retry))

        message = f"No GPS receiver detected on {self.serial_port} within {self.device_timeout:.1f}s"
        if last_error:
            message += f" (last error: {last_error})"
        raise RuntimeError(message)

    async def _monitor_handler(self) -> None:
        if not self.gps_handler:
            return
        while not self._shutdown.is_set() and self.gps_handler:
            if not getattr(self.gps_handler, "running", False):
                raise RuntimeError("GPS handler stopped unexpectedly")
            await asyncio.sleep(1.0)

    async def _stop_gps_handler(self) -> None:
        handler = self.gps_handler
        self.gps_handler = None
        if handler:
            with contextlib.suppress(Exception):
                await handler.stop()

        manager = self.recording_manager
        if manager and getattr(manager, "recording", False):
            await self._stop_recording_flow()

        self.recording_manager = None

    # ------------------------------------------------------------------
    # Update pipeline

    async def _update_loop(self) -> None:
        while not self._shutdown.is_set():
            handler = self.gps_handler
            if handler:
                try:
                    data = handler.get_latest_data()
                    self._latest_data = data
                    sentences = handler.get_recent_sentences(200) if hasattr(handler, "get_recent_sentences") else []
                    if self._view_adapter:
                        self._view_adapter.update_gps_data(data, sentences)
                        if self.recording_manager and self.recording_manager.csv_file:
                            self._view_adapter.set_session_log_path(Path(self.recording_manager.csv_file))
                except Exception as exc:
                    self.logger.debug("GPS update loop error: %s", exc, exc_info=True)
            await asyncio.sleep(self.update_interval)

    # ------------------------------------------------------------------
    # Recording helpers

    async def _maybe_auto_start(self) -> None:
        if not self._auto_start_pending or self.model.recording:
            return
        if not self.recording_manager or not self.gps_handler:
            return
        if not (self.model.session_dir or self._session_dir):
            return
        payload = {"trial_number": self.model.trial_number or 1}
        success = await self._start_recording_flow(payload)
        if success:
            self._auto_start_pending = False

    async def _start_recording_flow(self, payload: Dict[str, Any]) -> bool:
        if not self.recording_manager or not self.gps_handler:
            self.logger.error("Cannot start GPS recording; handler not ready")
            self.model.recording = False
            if self._view_adapter:
                self._view_adapter.set_recording_state(False)
            return False

        session_path = self.model.session_dir or self._session_dir
        if not session_path:
            session_path = await self._generate_session_dir()
        session_path.mkdir(parents=True, exist_ok=True)

        trial_number = int(payload.get("trial_number") or (self.model.trial_number or 1))
        try:
            success = await self.recording_manager.start_recording(session_path, trial_number)
        except Exception as exc:
            self.logger.error("Failed to start GPS recording: %s", exc, exc_info=True)
            success = False

        if not success:
            self.model.recording = False
            if self._view_adapter:
                self._view_adapter.set_recording_state(False)
            return False

        StatusMessage.send(
            StatusType.RECORDING_STARTED,
            {
                "module": self.display_name,
                "session_dir": str(session_path),
                "trial_number": trial_number,
            },
        )
        if self._view_adapter:
            self._view_adapter.set_recording_state(True)
            if self.recording_manager and self.recording_manager.csv_file:
                self._view_adapter.set_session_log_path(Path(self.recording_manager.csv_file))

        self.logger.info("GPS recording started -> %s", session_path)
        self._auto_start_pending = False
        return True

    async def _stop_recording_flow(self) -> bool:
        manager = self.recording_manager
        if not manager or not getattr(manager, "recording", False):
            return False
        result = False
        try:
            result = await manager.stop_recording()
        except Exception as exc:
            self.logger.error("Failed to stop GPS recording: %s", exc, exc_info=True)
        finally:
            StatusMessage.send(
                StatusType.RECORDING_STOPPED,
                {
                    "module": self.display_name,
                    "session_dir": str(self.model.session_dir or self._session_dir) if (self.model.session_dir or self._session_dir) else None,
                    "file": str(manager.csv_file) if manager and manager.csv_file else None,
                },
        )
        if self._view_adapter:
            self._view_adapter.set_recording_state(False)
        self.logger.info("GPS recording stopped")
        return result

    async def _generate_session_dir(self) -> Path:
        root = Path(getattr(self.args, "output_dir", self.module_dir / "data"))
        root.mkdir(parents=True, exist_ok=True)
        prefix = getattr(self.args, "session_prefix", "session")
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        path = root / f"{prefix}_{timestamp}"
        path.mkdir(parents=True, exist_ok=True)
        self._session_dir = path
        return path

    # ------------------------------------------------------------------
    # Model observers

    def _on_model_change(self, field: str, value: Any) -> None:
        if field == "recording":
            if value:
                self._auto_start_pending = False
            if self._view_adapter:
                self._view_adapter.set_recording_state(bool(value))
        elif field == "session_dir" and value and self._view_adapter:
            self._view_adapter.set_session_log_path(None)

    # ------------------------------------------------------------------
    # View integration

    def _attach_view(self) -> None:
        if not self.view:
            return
        try:
            self._view_adapter = GPSViewAdapter(
                self.view,
                model=self.model,
                logger=self.logger.getChild("ViewAdapter"),
                map_center=self.map_center,
                map_zoom=self.map_zoom,
                offline_tiles=self.offline_tiles,
                disabled_message=str(self._import_error) if self._import_error else None,
            )
        except Exception as exc:
            self.logger.warning("Failed to build GPS view content: %s", exc, exc_info=True)
            self._view_adapter = None
