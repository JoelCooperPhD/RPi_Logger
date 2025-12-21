"""Audio domain state tracking independent of Tk or sounddevice."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from rpi_logger.core.logging_utils import get_module_logger

from .entities import AudioDeviceInfo, AudioSnapshot
from .level_meter import LevelMeter

logger = get_module_logger(__name__)

# State persistence prefix for config keys
_STATE_PREFIX = "audio"


class AudioState:
    """Holds single device + recording state and notifies observers on change.

    The audio module supports a single device at a time, assigned by the main logger.
    Device discovery is handled externally - this module only receives assignments.
    """

    def __init__(self) -> None:
        self.device: AudioDeviceInfo | None = None
        self.level_meter: LevelMeter | None = None
        self.session_dir: Path | None = None
        self.recording: bool = False
        self.trial_number: int = 1
        self._observers: list[Callable[[AudioSnapshot], None]] = []
        self._status_text: str = "No audio device assigned"
        self._pending_restore_name: str | None = None

    # ------------------------------------------------------------------
    # Observer helpers

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

    # ------------------------------------------------------------------
    # State mutation helpers

    def set_device(self, device: AudioDeviceInfo) -> None:
        """Set the single assigned device (replaces any existing)."""
        self.device = device
        self.level_meter = LevelMeter()
        self._update_status()
        self._notify()

    def clear_device(self) -> None:
        """Clear the assigned device."""
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

    # ------------------------------------------------------------------
    # Status payload helpers

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

    # ------------------------------------------------------------------
    # State persistence (StatePersistence protocol)

    def get_persistable_state(self) -> dict[str, Any]:
        """Return state that should be persisted across restarts."""
        return {
            "device_name": self.device.name if self.device else "",
        }

    def restore_from_state(self, data: dict[str, Any]) -> None:
        """Restore state from previously persisted data."""
        name = data.get("device_name", "")
        self._pending_restore_name = name if name else None

    @classmethod
    def state_prefix(cls) -> str:
        """Return the config key prefix for this state class."""
        return _STATE_PREFIX

    def try_restore_device_selection(self) -> bool:
        """Check if current device matches pending restore name.

        Returns True if the current device matches the persisted name.
        """
        if not self._pending_restore_name or not self.device:
            return False
        if self.device.name == self._pending_restore_name:
            self._pending_restore_name = None
            return True
        return False
