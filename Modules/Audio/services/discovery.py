"""Device discovery backed by sounddevice only."""

from __future__ import annotations

import logging
from typing import Dict

import sounddevice as sd

from ..state import AudioDeviceInfo


class DeviceDiscoveryService:
    """Query sounddevice for currently available input devices."""

    def __init__(self, logger: logging.Logger, sample_rate: int) -> None:
        self.logger = logger.getChild("Discovery")
        self.sample_rate = sample_rate

    def list_input_devices(self) -> Dict[int, AudioDeviceInfo]:
        self.logger.debug("Querying sounddevice for input devices")
        try:
            devices = sd.query_devices()
        except Exception as exc:
            self.logger.error("sounddevice discovery failed: %s", exc)
            return {}

        discovered: Dict[int, AudioDeviceInfo] = {}
        for index, info in enumerate(devices):
            channels = int(info.get("max_input_channels", 0) or 0)
            if channels <= 0:
                continue
            sample_rate = float(info.get("default_samplerate") or self.sample_rate)
            name = info.get("name", f"Device {index}")
            discovered[index] = AudioDeviceInfo(
                device_id=index,
                name=name,
                channels=channels,
                sample_rate=sample_rate,
            )
        self.logger.debug(
            "Discovered %d/%d audio input device(s)",
            len(discovered),
            len(devices),
        )
        return discovered
