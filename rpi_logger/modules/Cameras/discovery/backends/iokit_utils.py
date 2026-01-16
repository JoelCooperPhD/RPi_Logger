"""
macOS IOKit utilities for USB device enumeration.

Provides VID:PID extraction for USB devices using IOKit via ctypes,
enabling audio sibling detection on macOS by matching webcam video
and audio interfaces that share the same VID:PID.

Based on pyserial's list_ports_osx.py implementation pattern.

Copyright (C) 2024-2025 Red Scientific

Licensed under the Apache License, Version 2.0
"""

import ctypes
import sys
from typing import Optional

from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger("IOKitUtils")

# Only available on macOS
if sys.platform != "darwin":
    raise ImportError("IOKit utilities are only available on macOS")


# Load IOKit and CoreFoundation frameworks
try:
    iokit = ctypes.cdll.LoadLibrary(
        "/System/Library/Frameworks/IOKit.framework/IOKit"
    )
    cf = ctypes.cdll.LoadLibrary(
        "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
    )
except OSError as e:
    logger.warning(f"Failed to load IOKit/CoreFoundation: {e}")
    raise ImportError(f"IOKit not available: {e}") from e


# Constants
# kIOMasterPortDefault is no longer exported in Big Sur, but NULL works
kIOMasterPortDefault = 0
kCFAllocatorDefault = ctypes.c_void_p.in_dll(cf, "kCFAllocatorDefault")

kCFStringEncodingUTF8 = 0x08000100

# CFNumber type defines
kCFNumberSInt16Type = 2
kCFNumberSInt32Type = 3

# `io_name_t` defined as `typedef char io_name_t[128];`
io_name_size = 128

# kern_return_t success value
KERN_SUCCESS = 0
kern_return_t = ctypes.c_int


# Set up IOKit function signatures
iokit.IOServiceMatching.restype = ctypes.c_void_p

iokit.IOServiceGetMatchingServices.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
]
iokit.IOServiceGetMatchingServices.restype = kern_return_t

iokit.IOIteratorNext.argtypes = [ctypes.c_void_p]
iokit.IOIteratorNext.restype = ctypes.c_void_p

iokit.IOIteratorIsValid.argtypes = [ctypes.c_void_p]
iokit.IOIteratorIsValid.restype = ctypes.c_bool

iokit.IORegistryEntryGetParentEntry.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
]
iokit.IORegistryEntryGetParentEntry.restype = kern_return_t

iokit.IORegistryEntryCreateCFProperty.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32
]
iokit.IORegistryEntryCreateCFProperty.restype = ctypes.c_void_p

iokit.IORegistryEntryGetName.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
iokit.IORegistryEntryGetName.restype = kern_return_t

iokit.IOObjectGetClass.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
iokit.IOObjectGetClass.restype = kern_return_t

iokit.IOObjectRelease.argtypes = [ctypes.c_void_p]
iokit.IOObjectRelease.restype = kern_return_t


# Set up CoreFoundation function signatures
cf.CFStringCreateWithCString.argtypes = [
    ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int32
]
cf.CFStringCreateWithCString.restype = ctypes.c_void_p

cf.CFStringGetCStringPtr.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
cf.CFStringGetCStringPtr.restype = ctypes.c_char_p

cf.CFStringGetCString.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long, ctypes.c_uint32
]
cf.CFStringGetCString.restype = ctypes.c_bool

cf.CFNumberGetValue.argtypes = [
    ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p
]
cf.CFNumberGetValue.restype = ctypes.c_void_p

cf.CFRelease.argtypes = [ctypes.c_void_p]
cf.CFRelease.restype = None


def _get_string_property(device: ctypes.c_void_p, prop: str) -> Optional[str]:
    """Get a string property from an IOKit device.

    Args:
        device: IOKit device reference
        prop: Property name to retrieve

    Returns:
        Property value as string, or None if not found.
    """
    key = cf.CFStringCreateWithCString(
        kCFAllocatorDefault, prop.encode("utf-8"), kCFStringEncodingUTF8
    )
    if not key:
        return None

    try:
        cf_value = iokit.IORegistryEntryCreateCFProperty(
            device, key, kCFAllocatorDefault, 0
        )
        if not cf_value:
            return None

        try:
            # Try fast path first
            result = cf.CFStringGetCStringPtr(cf_value, 0)
            if result is not None:
                return result.decode("utf-8")

            # Fall back to buffer copy
            buffer = ctypes.create_string_buffer(io_name_size)
            if cf.CFStringGetCString(
                cf_value, ctypes.byref(buffer), io_name_size, kCFStringEncodingUTF8
            ):
                return buffer.value.decode("utf-8")
            return None
        finally:
            cf.CFRelease(cf_value)
    finally:
        cf.CFRelease(key)


