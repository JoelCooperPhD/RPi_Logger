import logging
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from logger_core.commands import StatusMessage, StatusType
from ..constants import DISPLAY_NAME

logger = logging.getLogger(__name__)


class ModuleState(Enum):
    STOPPED = "stopped"
    IDLE = "idle"
    RECORDING = "recording"
    ERROR = "error"


@dataclass(slots=True)
class RuntimeMetrics:
    ready_ms: float = 0.0
    runtime_ms: float = 0.0
    shutdown_ms: float = 0.0
    shutdown_trigger_ms: float = 0.0
    window_ms: float = 0.0


class StubModel:
    def __init__(self):
        self._startup_timestamp = time.perf_counter()

        self._state = ModuleState.IDLE
        self._recording = False
        self._trial_number: Optional[int] = None
        self._session_dir: Optional[Path] = None
        self._error_message: Optional[str] = None

        self._saved_geometry: Optional[str] = None
        self._pending_geometry: Optional[str] = None

        self.metrics = RuntimeMetrics()
        self.shutdown_reason: Optional[str] = None

        init_elapsed_ms = (time.perf_counter() - self._startup_timestamp) * 1000.0
        logger.info(f"StubModel initialized ({init_elapsed_ms:.2f}ms)")

    @property
    def state(self) -> ModuleState:
        return self._state

    @state.setter
    def state(self, value: ModuleState) -> None:
        if self._state != value:
            old_state = self._state
            self._state = value
            logger.info(f"State changed: {old_state.value} → {value.value}")

    @property
    def recording(self) -> bool:
        return self._recording

    @recording.setter
    def recording(self, value: bool) -> None:
        if self._recording != value:
            self._recording = value
            logger.info(f"Recording: {value}")

    @property
    def trial_number(self) -> Optional[int]:
        return self._trial_number

    @trial_number.setter
    def trial_number(self, value: Optional[int]) -> None:
        if self._trial_number != value:
            self._trial_number = value
            logger.debug(f"Trial number: {value}")

    @property
    def session_dir(self) -> Optional[Path]:
        return self._session_dir

    @session_dir.setter
    def session_dir(self, value: Optional[Path]) -> None:
        if self._session_dir != value:
            self._session_dir = value
            logger.info(f"Session dir: {value}")

    @property
    def error_message(self) -> Optional[str]:
        return self._error_message

    @error_message.setter
    def error_message(self, value: Optional[str]) -> None:
        if self._error_message != value:
            self._error_message = value
            if value:
                logger.error(f"Error: {value}")
                self.state = ModuleState.ERROR

    def get_status_info(self) -> dict:
        return {
            "state": self.state.value,
            "recording": self.recording,
            "trial_number": self.trial_number,
            "session_dir": str(self.session_dir) if self.session_dir else None,
            "error": self.error_message
        }

    @property
    def startup_timestamp(self) -> float:
        return self._startup_timestamp

    def mark_ready(self) -> float:
        ready_elapsed_ms = (time.perf_counter() - self._startup_timestamp) * 1000.0
        self.metrics.ready_ms = ready_elapsed_ms
        StatusMessage.send(
            StatusType.INITIALIZED,
            {"message": f"{DISPLAY_NAME} ready", "ready_ms": round(ready_elapsed_ms, 1)},
        )
        return ready_elapsed_ms

    def request_shutdown(self, reason: str) -> None:
        if self.shutdown_reason:
            return
        self.shutdown_reason = reason
        self.mark_shutdown_phase()
        logger.info(f"Shutdown requested: {reason}")

    def mark_shutdown_phase(self) -> None:
        shutdown_elapsed_ms = (time.perf_counter() - self._startup_timestamp) * 1000.0
        self.metrics.shutdown_trigger_ms = shutdown_elapsed_ms

    def record_window_duration(self, duration_ms: float) -> None:
        self.metrics.window_ms = max(0.0, duration_ms)

    def finalize_metrics(self) -> None:
        total_runtime_ms = (time.perf_counter() - self._startup_timestamp) * 1000.0
        self.metrics.runtime_ms = total_runtime_ms
        trigger_ms = self.metrics.shutdown_trigger_ms
        if trigger_ms > 0.0 and total_runtime_ms >= trigger_ms:
            self.metrics.shutdown_ms = max(0.0, total_runtime_ms - trigger_ms)
        elif self.metrics.shutdown_ms == 0.0 and self.shutdown_reason:
            shutdown_elapsed = total_runtime_ms - self.metrics.ready_ms
            self.metrics.shutdown_ms = max(0.0, shutdown_elapsed)

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

    def set_geometry(self, geometry: str) -> bool:
        if not geometry or geometry == self._pending_geometry:
            return False
        self._pending_geometry = geometry
        return True

    def has_pending_geometry(self) -> bool:
        return self._pending_geometry is not None and self._pending_geometry != self._saved_geometry

    def mark_geometry_saved(self, geometry: str) -> None:
        self._saved_geometry = geometry
        if self._pending_geometry == geometry:
            self._pending_geometry = None
