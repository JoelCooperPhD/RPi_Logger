"""
Audio module discovery package.

Provides USB microphone discovery using sounddevice.
"""

from rpi_logger.core.devices.discovery_protocol import (
    BaseModuleDiscovery,
    DeviceFoundCallback,
    DeviceLostCallback,
)
from .spec import DISCOVERY_SPEC
from .scanner import (
    AudioScanner,
    DiscoveredAudioDevice,
    SOUNDDEVICE_AVAILABLE,
)


class AudioDiscovery(BaseModuleDiscovery):
    """Discovery handler for USB audio devices."""

    spec = DISCOVERY_SPEC

    def create_scanner(
        self,
        on_found: DeviceFoundCallback,
        on_lost: DeviceLostCallback,
    ) -> AudioScanner:
        """Create audio scanner with callbacks."""
        return AudioScanner(
            on_device_found=on_found,
            on_device_lost=on_lost,
        )


# Exports for discovery loader
__all__ = [
    "AudioDiscovery",
    "DISCOVERY_SPEC",
    "AudioScanner",
    "DiscoveredAudioDevice",
    "SOUNDDEVICE_AVAILABLE",
]