def _get_int_property(
    device: ctypes.c_void_p, prop: str, cf_type: int = kCFNumberSInt16Type
) -> Optional[int]:
    """Get an integer property from an IOKit device.

    Args:
        device: IOKit device reference
        prop: Property name to retrieve
        cf_type: CFNumber type (kCFNumberSInt16Type or kCFNumberSInt32Type)

    Returns:
        Property value as integer, or None if not found.
    """
    key = cf.CFStringCreateWithCString(
        kCFAllocatorDefault, prop.encode("utf-8"), kCFStringEncodingUTF8
    )
    if not key:
        return None

    try:
        cf_value = iokit.IORegistryEntryCreateCFProperty(
            device, key, kCFAllocatorDefault, 0
        )
        if not cf_value:
            return None

        try:
            if cf_type == kCFNumberSInt32Type:
                number = ctypes.c_uint32()
            else:
                number = ctypes.c_uint16()

            cf.CFNumberGetValue(cf_value, cf_type, ctypes.byref(number))
            return number.value
        finally:
            cf.CFRelease(cf_value)
    finally:
        cf.CFRelease(key)


def _get_device_class(device: ctypes.c_void_p) -> bytes:
    """Get the IOKit class name of a device."""
    classname = ctypes.create_string_buffer(io_name_size)
    iokit.IOObjectGetClass(device, ctypes.byref(classname))
    return classname.value


def _get_device_name(device: ctypes.c_void_p) -> Optional[str]:
    """Get the registry entry name of a device."""
    name = ctypes.create_string_buffer(io_name_size)
    result = iokit.IORegistryEntryGetName(device, ctypes.byref(name))
    if result != KERN_SUCCESS:
        return None
    return name.value.decode("utf-8")


def _get_parent_by_type(
    device: ctypes.c_void_p, parent_type: str
) -> Optional[ctypes.c_void_p]:
    """Walk up the IOKit tree to find a parent of the specified type.

    Args:
        device: Starting device reference
        parent_type: IOKit class name to find (e.g., "IOUSBHostDevice")

    Returns:
        Parent device reference, or None if not found.
    """
    parent_type_bytes = parent_type.encode("utf-8")

    while _get_device_class(device) != parent_type_bytes:
        parent = ctypes.c_void_p()
        result = iokit.IORegistryEntryGetParentEntry(
            device, b"IOService", ctypes.byref(parent)
        )
        if result != KERN_SUCCESS:
            return None
        device = parent

    return device


def _get_services_by_type(service_type: str) -> list[ctypes.c_void_p]:
    """Get all IOKit services of a given type.

    Args:
        service_type: IOKit class name to match

    Returns:
        List of device references. Caller must release each with IOObjectRelease.
    """
    iterator = ctypes.c_void_p()

    result = iokit.IOServiceGetMatchingServices(
        kIOMasterPortDefault,
        iokit.IOServiceMatching(service_type.encode("utf-8")),
        ctypes.byref(iterator),
    )

    if result != KERN_SUCCESS:
        return []

    services = []
    while iokit.IOIteratorIsValid(iterator):
        service = iokit.IOIteratorNext(iterator)
        if not service:
            break
        services.append(service)

    iokit.IOObjectRelease(iterator)
    return services


def get_usb_devices() -> list[dict]:
    """Get all USB devices with their VID:PID and names.

    Returns:
        List of dicts with keys:
            - vid: Vendor ID (int)
            - pid: Product ID (int)
            - vid_pid: "XXXX:YYYY" format string
            - name: Device product name
            - manufacturer: Device manufacturer name
    """
    devices = []

    # Try IOUSBHostDevice first (modern macOS, Apple Silicon)
    services = _get_services_by_type("IOUSBHostDevice")
    if not services:
        # Fall back to IOUSBDevice (older macOS, deprecated but may still work)
        services = _get_services_by_type("IOUSBDevice")

    for service in services:
        try:
            vid = _get_int_property(service, "idVendor", kCFNumberSInt16Type)
            pid = _get_int_property(service, "idProduct", kCFNumberSInt16Type)

            if vid is not None and pid is not None:
                name = _get_device_name(service) or ""
                manufacturer = _get_string_property(service, "USB Vendor Name") or ""

                devices.append({
                    "vid": vid,
                    "pid": pid,
                    "vid_pid": f"{vid:04x}:{pid:04x}",
                    "name": name,
                    "manufacturer": manufacturer,
                })
        finally:
            iokit.IOObjectRelease(service)

    return devices


