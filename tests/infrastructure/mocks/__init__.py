"""Mock infrastructure for Logger module testing.

Provides mock implementations of hardware interfaces to enable testing
without physical devices.

Usage:
    from mocks import MockSerialDevice, MockGPSDevice

    # Create a mock GPS that replays NMEA sentences
    gps = MockGPSDevice(nmea_file="/path/to/nmea.log")
    gps.start()

    # Read data as if from real device
    data = gps.read()
"""

from .serial_mocks import (
    MockSerialDevice,
    MockGPSDevice,
    MockDRTDevice,
    MockVOGDevice,
)
from .audio_mocks import MockSoundDevice
from .camera_mocks import MockCameraBackend
from .network_mocks import MockPupilNeonAPI

__all__ = [
    "MockSerialDevice",
    "MockGPSDevice",
    "MockDRTDevice",
    "MockVOGDevice",
    "MockSoundDevice",
    "MockCameraBackend",
    "MockPupilNeonAPI",
]
