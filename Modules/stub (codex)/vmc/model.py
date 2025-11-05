"""Model component for the stub (codex) module."""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from cli_utils import ensure_directory, log_module_shutdown, log_module_startup, setup_module_logging
from logger_core.config_manager import get_config_manager
from logger_core.commands import StatusMessage, StatusType
from .constants import DISPLAY_NAME, MODULE_ID


class ModuleState(Enum):
    """High-level lifecycle phases for the stub module."""

    INITIALIZING = "initializing"
    IDLE = "idle"
    RECORDING = "recording"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass(slots=True)
class RuntimeMetrics:
    ready_ms: float = 0.0
    runtime_ms: float = 0.0
    shutdown_ms: float = 0.0
    shutdown_trigger_ms: float = 0.0
    window_ms: float = 0.0


class StubCodexModel:
    """Holds module state and orchestrates environment preparation."""

    def __init__(self, args, module_dir: Path) -> None:
        self.args = args
        self.module_dir = module_dir
        self.shutdown_event = asyncio.Event()
        self.shutdown_reason: Optional[str] = None
        self.window_duration_ms: float = 0.0
        self.metrics = RuntimeMetrics()
        self._startup_timestamp = time.perf_counter()
        self.session_name: Optional[str] = None
        self.log_file: Optional[Path] = None
        self.logs_dir = module_dir / "logs"
        self.config_path = module_dir / "config.txt"
        self.saved_window_geometry: Optional[str] = None
        self._pending_window_geometry: Optional[str] = None
        self._state: ModuleState = ModuleState.INITIALIZING
        self._recording: bool = False
        self._trial_number: Optional[int] = None
        self._session_dir: Optional[Path] = None
        self._error_message: Optional[str] = None
        self._observers: List[Callable[[str, Any], None]] = []

        try:
            config = get_config_manager().read_config(self.config_path)
        except Exception:
            config = {}
        self.saved_window_geometry = config.get("window_geometry")

    @property
    def startup_timestamp(self) -> float:
        return self._startup_timestamp

    async def prepare_environment(self, logger) -> None:
        """Ensure filesystem layout and logging artefacts exist."""
        self.args.output_dir = await asyncio.to_thread(ensure_directory, self.args.output_dir)

        await asyncio.to_thread(self.logs_dir.mkdir, parents=True, exist_ok=True)
        with contextlib.suppress(Exception):
            await asyncio.to_thread(self.logs_dir.chmod, 0o777)

        config_manager = get_config_manager()

        if self.config_path.exists():
            with contextlib.suppress(Exception):
                await asyncio.to_thread(self.config_path.chmod, 0o666)
            config = await config_manager.read_config_async(self.config_path)
            if config.get("display_name") != DISPLAY_NAME:
                await config_manager.write_config_async(self.config_path, {"display_name": DISPLAY_NAME})
            if "window_geometry" not in config:
                await config_manager.write_config_async(
                    self.config_path,
                    {"window_geometry": PLACEHOLDER_GEOMETRY},
                )
            geometry = config.get("window_geometry") or PLACEHOLDER_GEOMETRY
            self.saved_window_geometry = geometry
        else:
            await config_manager.write_config_async(
                self.config_path,
                {
                    "display_name": DISPLAY_NAME,
                    "enabled": False,
                    "window_geometry": PLACEHOLDER_GEOMETRY,
                },
            )
            self.saved_window_geometry = PLACEHOLDER_GEOMETRY

        session_name, log_file, _ = setup_module_logging(
            self.args,
            module_name=MODULE_ID,
            module_dir=self.module_dir,
            default_prefix=MODULE_ID,
        )
        self.session_name = session_name
        self.log_file = log_file

        with contextlib.suppress(Exception):
            await asyncio.to_thread(log_file.chmod, 0o666)

        log_module_startup(
            logger,
            session_name,
            log_file,
            self.args,
            module_name=DISPLAY_NAME,
        )

    def mark_ready(self) -> float:
        ready_elapsed_ms = (time.perf_counter() - self._startup_timestamp) * 1000.0
        self.metrics.ready_ms = ready_elapsed_ms
        StatusMessage.send(
            StatusType.INITIALIZED,
            {"message": f"{DISPLAY_NAME} ready", "ready_ms": round(ready_elapsed_ms, 1)},
        )
        self.state = ModuleState.IDLE
        return ready_elapsed_ms

    def request_shutdown(self, reason: str) -> None:
        if self.shutdown_event.is_set():
            return
        self.shutdown_reason = reason
        self.mark_shutdown_phase()
        self.state = ModuleState.STOPPED
        self.shutdown_event.set()

    def record_window_duration(self, duration_ms: float) -> None:
        self.window_duration_ms = max(0.0, duration_ms)

    def finalize_metrics(self) -> None:
        total_runtime_ms = (time.perf_counter() - self._startup_timestamp) * 1000.0
        self.metrics.runtime_ms = total_runtime_ms
        trigger_ms = self.metrics.shutdown_trigger_ms
        if trigger_ms > 0.0 and total_runtime_ms >= trigger_ms:
            self.metrics.shutdown_ms = max(0.0, total_runtime_ms - trigger_ms)
        elif self.metrics.shutdown_ms == 0.0 and self.shutdown_reason:
            shutdown_elapsed = total_runtime_ms - self.metrics.ready_ms
            self.metrics.shutdown_ms = max(0.0, shutdown_elapsed)
        self.metrics.window_ms = self.window_duration_ms

    def mark_shutdown_phase(self) -> None:
        shutdown_elapsed_ms = (time.perf_counter() - self._startup_timestamp) * 1000.0
        self.metrics.shutdown_trigger_ms = shutdown_elapsed_ms

    def emit_shutdown_logs(self, logger) -> None:
        log_module_shutdown(logger, DISPLAY_NAME)

    def send_runtime_report(self) -> None:
        StatusMessage.send(
            StatusType.STATUS_REPORT,
            {
                "event": "shutdown_timing",
                "runtime_ms": round(self.metrics.runtime_ms, 1),
                "shutdown_ms": round(self.metrics.shutdown_ms, 1),
                "window_ms": round(self.metrics.window_ms, 1),
            },
        )

    # Observable state helpers -------------------------------------------------

    def subscribe(self, observer: Callable[[str, Any], None]) -> None:
        self._observers.append(observer)

    def _notify(self, prop: str, value: Any) -> None:
        for observer in list(self._observers):
            try:
                observer(prop, value)
            except Exception:
                continue

    @property
    def state(self) -> ModuleState:
        return self._state

    @state.setter
    def state(self, value: ModuleState) -> None:
        if self._state is value:
            return
        self._state = value
        self._notify("state", value)

    @property
    def recording(self) -> bool:
        return self._recording

    @recording.setter
    def recording(self, active: bool) -> None:
        if self._recording == active:
            return
        self._recording = active
        if active:
            self.state = ModuleState.RECORDING
        elif self._state is ModuleState.RECORDING:
            self.state = ModuleState.IDLE
        self._notify("recording", active)

    @property
    def trial_number(self) -> Optional[int]:
        return self._trial_number

    @trial_number.setter
    def trial_number(self, value: Optional[int]) -> None:
        if self._trial_number == value:
            return
        self._trial_number = value
        self._notify("trial_number", value)

    @property
    def session_dir(self) -> Optional[Path]:
        return self._session_dir

    @session_dir.setter
    def session_dir(self, path: Optional[Path]) -> None:
        if self._session_dir == path:
            return
        self._session_dir = path
        self._notify("session_dir", path)

    @property
    def error_message(self) -> Optional[str]:
        return self._error_message

    @error_message.setter
    def error_message(self, message: Optional[str]) -> None:
        if self._error_message == message:
            return
        self._error_message = message
        if message:
            self.state = ModuleState.ERROR
        self._notify("error_message", message)

    def get_status_snapshot(self) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "recording": self.recording,
            "trial_number": self.trial_number,
            "session_dir": str(self.session_dir) if self.session_dir else None,
            "error": self.error_message,
        }

    # Window geometry helpers -------------------------------------------------

    def apply_initial_window_geometry(self) -> None:
        if getattr(self.args, "window_geometry", None):
            return
        if self.saved_window_geometry:
            setattr(self.args, "window_geometry", self.saved_window_geometry)

    def set_window_geometry(self, geometry: Optional[str]) -> bool:
        if not geometry:
            return False

        geometry = str(geometry).strip()
        if not geometry:
            return False

        if geometry == self.saved_window_geometry and self._pending_window_geometry is None:
            return False

        if geometry == self._pending_window_geometry:
            return False

        self._pending_window_geometry = geometry
        return True

    async def persist_window_geometry(self) -> None:
        if not self._pending_window_geometry:
            return
        if self._pending_window_geometry == self.saved_window_geometry:
            self._pending_window_geometry = None
            return

        success = await get_config_manager().write_config_async(
            self.config_path,
            {"window_geometry": self._pending_window_geometry},
        )
        if success:
            self.saved_window_geometry = self._pending_window_geometry
            self._pending_window_geometry = None

    def has_pending_window_geometry(self) -> bool:
        return bool(self._pending_window_geometry)
