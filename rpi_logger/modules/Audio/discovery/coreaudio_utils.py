"""
CoreAudio utilities for macOS audio device detection.

Uses CoreAudio's C API via ctypes to identify USB audio devices.
This allows proper filtering of audio devices on macOS where device names
don't contain "USB" like they do on Windows.

Copyright (C) 2024-2025 Red Scientific

Licensed under the Apache License, Version 2.0
"""

import ctypes
from ctypes import c_uint32, c_int32, c_void_p, c_char_p, byref, POINTER, Structure
import sys
from typing import Set

from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger("CoreAudioUtils")

# Only available on macOS
if sys.platform != "darwin":
    raise ImportError("CoreAudio utilities only available on macOS")


# CoreAudio constants (FourCC codes)
kAudioObjectSystemObject = 1
kAudioHardwarePropertyDevices = 0x64657623  # 'dev#'
kAudioObjectPropertyScopeGlobal = 0x676C6F62  # 'glob'
kAudioObjectPropertyElementMain = 0  # Was kAudioObjectPropertyElementMaster

kAudioDevicePropertyDeviceNameCFString = 0x6C6E616D  # 'lnam'
kAudioDevicePropertyTransportType = 0x7472616E  # 'tran'
kAudioDevicePropertyStreams = 0x73746D23  # 'stm#'
kAudioObjectPropertyScopeInput = 0x696E7074  # 'inpt'

# Transport types
kAudioDeviceTransportTypeUSB = 0x75736220  # 'usb '
kAudioDeviceTransportTypeBuiltIn = 0x626C746E  # 'bltn'
kAudioDeviceTransportTypeBluetooth = 0x626C7565  # 'blue'
kAudioDeviceTransportTypeVirtual = 0x76697274  # 'virt'
kAudioDeviceTransportTypeAggregate = 0x67727570  # 'grup'


class AudioObjectPropertyAddress(Structure):
    """CoreAudio property address structure."""
    _fields_ = [
        ("mSelector", c_uint32),
        ("mScope", c_uint32),
        ("mElement", c_uint32),
    ]


# Load CoreAudio framework
try:
    _core_audio = ctypes.CDLL(
        "/System/Library/Frameworks/CoreAudio.framework/CoreAudio"
    )
    _core_foundation = ctypes.CDLL(
        "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
    )
    COREAUDIO_AVAILABLE = True
except OSError as e:
    logger.warning(f"Failed to load CoreAudio: {e}")
    COREAUDIO_AVAILABLE = False


if COREAUDIO_AVAILABLE:
    # AudioObjectGetPropertyDataSize
    _AudioObjectGetPropertyDataSize = _core_audio.AudioObjectGetPropertyDataSize
    _AudioObjectGetPropertyDataSize.argtypes = [
        c_uint32,  # inObjectID
        POINTER(AudioObjectPropertyAddress),  # inAddress
        c_uint32,  # inQualifierDataSize
        c_void_p,  # inQualifierData
        POINTER(c_uint32),  # outDataSize
    ]
    _AudioObjectGetPropertyDataSize.restype = c_int32

    # AudioObjectGetPropertyData
    _AudioObjectGetPropertyData = _core_audio.AudioObjectGetPropertyData
    _AudioObjectGetPropertyData.argtypes = [
        c_uint32,  # inObjectID
        POINTER(AudioObjectPropertyAddress),  # inAddress
        c_uint32,  # inQualifierDataSize
        c_void_p,  # inQualifierData
        POINTER(c_uint32),  # ioDataSize
        c_void_p,  # outData
    ]
    _AudioObjectGetPropertyData.restype = c_int32

    # CFStringGetCString
    _CFStringGetCString = _core_foundation.CFStringGetCString
    _CFStringGetCString.argtypes = [c_void_p, c_char_p, c_uint32, c_uint32]
    _CFStringGetCString.restype = ctypes.c_bool

    # CFRelease
    _CFRelease = _core_foundation.CFRelease
    _CFRelease.argtypes = [c_void_p]
    _CFRelease.restype = None


def _cfstring_to_python(cfstring: c_void_p) -> str:
    """Convert CFString to Python string."""
    if not cfstring:
        return ""

    buffer = ctypes.create_string_buffer(256)
    # kCFStringEncodingUTF8 = 0x08000100
    if _CFStringGetCString(cfstring, buffer, 256, 0x08000100):
        return buffer.value.decode("utf-8")
    return ""


def _get_device_property_string(device_id: int, selector: int) -> str:
    """Get a string property from an audio device."""
    address = AudioObjectPropertyAddress(
        mSelector=selector,
        mScope=kAudioObjectPropertyScopeGlobal,
        mElement=kAudioObjectPropertyElementMain,
    )

    data_size = c_uint32(ctypes.sizeof(c_void_p))
    cfstring = c_void_p()

    status = _AudioObjectGetPropertyData(
        device_id,
        byref(address),
        0,
        None,
        byref(data_size),
        byref(cfstring),
    )

    if status != 0 or not cfstring:
        return ""

    result = _cfstring_to_python(cfstring)
    _CFRelease(cfstring)
    return result


def _get_device_property_uint32(device_id: int, selector: int) -> int:
    """Get a UInt32 property from an audio device."""
    address = AudioObjectPropertyAddress(
        mSelector=selector,
        mScope=kAudioObjectPropertyScopeGlobal,
        mElement=kAudioObjectPropertyElementMain,
    )

    data_size = c_uint32(ctypes.sizeof(c_uint32))
    value = c_uint32()

    status = _AudioObjectGetPropertyData(
        device_id,
        byref(address),
        0,
        None,
        byref(data_size),
        byref(value),
    )

    if status != 0:
        return 0

    return value.value


