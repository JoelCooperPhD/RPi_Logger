"""Audio state tracking."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from rpi_logger.core.logging_utils import get_module_logger

from .entities import AudioDeviceInfo, AudioSnapshot
from .level_meter import LevelMeter

logger = get_module_logger(__name__)

_STATE_PREFIX = "audio"


class AudioState:
    """Manages device state and notifies observers on change."""

    def __init__(self) -> None:
        self.device: AudioDeviceInfo | None = None
        self.level_meter: LevelMeter | None = None
        self.session_dir: Path | None = None
        self.recording: bool = False
        self.trial_number: int = 1
        self._observers: list[Callable[[AudioSnapshot], None]] = []
        self._status_text: str = "No audio device assigned"
        self._pending_restore_name: str | None = None


    def subscribe(self, observer: Callable[[AudioSnapshot], None]) -> None:
        self._observers.append(observer)
        observer(self.snapshot())

    def _notify(self) -> None:
        snapshot = self.snapshot()
        for observer in list(self._observers):
            try:
                observer(snapshot)
            except Exception:
                logger.debug("Observer notification failed", exc_info=True)

    def snapshot(self) -> AudioSnapshot:
        return AudioSnapshot(
            device=self.device,
            level_meter=self.level_meter,
            recording=self.recording,
            trial_number=self.trial_number,
            session_dir=self.session_dir,
            status_text=self._status_text,
        )


    def set_device(self, device: AudioDeviceInfo) -> None:
        self.device = device
        self.level_meter = LevelMeter()
        self._update_status()
        self._notify()

    def clear_device(self) -> None:
        self.device = None
        self.level_meter = None
        self._update_status()
        self._notify()

    def set_session_dir(self, session_dir: Path | None) -> None:
        if self.session_dir == session_dir:
            return
        self.session_dir = session_dir
        self._notify()

    def set_recording(self, active: bool, trial: int | None = None) -> None:
        if self.recording == active and (trial is None or trial == self.trial_number):
            return
        self.recording = active
        if trial is not None:
            self.trial_number = max(1, trial)
        self._update_status()
        self._notify()

    def _update_status(self) -> None:
        if self.recording:
            device_name = self.device.name if self.device else "unknown"
            self._status_text = f"Recording trial {self.trial_number} ({device_name})"
        elif self.device is None:
            self._status_text = "No audio device assigned"
        else:
            self._status_text = f"Device ready: {self.device.name}"


    def status_payload(self) -> dict[str, object]:
        return {
            "recording": self.recording,
            "trial_number": self.trial_number,
            "device_assigned": self.device is not None,
            "device_name": self.device.name if self.device else None,
            "device_id": self.device.device_id if self.device else None,
            "session_dir": str(self.session_dir) if self.session_dir else None,
            "status_message": self._status_text,
        }


    def get_persistable_state(self) -> dict[str, Any]:
        return {
            "device_name": self.device.name if self.device else "",
        }

    def restore_from_state(self, data: dict[str, Any]) -> None:
        name = data.get("device_name", "")
        self._pending_restore_name = name if name else None

    @classmethod
    def state_prefix(cls) -> str:
        return _STATE_PREFIX

    def try_restore_device_selection(self) -> bool:
        if not self._pending_restore_name or not self.device:
            return False
        if self.device.name == self._pending_restore_name:
            self._pending_restore_name = None
            return True
        return False