def get_vid_pid_for_camera_name(camera_name: str) -> Optional[str]:
    """Find VID:PID for a camera by matching its name.

    Searches USB devices for one whose name contains the camera name
    (or vice versa), useful for correlating AVFoundation camera names
    with their USB VID:PID.

    Args:
        camera_name: Camera name from AVFoundation (e.g., "FaceTime HD Camera")

    Returns:
        VID:PID string in "XXXX:YYYY" format, or None if not found.
    """
    if not camera_name:
        return None

    camera_name_lower = camera_name.lower()
    usb_devices = get_usb_devices()

    for dev in usb_devices:
        dev_name_lower = dev["name"].lower()

        # Check bidirectional containment (handles different naming conventions)
        if camera_name_lower in dev_name_lower or dev_name_lower in camera_name_lower:
            return dev["vid_pid"]

        # Also check manufacturer string
        manufacturer_lower = dev.get("manufacturer", "").lower()
        if manufacturer_lower and camera_name_lower in manufacturer_lower:
            return dev["vid_pid"]

    return None


def find_audio_device_with_vid_pid(vid_pid: str) -> Optional[dict]:
    """Find an audio input device that matches the given VID:PID.

    Searches sounddevice inputs and tries to match them to USB devices
    by name, then checks if the USB device has the target VID:PID.

    Args:
        vid_pid: Target VID:PID in "XXXX:YYYY" format

    Returns:
        Dict with sounddevice info if found:
            - sounddevice_index: Index for sounddevice
            - channels: Max input channels
            - sample_rate: Default sample rate
            - name: Device name
        Or None if no matching audio device found.
    """
    try:
        import sounddevice as sd
    except ImportError:
        return None

    try:
        sd_devices = sd.query_devices()
    except Exception:
        return None

    usb_devices = get_usb_devices()

    # Build a map of USB device names to VID:PID
    usb_name_to_vid_pid: dict[str, str] = {}
    for dev in usb_devices:
        name_lower = dev["name"].lower()
        usb_name_to_vid_pid[name_lower] = dev["vid_pid"]

    # Search sounddevice inputs for a match
    for i, sd_dev in enumerate(sd_devices):
        if sd_dev.get("max_input_channels", 0) <= 0:
            continue

        sd_name = sd_dev.get("name", "")
        sd_name_lower = sd_name.lower()

        # Try to match sounddevice name to USB device name
        for usb_name, usb_vid_pid in usb_name_to_vid_pid.items():
            # Check if names match (either direction containment)
            if usb_name in sd_name_lower or sd_name_lower in usb_name:
                if usb_vid_pid == vid_pid:
                    return {
                        "sounddevice_index": i,
                        "channels": sd_dev.get("max_input_channels", 2),
                        "sample_rate": sd_dev.get("default_samplerate", 48000.0),
                        "name": sd_name,
                    }

    return None


def find_builtin_audio_sibling(camera_name: str) -> Optional[dict]:
    """Find an audio device for built-in (non-USB) cameras using name heuristics.

    On Apple Silicon Macs, built-in cameras (like FaceTime HD Camera) are not
    USB devices, so VID:PID matching won't work. This function uses name-based
    heuristics to match built-in cameras with built-in microphones.

    Args:
        camera_name: Camera name (e.g., "FaceTime HD Camera")

    Returns:
        Dict with sounddevice info if a match is found:
            - sounddevice_index: Index for sounddevice
            - channels: Max input channels
            - sample_rate: Default sample rate
            - name: Device name
        Or None if no match found.
    """
    try:
        import sounddevice as sd
    except ImportError:
        return None

    if not camera_name:
        return None

    camera_name_lower = camera_name.lower()

    # Built-in camera patterns (FaceTime, iSight, etc.)
    builtin_camera_patterns = ["facetime", "isight", "built-in"]
    is_builtin_camera = any(p in camera_name_lower for p in builtin_camera_patterns)

    if not is_builtin_camera:
        return None

    # Built-in microphone patterns
    builtin_mic_patterns = [
        "macbook",
        "imac",
        "mac mini",
        "mac pro",
        "mac studio",
        "built-in",
        "internal",
    ]

    try:
        sd_devices = sd.query_devices()
    except Exception:
        return None

    # Search for built-in microphone
    for i, sd_dev in enumerate(sd_devices):
        if sd_dev.get("max_input_channels", 0) <= 0:
            continue

        sd_name = sd_dev.get("name", "")
        sd_name_lower = sd_name.lower()

        # Check if this is a built-in microphone
        if any(p in sd_name_lower for p in builtin_mic_patterns):
            # Exclude virtual audio devices
            if "virtual" in sd_name_lower or "teams" in sd_name_lower:
                continue

            return {
                "sounddevice_index": i,
                "channels": sd_dev.get("max_input_channels", 1),
                "sample_rate": sd_dev.get("default_samplerate", 48000.0),
                "name": sd_name,
            }

    return None


__all__ = [
    "get_usb_devices",
    "get_vid_pid_for_camera_name",
    "find_audio_device_with_vid_pid",
    "find_builtin_audio_sibling",
]
