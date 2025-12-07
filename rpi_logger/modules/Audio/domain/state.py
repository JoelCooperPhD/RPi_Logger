"""Audio domain state tracking independent of Tk or sounddevice."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Dict, Optional

from .entities import AudioDeviceInfo, AudioSnapshot
from .level_meter import LevelMeter

_logger = logging.getLogger(__name__)


class AudioState:
    """Holds device + recording state and notifies observers on change."""

    def __init__(self) -> None:
        self.devices: Dict[int, AudioDeviceInfo] = {}
        self.selected_devices: Dict[int, AudioDeviceInfo] = {}
        self.level_meters: Dict[int, LevelMeter] = {}
        self.session_dir: Optional[Path] = None
        self.recording: bool = False
        self.trial_number: int = 1
        self._observers: list[Callable[[AudioSnapshot], None]] = []
        self._status_text: str = "No audio devices detected"

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
                _logger.debug("Observer notification failed", exc_info=True)

    def snapshot(self) -> AudioSnapshot:
        return AudioSnapshot(
            devices=dict(self.devices),
            selected_devices=dict(self.selected_devices),
            level_meters=dict(self.level_meters),
            recording=self.recording,
            trial_number=self.trial_number,
            session_dir=self.session_dir,
            status_text=self._status_text,
        )

    # ------------------------------------------------------------------
    # State mutation helpers

    def set_devices(self, devices: Dict[int, AudioDeviceInfo]) -> None:
        self.devices = dict(devices)
        missing = [device_id for device_id in self.selected_devices.keys() if device_id not in devices]
        for device_id in missing:
            self.selected_devices.pop(device_id, None)
            self.level_meters.pop(device_id, None)

        for device_id, info in devices.items():
            if device_id in self.selected_devices:
                self.selected_devices[device_id] = info

        self._update_status()
        self._notify()

    def set_device(self, device_id: int, device: AudioDeviceInfo) -> None:
        """Add or update a single device (used by centralized discovery)."""
        self.devices[device_id] = device
        if device_id in self.selected_devices:
            self.selected_devices[device_id] = device
        self._update_status()
        self._notify()

    def remove_device(self, device_id: int) -> None:
        """Remove a single device (used by centralized discovery)."""
        self.devices.pop(device_id, None)
        self.selected_devices.pop(device_id, None)
        self.level_meters.pop(device_id, None)
        self._update_status()
        self._notify()

    def set_session_dir(self, session_dir: Optional[Path]) -> None:
        if self.session_dir == session_dir:
            return
        self.session_dir = session_dir
        self._notify()

    def set_recording(self, active: bool, trial: Optional[int] = None) -> None:
        if self.recording == active and (trial is None or trial == self.trial_number):
            return
        self.recording = active
        if trial is not None:
            self.trial_number = max(1, trial)
        self._update_status()
        self._notify()

    def ensure_meter(self, device_id: int) -> LevelMeter:
        meter = self.level_meters.get(device_id)
        if meter is None:
            meter = LevelMeter()
            self.level_meters[device_id] = meter
            self._notify()
        return meter

    def select_device(self, device: AudioDeviceInfo) -> None:
        if device.device_id in self.selected_devices:
            return
        self.selected_devices[device.device_id] = device
        self.ensure_meter(device.device_id)
        self._update_status()
        self._notify()

    def deselect_device(self, device_id: int) -> None:
        if device_id not in self.selected_devices:
            return
        self.selected_devices.pop(device_id, None)
        self.level_meters.pop(device_id, None)
        self._update_status()
        self._notify()

    def _update_status(self) -> None:
        if self.recording:
            self._status_text = (
                f"Recording trial {self.trial_number} ({len(self.selected_devices)} device(s))"
            )
        elif not self.devices:
            self._status_text = "No audio devices detected"
        else:
            self._status_text = f"{len(self.devices)} device(s) available"

    # ------------------------------------------------------------------
    # Status payload helpers

    def status_payload(self) -> dict[str, object]:
        return {
            "recording": self.recording,
            "trial_number": self.trial_number,
            "devices_available": len(self.devices),
            "devices_selected": len(self.selected_devices),
            "session_dir": str(self.session_dir) if self.session_dir else None,
            "status_message": self._status_text,
        }
