"""
Core type definitions for device discovery.

These enums are used across the entire device system and module discovery.
They were extracted from device_registry.py as part of the module-driven
discovery refactor.
"""

from enum import Enum


class InterfaceType(Enum):
    """Physical connection interface types."""
    USB = "USB"              # USB-connected devices (serial, audio, cameras)
    XBEE = "XBee"            # XBee wireless (via USB dongle)
    NETWORK = "Network"      # Network/mDNS discovered devices
    CSI = "CSI"              # Raspberry Pi Camera Serial Interface
    INTERNAL = "Internal"    # Software-only (no hardware)
    UART = "UART"            # Built-in serial ports (Pi GPIO UART)


class DeviceFamily(Enum):
    """Device family classification (what type of device)."""
    VOG = "VOG"
    DRT = "DRT"
    EYE_TRACKER = "EyeTracker-Neon"
    AUDIO = "Audio"          # Microphones
    CAMERA_USB = "Camera-USB"    # USB cameras
    CAMERA_CSI = "Camera-CSI"    # Raspberry Pi CSI cameras
    INTERNAL = "Internal"    # Software-only modules (no hardware)
    GPS = "GPS"              # GPS receivers


class DeviceType(Enum):
    """All supported device types across all modules."""
    # VOG devices
    SVOG = "sVOG"
    WVOG_USB = "wVOG_USB"
    WVOG_WIRELESS = "wVOG_Wireless"

    # DRT devices
    SDRT = "DRT"
    WDRT_USB = "wDRT_USB"
    WDRT_WIRELESS = "wDRT_Wireless"

    # Coordinator dongles
    XBEE_COORDINATOR = "XBee_Coordinator"

    # Eye Tracker devices (network-based)
    PUPIL_LABS_NEON = "Pupil_Labs_Neon"

    # Audio devices (discovered via sounddevice)
    USB_MICROPHONE = "USB_Microphone"

    # Internal/virtual devices (always available, no hardware)
    NOTES = "Notes"

    # Camera devices (discovered via /dev/video* or Picamera2)
    USB_CAMERA = "USB_Camera"
    PI_CAMERA = "Pi_Camera"

    # GPS devices (discovered via UART path check)
    BERRY_GPS = "BerryGPS"
