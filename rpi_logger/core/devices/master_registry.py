"""
Master Device Registry - Single source of truth for physical devices.

The registry aggregates capabilities discovered by various scanners into
MasterDevice instances, grouped by physical_id (USB bus path, etc.).

This enables:
1. Linking video and audio interfaces of the same physical device
2. Querying devices by capability (webcams, audio-only devices, etc.)
3. Filtering webcam mics from the standalone audio device list
"""

from __future__ import annotations

import time
from typing import Callable

from rpi_logger.core.logging_utils import get_module_logger

from .master_device import (
    MasterDevice,
    DeviceCapability,
    CapabilityInfo,
    PhysicalInterface,
)

logger = get_module_logger("MasterDeviceRegistry")

# Type alias for capability change observers
CapabilityObserver = Callable[[str, DeviceCapability, bool], None]


class MasterDeviceRegistry:
    """
    Single source of truth for all physical devices and their capabilities.

    Scanners register capabilities they discover. The registry aggregates
    these into MasterDevice instances grouped by physical_id.

    Usage:
        registry = MasterDeviceRegistry()

        # Camera scanner discovers webcam video
        registry.register_capability(
            physical_id="1-2",
            capability=DeviceCapability.VIDEO_USB,
            info=VideoUSBCapability(dev_path="/dev/video0", stable_id="1-2"),
            display_name="Logitech C920",
        )

        # Camera scanner also found audio sibling
        registry.register_capability(
            physical_id="1-2",
            capability=DeviceCapability.AUDIO_INPUT,
            info=AudioInputCapability(sounddevice_index=3, channels=2),
        )

        # Query
        webcams = registry.get_webcams()  # [MasterDevice with video+audio]
        audio_only = registry.get_standalone_audio_devices()  # []
    """

    def __init__(self) -> None:
        self._devices: dict[str, MasterDevice] = {}
        self._observers: list[CapabilityObserver] = []

    def register_capability(
        self,
        physical_id: str,
        capability: DeviceCapability,
        info: CapabilityInfo,
        display_name: str | None = None,
        physical_interface: PhysicalInterface = PhysicalInterface.USB,
        vendor_id: int | None = None,
        product_id: int | None = None,
    ) -> MasterDevice:
        """
        Register that a physical device has a capability.

        If the device doesn't exist yet, creates it.
        If it exists, adds the capability to it.

        Args:
            physical_id: Stable identifier for the physical device (USB bus path, etc.)
            capability: The capability type being registered
            info: Capability-specific metadata
            display_name: Human-readable name (optional, uses physical_id if not provided)
            physical_interface: How the device connects (USB, CSI, etc.)
            vendor_id: USB vendor ID (optional)
            product_id: USB product ID (optional)

        Returns:
            The MasterDevice (new or updated)
        """
        if physical_id not in self._devices:
            self._devices[physical_id] = MasterDevice(
                physical_id=physical_id,
                display_name=display_name or f"Device {physical_id}",
                physical_interface=physical_interface,
                vendor_id=vendor_id,
                product_id=product_id,
                capabilities={},
                first_seen=time.time(),
            )
            logger.debug("Created new MasterDevice: %s", physical_id)

        device = self._devices[physical_id]

        # Update display name if we got a better one
        if display_name and (device.display_name.startswith("Device ") or
                            device.display_name == physical_id):
            device.display_name = display_name

        # Update VID/PID if provided
        if vendor_id is not None and device.vendor_id is None:
            device.vendor_id = vendor_id
        if product_id is not None and device.product_id is None:
            device.product_id = product_id

        # Add or update capability
        was_new = capability not in device.capabilities
        device.capabilities[capability] = info

        if was_new:
            logger.debug(
                "Registered capability %s for device %s (%s)",
                capability.value, physical_id, device.display_name
            )
            self._notify(physical_id, capability, added=True)

        return device

    def unregister_capability(
        self,
        physical_id: str,
        capability: DeviceCapability,
    ) -> bool:
        """
        Remove a capability from a device.

        If no capabilities remain, removes the device entirely.

        Args:
            physical_id: The device's physical ID
            capability: The capability to remove

        Returns:
            True if capability was removed, False if not found
        """
        if physical_id not in self._devices:
            return False

        device = self._devices[physical_id]
        if capability not in device.capabilities:
            return False

        del device.capabilities[capability]
        logger.debug(
            "Unregistered capability %s from device %s",
            capability.value, physical_id
        )
        self._notify(physical_id, capability, added=False)

        # Remove device if no capabilities remain
        if not device.capabilities:
            del self._devices[physical_id]
            logger.debug("Removed empty device: %s", physical_id)

        return True

    def remove_device(self, physical_id: str) -> MasterDevice | None:
        """
        Remove a device entirely (all capabilities).

        Args:
            physical_id: The device's physical ID

        Returns:
            The removed device, or None if not found
        """
        device = self._devices.pop(physical_id, None)
        if device:
            for capability in list(device.capabilities.keys()):
                self._notify(physical_id, capability, added=False)
            logger.debug("Removed device: %s (%s)", physical_id, device.display_name)
        return device

    def clear(self) -> None:
        """Remove all devices from the registry."""
        for physical_id in list(self._devices.keys()):
            self.remove_device(physical_id)
        logger.debug("Registry cleared")

    # =========================================================================
    # Queries
    # =========================================================================

    def get_device(self, physical_id: str) -> MasterDevice | None:
        """Get a device by physical ID."""
        return self._devices.get(physical_id)

    def get_all_devices(self) -> list[MasterDevice]:
        """Get all registered devices."""
        return list(self._devices.values())

    def get_devices_with_capability(
        self,
        capability: DeviceCapability,
    ) -> list[MasterDevice]:
        """Get all devices that have a specific capability."""
        return [d for d in self._devices.values() if capability in d.capabilities]

    def get_webcams(self) -> list[MasterDevice]:
        """Get all USB webcams (with or without audio)."""
        return [d for d in self._devices.values() if d.is_webcam]

    def get_webcams_with_audio(self) -> list[MasterDevice]:
        """Get USB webcams that have built-in microphones."""
        return [d for d in self._devices.values() if d.is_webcam_with_mic]

    def get_csi_cameras(self) -> list[MasterDevice]:
        """Get CSI cameras (Raspberry Pi cameras)."""
        return [d for d in self._devices.values() if d.is_csi_camera]

    def get_all_video_devices(self) -> list[MasterDevice]:
        """Get all devices with video capability (USB or CSI)."""
        return [d for d in self._devices.values() if d.has_video]

    def get_standalone_audio_devices(self) -> list[MasterDevice]:
        """
        Get audio devices that are NOT part of a webcam.

        This is the key filter - webcam mics don't appear here,
        only standalone USB microphones and audio interfaces.
        """
        return [d for d in self._devices.values() if d.is_standalone_audio]

    def get_serial_devices(self, subtype: str | None = None) -> list[MasterDevice]:
        """
        Get serial devices, optionally filtered by subtype.

        Args:
            subtype: Optional filter ("drt", "vog", "gps")

        Returns:
            List of serial devices
        """
        result = []
        for device in self._devices.values():
            if device.is_serial:
                if subtype is None:
                    result.append(device)
                else:
                    serial_cap = device.serial_capability
                    if serial_cap and serial_cap.device_subtype == subtype:
                        result.append(device)
        return result

    def get_network_devices(self) -> list[MasterDevice]:
        """Get network devices."""
        return [d for d in self._devices.values() if d.is_network]

    def get_internal_devices(self) -> list[MasterDevice]:
        """Get internal (virtual) devices."""
        return [d for d in self._devices.values() if d.is_internal]

    # =========================================================================
    # Lookup by Interface Details
    # =========================================================================

    def find_device_by_audio_index(
        self,
        sounddevice_index: int,
    ) -> MasterDevice | None:
        """Find which device owns a specific sounddevice index."""
        for device in self._devices.values():
            audio_cap = device.audio_input_capability
            if audio_cap and audio_cap.sounddevice_index == sounddevice_index:
                return device
        return None

    def find_device_by_video_path(self, dev_path: str) -> MasterDevice | None:
        """Find which device owns a specific video device path."""
        from .master_device import VideoUSBCapability
        for device in self._devices.values():
            video_cap = device.video_capability
            if isinstance(video_cap, VideoUSBCapability) and video_cap.dev_path == dev_path:
                return device
        return None

    def find_device_by_serial_port(self, port: str) -> MasterDevice | None:
        """Find which device owns a specific serial port."""
        for device in self._devices.values():
            serial_cap = device.serial_capability
            if serial_cap and serial_cap.port == port:
                return device
        return None

    def is_audio_index_webcam_mic(self, sounddevice_index: int) -> bool:
        """
        Check if a sounddevice index belongs to a webcam's microphone.

        This is used by AudioScanner to filter out webcam mics.
        """
        device = self.find_device_by_audio_index(sounddevice_index)
        return device is not None and device.is_webcam_with_mic

    # =========================================================================
    # Observers
    # =========================================================================

    def add_observer(self, callback: CapabilityObserver) -> None:
        """
        Add observer for capability changes.

        The callback receives (physical_id, capability, added) where
        added is True for new capabilities, False for removals.
        """
        if callback not in self._observers:
            self._observers.append(callback)

    def remove_observer(self, callback: CapabilityObserver) -> None:
        """Remove a capability change observer."""
        if callback in self._observers:
            self._observers.remove(callback)

    def _notify(
        self,
        physical_id: str,
        capability: DeviceCapability,
        added: bool,
    ) -> None:
        """Notify observers of capability change."""
        for observer in self._observers:
            try:
                observer(physical_id, capability, added)
            except Exception as e:
                logger.warning("Observer error: %s", e)

    # =========================================================================
    # Debug
    # =========================================================================

    def __repr__(self) -> str:
        return f"MasterDeviceRegistry({len(self._devices)} devices)"

    def dump(self) -> str:
        """Return a debug dump of all devices and capabilities."""
        lines = [f"MasterDeviceRegistry: {len(self._devices)} devices"]
        for physical_id, device in sorted(self._devices.items()):
            lines.append(f"\n  {physical_id}: {device.display_name}")
            lines.append(f"    interface: {device.physical_interface.value}")
            if device.vendor_id or device.product_id:
                lines.append(f"    vid:pid: {device.vendor_id:04x}:{device.product_id:04x}")
            lines.append(f"    capabilities:")
            for cap_type, cap_info in device.capabilities.items():
                lines.append(f"      - {cap_type.value}: {cap_info}")
            lines.append(f"    is_webcam_with_mic: {device.is_webcam_with_mic}")
            lines.append(f"    is_standalone_audio: {device.is_standalone_audio}")
        return "\n".join(lines)
