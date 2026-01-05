"""
Physical ID Resolution - Links device interfaces by USB bus path.

On Linux, USB devices can be identified by their bus path, which is stable
across reboots as long as the device stays in the same physical port.

This module provides utilities to resolve the physical ID (USB bus path)
for various device types (video, audio, serial), enabling us to group
multiple interfaces belonging to the same physical device.

Example:
    A webcam plugged into USB port 1-2 might have:
    - Video at /dev/video0 (sysfs shows bus path 1-2)
    - Audio at ALSA card 2 (sysfs shows bus path 1-2)

    Both resolve to physical_id="1-2", so we know they're the same device.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from rpi_logger.core.logging_utils import get_module_logger

if TYPE_CHECKING:
    pass

logger = get_module_logger("PhysicalIdResolver")


class USBPhysicalIdResolver:
    """
    Resolves USB bus paths for device interfaces.

    USB devices are identified by their bus/port path, e.g., "1-2" means
    bus 1, port 2. Compound paths like "1-2.3" indicate hub hierarchies.

    This path is shared by all interfaces of the same physical device,
    enabling us to link video and audio interfaces.
    """

    @staticmethod
    def from_video_device(dev_path: str) -> str | None:
        """
        Get USB bus path from a video device.

        Args:
            dev_path: Video device path, e.g., "/dev/video0"

        Returns:
            USB bus path like "1-2" or "1-2.1", or None if not USB
        """
        try:
            video_name = Path(dev_path).name
            sysfs_path = Path(f"/sys/class/video4linux/{video_name}/device")

            if not sysfs_path.exists():
                logger.debug("No sysfs path for %s", dev_path)
                return None

            resolved = sysfs_path.resolve()

            if not _is_usb_path(resolved):
                logger.debug("%s is not a USB device", dev_path)
                return None

            return _extract_usb_bus_path(resolved)

        except Exception as e:
            logger.debug("Could not resolve USB path for %s: %s", dev_path, e)
            return None

    @staticmethod
    def from_alsa_card(card_index: int) -> str | None:
        """
        Get USB bus path from an ALSA card index.

        Args:
            card_index: ALSA card number (e.g., 2 for hw:2,0)

        Returns:
            USB bus path like "1-2", or None if not USB
        """
        try:
            sysfs_path = Path(f"/sys/class/sound/card{card_index}/device")

            if not sysfs_path.exists():
                logger.debug("No sysfs path for ALSA card %d", card_index)
                return None

            resolved = sysfs_path.resolve()

            if not _is_usb_path(resolved):
                logger.debug("ALSA card %d is not USB", card_index)
                return None

            return _extract_usb_bus_path(resolved)

        except Exception as e:
            logger.debug("Could not resolve USB path for ALSA card %d: %s", card_index, e)
            return None

    @staticmethod
    def from_sounddevice_index(sd_index: int) -> str | None:
        """
        Get USB bus path from a sounddevice index.

        This requires mapping sounddevice index -> ALSA card -> USB path.

        Args:
            sd_index: sounddevice device index

        Returns:
            USB bus path, or None if not USB or cannot resolve
        """
        try:
            import sounddevice as sd
            devices = sd.query_devices()

            if sd_index >= len(devices):
                return None

            device_info = devices[sd_index]
            device_name = device_info.get("name", "")

            # Try to extract ALSA card number from device name
            alsa_card = _extract_alsa_card_from_name(device_name)
            if alsa_card is not None:
                return USBPhysicalIdResolver.from_alsa_card(alsa_card)

            # Fallback: try to find by iterating ALSA cards and matching names
            return _find_alsa_card_by_name_match(device_name)

        except ImportError:
            logger.debug("sounddevice not available")
            return None
        except Exception as e:
            logger.debug("Could not resolve USB path for sounddevice %d: %s", sd_index, e)
            return None

    @staticmethod
    def from_serial_port(port: str) -> str | None:
        """
        Get USB bus path from a serial port.

        Args:
            port: Serial port path, e.g., "/dev/ttyUSB0" or "/dev/ttyACM0"

        Returns:
            USB bus path, or None if not USB
        """
        try:
            tty_name = Path(port).name
            sysfs_path = Path(f"/sys/class/tty/{tty_name}/device")

            if not sysfs_path.exists():
                logger.debug("No sysfs path for %s", port)
                return None

            resolved = sysfs_path.resolve()

            if not _is_usb_path(resolved):
                logger.debug("%s is not a USB device", port)
                return None

            return _extract_usb_bus_path(resolved)

        except Exception as e:
            logger.debug("Could not resolve USB path for %s: %s", port, e)
            return None

    @staticmethod
    def find_audio_sibling_for_video(dev_path: str) -> dict | None:
        """
        Find the audio device that's a sibling of a video device.

        This is the key method for webcam audio detection - given a video
        device path, find if there's an audio device on the same USB bus path.

        Args:
            dev_path: Video device path, e.g., "/dev/video0"

        Returns:
            Dict with audio device info if found:
            {
                "sounddevice_index": int,
                "alsa_card": int,
                "channels": int,
                "sample_rate": float,
                "name": str,
            }
            Or None if no audio sibling found.
        """
        video_bus_path = USBPhysicalIdResolver.from_video_device(dev_path)
        if not video_bus_path:
            return None

        logger.debug("Looking for audio sibling of %s (bus path: %s)", dev_path, video_bus_path)

        try:
            import sounddevice as sd
            devices = sd.query_devices()

            for idx, device_info in enumerate(devices):
                # Only check input devices
                if device_info.get("max_input_channels", 0) <= 0:
                    continue

                # Check if this device has same USB bus path
                audio_bus_path = USBPhysicalIdResolver.from_sounddevice_index(idx)
                if audio_bus_path == video_bus_path:
                    logger.info(
                        "Found audio sibling for %s: index=%d, name=%s",
                        dev_path, idx, device_info.get("name", "")
                    )
                    return {
                        "sounddevice_index": idx,
                        "alsa_card": _extract_alsa_card_from_name(device_info.get("name", "")),
                        "channels": device_info.get("max_input_channels", 2),
                        "sample_rate": device_info.get("default_samplerate", 48000.0),
                        "name": device_info.get("name", ""),
                    }

        except ImportError:
            logger.debug("sounddevice not available for audio sibling detection")
        except Exception as e:
            logger.debug("Error finding audio sibling: %s", e)

        return None


def _is_usb_path(sysfs_path: Path) -> bool:
    """Check if a sysfs path represents a USB device."""
    return any("usb" in part.lower() for part in sysfs_path.parts)


def _extract_usb_bus_path(sysfs_path: Path) -> str | None:
    """
    Extract the USB bus path from a sysfs path.

    The sysfs path looks like:
    /sys/devices/pci.../usb1/1-2/1-2:1.0/...

    We want "1-2" (the device node, not the interface "1-2:1.0").
    """
    # Walk up to find the USB device node
    # Device nodes look like "1-2" or "1-2.3" (no colon)
    # Interface nodes look like "1-2:1.0" (have a colon)

    current = sysfs_path
    while current.parent != current:
        name = current.name

        # Skip interface nodes (have colon)
        if ":" in name:
            current = current.parent
            continue

        # Check if this looks like a USB device node (digit-digit pattern)
        if re.match(r"^\d+-[\d.]+$", name):
            return name

        # Check if parent is a USB root (usbN)
        if current.parent.name.startswith("usb"):
            return name

        current = current.parent

    return None


def _extract_alsa_card_from_name(device_name: str) -> int | None:
    """
    Extract ALSA card number from device name string.

    Device names from sounddevice/PortAudio often contain the hw:X format.
    Examples:
        "HD Pro Webcam C920: USB Audio (hw:2,0)" -> 2
        "USB Audio Device (hw:3,0)" -> 3
    """
    match = re.search(r"hw:(\d+)", device_name)
    if match:
        return int(match.group(1))
    return None


def _find_alsa_card_by_name_match(device_name: str) -> str | None:
    """
    Find ALSA card by matching device name.

    Fallback when we can't extract hw:X from the name.
    Reads /proc/asound/cards and tries to match.
    """
    try:
        cards_path = Path("/proc/asound/cards")
        if not cards_path.exists():
            return None

        content = cards_path.read_text()

        # Parse card entries - format is:
        # " 0 [PCH            ]: HDA-Intel - HDA Intel PCH"
        # " 2 [C920           ]: USB-Audio - HD Pro Webcam C920"
        for line in content.split("\n"):
            match = re.match(r"\s*(\d+)\s+\[", line)
            if match:
                card_num = int(match.group(1))
                # Check if device name appears in this line (case-insensitive)
                if device_name.lower() in line.lower():
                    return USBPhysicalIdResolver.from_alsa_card(card_num)

        return None

    except Exception:
        return None


def get_all_usb_audio_bus_paths() -> dict[int, str]:
    """
    Get USB bus paths for all USB audio devices.

    Returns:
        Dict mapping sounddevice index to USB bus path.
        Only includes USB audio devices.
    """
    result = {}
    try:
        import sounddevice as sd
        devices = sd.query_devices()

        for idx, device_info in enumerate(devices):
            if device_info.get("max_input_channels", 0) <= 0:
                continue

            bus_path = USBPhysicalIdResolver.from_sounddevice_index(idx)
            if bus_path:
                result[idx] = bus_path

    except ImportError:
        pass
    except Exception as e:
        logger.debug("Error getting USB audio bus paths: %s", e)

    return result