def _device_has_input_streams(device_id: int) -> bool:
    """Check if device has input streams (is an input device)."""
    address = AudioObjectPropertyAddress(
        mSelector=kAudioDevicePropertyStreams,
        mScope=kAudioObjectPropertyScopeInput,
        mElement=kAudioObjectPropertyElementMain,
    )

    data_size = c_uint32()
    status = _AudioObjectGetPropertyDataSize(
        device_id,
        byref(address),
        0,
        None,
        byref(data_size),
    )

    # If we can get the size and it's > 0, device has input streams
    return status == 0 and data_size.value > 0


def get_usb_audio_device_names() -> Set[str]:
    """
    Get names of hardware audio input devices on macOS.

    Uses CoreAudio to query device transport types and identify physical devices.
    Only returns devices that have input capability (microphones).

    Includes:
    - USB devices (external microphones like Blue Yeti)
    - Built-in devices (MacBook microphone)

    Excludes:
    - Virtual devices (Microsoft Teams Audio, BlackHole, etc.)
    - Aggregate devices (user-created combined devices)
    - Bluetooth devices (handled separately, often unreliable for recording)

    Returns:
        Set of device names that are hardware audio input devices.
    """
    if not COREAUDIO_AVAILABLE:
        logger.debug("CoreAudio not available")
        return set()

    hardware_device_names: Set[str] = set()

    # Transport types to include (actual hardware)
    allowed_transports = {
        kAudioDeviceTransportTypeUSB,
        kAudioDeviceTransportTypeBuiltIn,
    }

    try:
        # Get list of all audio devices
        address = AudioObjectPropertyAddress(
            mSelector=kAudioHardwarePropertyDevices,
            mScope=kAudioObjectPropertyScopeGlobal,
            mElement=kAudioObjectPropertyElementMain,
        )

        # Get size of device list
        data_size = c_uint32()
        status = _AudioObjectGetPropertyDataSize(
            kAudioObjectSystemObject,
            byref(address),
            0,
            None,
            byref(data_size),
        )

        if status != 0:
            logger.debug(f"Failed to get device list size: {status}")
            return set()

        # Get device IDs
        num_devices = data_size.value // ctypes.sizeof(c_uint32)
        device_ids = (c_uint32 * num_devices)()

        status = _AudioObjectGetPropertyData(
            kAudioObjectSystemObject,
            byref(address),
            0,
            None,
            byref(data_size),
            device_ids,
        )

        if status != 0:
            logger.debug(f"Failed to get device list: {status}")
            return set()

        # Check each device
        for device_id in device_ids:
            # Skip devices without input streams (not microphones)
            if not _device_has_input_streams(device_id):
                continue

            # Get transport type
            transport = _get_device_property_uint32(
                device_id, kAudioDevicePropertyTransportType
            )

            # Only include hardware devices (USB + Built-in)
            if transport not in allowed_transports:
                continue

            # Get device name
            name = _get_device_property_string(
                device_id, kAudioDevicePropertyDeviceNameCFString
            )

            if name:
                hardware_device_names.add(name)

        if hardware_device_names:
            logger.debug("CoreAudio discovery: %d hardware input devices", len(hardware_device_names))

    except Exception as e:
        logger.warning(f"Error querying CoreAudio devices: {e}")

    return hardware_device_names


def get_all_audio_input_devices() -> dict:
    """
    Get all audio input devices with their transport types.

    Useful for debugging and understanding what's available.

    Returns:
        Dict mapping device names to transport type strings.
    """
    if not COREAUDIO_AVAILABLE:
        return {}

    transport_names = {
        kAudioDeviceTransportTypeUSB: "USB",
        kAudioDeviceTransportTypeBuiltIn: "Built-in",
        kAudioDeviceTransportTypeBluetooth: "Bluetooth",
        kAudioDeviceTransportTypeVirtual: "Virtual",
        kAudioDeviceTransportTypeAggregate: "Aggregate",
    }

    devices = {}

    try:
        # Get list of all audio devices
        address = AudioObjectPropertyAddress(
            mSelector=kAudioHardwarePropertyDevices,
            mScope=kAudioObjectPropertyScopeGlobal,
            mElement=kAudioObjectPropertyElementMain,
        )

        data_size = c_uint32()
        status = _AudioObjectGetPropertyDataSize(
            kAudioObjectSystemObject,
            byref(address),
            0,
            None,
            byref(data_size),
        )

        if status != 0:
            return {}

        num_devices = data_size.value // ctypes.sizeof(c_uint32)
        device_ids = (c_uint32 * num_devices)()

        status = _AudioObjectGetPropertyData(
            kAudioObjectSystemObject,
            byref(address),
            0,
            None,
            byref(data_size),
            device_ids,
        )

        if status != 0:
            return {}

        for device_id in device_ids:
            if not _device_has_input_streams(device_id):
                continue

            name = _get_device_property_string(
                device_id, kAudioDevicePropertyDeviceNameCFString
            )
            transport = _get_device_property_uint32(
                device_id, kAudioDevicePropertyTransportType
            )

            transport_str = transport_names.get(transport, f"Unknown (0x{transport:08x})")
            devices[name] = transport_str

    except Exception as e:
        logger.warning(f"Error querying CoreAudio devices: {e}")

    return devices


__all__ = [
    "COREAUDIO_AVAILABLE",
    "get_usb_audio_device_names",
    "get_all_audio_input_devices",
]
