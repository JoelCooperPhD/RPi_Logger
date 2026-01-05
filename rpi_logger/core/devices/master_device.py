"""
Master Device - Physical device representation with capabilities.

This module provides the core data models for the Master Device Architecture,
which tracks physical devices (identified by USB bus path) and their capabilities
(video, audio, serial, etc.).

This is COMPLEMENTARY to the existing CameraCapabilities system:
- MasterDevice: What INTERFACES does this device have? (video, audio)
- CameraCapabilities: What can this camera DO? (modes, controls)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DeviceCapability(Enum):
    """
    What a device can do (capabilities, not families).

    A physical device can have multiple capabilities. For example,
    a USB webcam with built-in microphone has both VIDEO_USB and AUDIO_INPUT.
    """
    VIDEO_USB = "video_usb"
    VIDEO_CSI = "video_csi"
    AUDIO_INPUT = "audio_input"
    AUDIO_OUTPUT = "audio_output"
    SERIAL_DRT = "serial_drt"
    SERIAL_VOG = "serial_vog"
    SERIAL_GPS = "serial_gps"
    NETWORK_EYETRACKER = "network_eyetracker"
    INTERNAL = "internal"


class PhysicalInterface(Enum):
    """How the device connects physically."""
    USB = "usb"
    CSI = "csi"
    UART = "uart"
    NETWORK = "network"
    INTERNAL = "internal"


@dataclass
class CapabilityInfo:
    """
    Base class for capability-specific metadata.

    Each capability type has its own subclass with relevant fields.
    """
    pass


@dataclass
class VideoUSBCapability(CapabilityInfo):
    """USB video capability details."""
    dev_path: str
    stable_id: str
    hw_model: str | None = None


@dataclass
class VideoCSICapability(CapabilityInfo):
    """CSI camera capability details."""
    camera_num: int
    sensor_model: str | None = None


@dataclass
class AudioInputCapability(CapabilityInfo):
    """Audio input capability details."""
    sounddevice_index: int
    alsa_card: int | None = None
    alsa_device: str | None = None
    channels: int = 2
    sample_rate: float = 48000.0


@dataclass
class AudioOutputCapability(CapabilityInfo):
    """Audio output capability details."""
    sounddevice_index: int
    alsa_card: int | None = None
    channels: int = 2
    sample_rate: float = 48000.0


@dataclass
class SerialCapability(CapabilityInfo):
    """Serial device capability details."""
    port: str
    baudrate: int
    vid: int | None = None
    pid: int | None = None
    device_subtype: str = ""


@dataclass
class NetworkCapability(CapabilityInfo):
    """Network device capability details."""
    ip_address: str
    port: int
    service_name: str = ""


@dataclass
class InternalCapability(CapabilityInfo):
    """Internal (virtual) device capability details."""
    module_id: str


@dataclass
class MasterDevice:
    """
    A physical device with one or more capabilities.

    This is the central abstraction - a physical device (identified by USB bus
    path, CSI port, etc.) that can have multiple interfaces/capabilities.

    For example, a Logitech C920 webcam:
        physical_id: "1-2" (USB bus path)
        display_name: "Logitech C920"
        capabilities: {
            VIDEO_USB: VideoUSBCapability(dev_path="/dev/video0", ...),
            AUDIO_INPUT: AudioInputCapability(sounddevice_index=3, ...),
        }
    """
    physical_id: str
    display_name: str
    physical_interface: PhysicalInterface
    vendor_id: int | None = None
    product_id: int | None = None
    capabilities: dict[DeviceCapability, CapabilityInfo] = field(default_factory=dict)
    first_seen: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def has_video(self) -> bool:
        """Check if device has any video capability."""
        return (DeviceCapability.VIDEO_USB in self.capabilities or
                DeviceCapability.VIDEO_CSI in self.capabilities)

    @property
    def has_audio_input(self) -> bool:
        """Check if device has audio input capability."""
        return DeviceCapability.AUDIO_INPUT in self.capabilities

    @property
    def has_audio_output(self) -> bool:
        """Check if device has audio output capability."""
        return DeviceCapability.AUDIO_OUTPUT in self.capabilities

    @property
    def is_webcam(self) -> bool:
        """Check if device is a USB webcam (may or may not have audio)."""
        return DeviceCapability.VIDEO_USB in self.capabilities

    @property
    def is_csi_camera(self) -> bool:
        """Check if device is a CSI camera."""
        return DeviceCapability.VIDEO_CSI in self.capabilities

    @property
    def is_webcam_with_mic(self) -> bool:
        """Check if device is a USB webcam that also has a built-in microphone."""
        return self.is_webcam and self.has_audio_input

    @property
    def is_standalone_audio(self) -> bool:
        """Check if device is audio-only (not part of a webcam)."""
        return self.has_audio_input and not self.has_video

    @property
    def is_serial(self) -> bool:
        """Check if device has any serial capability."""
        serial_caps = {
            DeviceCapability.SERIAL_DRT,
            DeviceCapability.SERIAL_VOG,
            DeviceCapability.SERIAL_GPS,
        }
        return bool(serial_caps & set(self.capabilities.keys()))

    @property
    def is_network(self) -> bool:
        """Check if device is a network device."""
        return DeviceCapability.NETWORK_EYETRACKER in self.capabilities

    @property
    def is_internal(self) -> bool:
        """Check if device is internal (virtual)."""
        return DeviceCapability.INTERNAL in self.capabilities

    @property
    def video_capability(self) -> VideoUSBCapability | VideoCSICapability | None:
        """Get the video capability info, if any."""
        if DeviceCapability.VIDEO_USB in self.capabilities:
            cap = self.capabilities[DeviceCapability.VIDEO_USB]
            return cap if isinstance(cap, VideoUSBCapability) else None
        if DeviceCapability.VIDEO_CSI in self.capabilities:
            cap = self.capabilities[DeviceCapability.VIDEO_CSI]
            return cap if isinstance(cap, VideoCSICapability) else None
        return None

    @property
    def audio_input_capability(self) -> AudioInputCapability | None:
        """Get the audio input capability info, if any."""
        cap = self.capabilities.get(DeviceCapability.AUDIO_INPUT)
        return cap if isinstance(cap, AudioInputCapability) else None

    @property
    def serial_capability(self) -> SerialCapability | None:
        """Get the serial capability info, if any."""
        for cap_type in (DeviceCapability.SERIAL_DRT,
                         DeviceCapability.SERIAL_VOG,
                         DeviceCapability.SERIAL_GPS):
            if cap_type in self.capabilities:
                cap = self.capabilities[cap_type]
                return cap if isinstance(cap, SerialCapability) else None
        return None

    def get_capability(self, cap_type: DeviceCapability) -> CapabilityInfo | None:
        """Get a specific capability by type."""
        return self.capabilities.get(cap_type)

    def has_capability(self, cap_type: DeviceCapability) -> bool:
        """Check if device has a specific capability."""
        return cap_type in self.capabilities

    def capability_types(self) -> set[DeviceCapability]:
        """Get the set of capability types this device has."""
        return set(self.capabilities.keys())
