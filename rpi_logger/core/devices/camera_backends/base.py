"""
Base protocol for camera discovery backends.

Each platform (Linux, macOS, Windows) has its own backend implementation
that provides camera discovery using platform-specific APIs.

Copyright (C) 2024-2025 Red Scientific

Licensed under the Apache License, Version 2.0
"""

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol


@dataclass
class AudioSiblingInfo:
    """Information about an audio device that is part of the same physical device.

    When a USB webcam has a built-in microphone, both the video and audio
    interfaces share the same USB bus path. This class holds the audio
    interface details discovered alongside the video interface.
    """
    sounddevice_index: int
    alsa_card: Optional[int] = None
    channels: int = 2
    sample_rate: float = 48000.0
    name: str = ""


@dataclass
class DiscoveredUSBCamera:
    """Represents a discovered USB camera device.

    This is the common data structure returned by all camera backends.
    It contains all information needed to identify and use a camera.

    Attributes:
        device_id: Unique identifier for this camera (e.g., "usb:0", "usb:usb1-2")
        stable_id: Persistent identifier that survives reboots (USB path or unique ID)
        dev_path: Platform-specific device path (e.g., "/dev/video0" on Linux, index on macOS)
        friendly_name: Human-readable name for display (e.g., "FaceTime HD Camera")
        hw_model: Hardware model identifier if known
        location_hint: Physical location hint (USB port path on Linux)
        usb_bus_path: USB bus path for this device (e.g., "1-2"), used to link
            video and audio interfaces on the same physical device
        audio_sibling: If this webcam has a built-in microphone, contains the
            audio device details. None if no audio sibling was found.
        camera_index: Integer index for cv2.VideoCapture (primarily for Windows).
            On Linux this is extracted from dev_path (e.g., /dev/video0 -> 0).
    """

    device_id: str
    stable_id: str
    dev_path: Optional[str]
    friendly_name: str
    hw_model: Optional[str]
    location_hint: Optional[str]
    usb_bus_path: Optional[str] = None
    audio_sibling: Optional[AudioSiblingInfo] = None
    camera_index: Optional[int] = None


class CameraBackend(Protocol):
    """Protocol for platform-specific camera discovery backends.

    Each platform implements this protocol to provide camera discovery
    using the most appropriate APIs for that platform:
    - Linux: sysfs + OpenCV
    - macOS: AVFoundation + OpenCV
    - Windows: OpenCV (+ WMI for future enhancement)
    """

    def discover_cameras(self, max_devices: int = 16) -> list[DiscoveredUSBCamera]:
        """Discover available cameras on this platform.

        Args:
            max_devices: Maximum number of devices to enumerate.

        Returns:
            List of discovered cameras with full device information.
        """
        ...


__all__ = [
    "AudioSiblingInfo",
    "DiscoveredUSBCamera",
    "CameraBackend",
]
