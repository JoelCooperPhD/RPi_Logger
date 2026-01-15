"""
Audio device scanner using sounddevice.

Discovers USB microphones and other audio input devices.
"""

import asyncio
import csv
import io
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, Optional, Dict, Set, Awaitable

from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger("AudioScanner")

# Try to import sounddevice - it's optional
try:
    import sounddevice as sd
    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    SOUNDDEVICE_AVAILABLE = False
    logger.warning("sounddevice not available - audio device discovery disabled")

# Try to import macOS CoreAudio utilities for USB device detection
COREAUDIO_AVAILABLE = False
if sys.platform == "darwin":
    try:
        from .coreaudio_utils import get_usb_audio_device_names, COREAUDIO_AVAILABLE
        COREAUDIO_AVAILABLE = True
    except ImportError as e:
        logger.debug(f"CoreAudio utilities not available: {e}")


@dataclass
class DiscoveredAudioDevice:
    """Represents a discovered audio input device."""
    device_id: str           # Unique ID (e.g., "audio_0")
    sounddevice_index: int   # Index in sounddevice
    name: str                # Device name from sounddevice
    channels: int            # Max input channels
    sample_rate: float       # Default sample rate


# Type alias for callbacks
AudioDeviceFoundCallback = Callable[[DiscoveredAudioDevice], Awaitable[None]]
AudioDeviceLostCallback = Callable[[str], Awaitable[None]]  # device_id

# Filter callback type - returns True if audio index should be excluded
AudioIndexFilterCallback = Callable[[int], bool]

# Windows subprocess flag to hide console window
_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _get_windows_webcam_audio_indices() -> Set[int]:
    """
    Get sounddevice indices of audio devices that belong to webcams (Windows only).

    This queries WMI for USB video and audio devices, matches them by VID:PID,
    and returns the sounddevice indices of audio devices that share a VID:PID
    with any video device (i.e., webcam microphones).

    Returns:
        Set of sounddevice indices that are webcam microphones.
    """
    if sys.platform != "win32":
        return set()

    if not SOUNDDEVICE_AVAILABLE:
        return set()

    webcam_audio_indices: Set[int] = set()

    try:
        # Get VID:PIDs of all video/camera devices
        video_vid_pids = _query_windows_video_vid_pids()
        if not video_vid_pids:
            logger.debug("No video devices found for webcam mic detection")
            return set()

        logger.debug(f"Found video device VID:PIDs: {video_vid_pids}")

        # Get USB audio devices with their VID:PIDs
        audio_devices = _query_windows_audio_devices()
        if not audio_devices:
            logger.debug("No USB audio devices found")
            return set()

        # Identify webcam audio devices (those with VID:PID matching video devices)
        webcam_audio_names: list[str] = []
        for audio_dev in audio_devices:
            vid_pid = audio_dev.get("vid_pid", "")
            if vid_pid and vid_pid in video_vid_pids:
                webcam_audio_names.append(audio_dev.get("name", ""))
                logger.debug(
                    f"Webcam audio device: {audio_dev.get('name')} (VID:PID {vid_pid})"
                )

        if not webcam_audio_names:
            logger.debug("No webcam audio devices found")
            return set()

        # Find ALL sounddevice indices that match webcam audio device names
        sd_devices = sd.query_devices()

        for sd_idx, sd_dev in enumerate(sd_devices):
            if sd_dev.get("max_input_channels", 0) <= 0:
                continue

            sd_name = sd_dev.get("name", "")

            # Check if this sounddevice matches any webcam audio device name
            for webcam_name in webcam_audio_names:
                if _names_match(sd_name, webcam_name):
                    webcam_audio_indices.add(sd_idx)
                    logger.info(
                        f"Detected webcam mic: sounddevice {sd_idx} "
                        f"'{sd_name}' matches '{webcam_name}'"
                    )
                    break

    except Exception as e:
        logger.warning(f"Error detecting webcam mics: {e}")

    return webcam_audio_indices


def _names_match(name1: str, name2: str) -> bool:
    """Check if two device names likely refer to the same device."""
    n1 = name1.lower()
    n2 = name2.lower()

    # Check if one name contains the other (common on Windows where
    # sounddevice shows "Microphone (HD Pro Webcam C920)" and WMI shows "HD Pro Webcam C920")
    if n2 in n1 or n1 in n2:
        return True

    # Extract significant words (4+ chars, excluding generic terms)
    generic = {"microphone", "audio", "device", "usb", "input", "output", "sound"}
    words1 = {w for w in re.findall(r'\b\w{4,}\b', n1) if w not in generic}
    words2 = {w for w in re.findall(r'\b\w{4,}\b', n2) if w not in generic}

    # If either has no significant words, can't match
    if not words1 or not words2:
        return False

    # Check for overlapping words
    return bool(words1 & words2)


def _query_windows_video_vid_pids() -> Set[str]:
    """Query Windows for VID:PIDs of all video/camera devices."""
    vid_pids: Set[str] = set()

    try:
        # PowerShell query for Camera and Image class devices
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                "Get-PnpDevice -Class Camera,Image -Status OK 2>$null | "
                "Select-Object InstanceId | "
                "ConvertTo-Csv -NoTypeInformation"
            ],
            capture_output=True, text=True, timeout=10,
            creationflags=_SUBPROCESS_FLAGS
        )
        if result.returncode == 0 and result.stdout.strip():
            for line in result.stdout.strip().split("\n")[1:]:  # Skip header
                line = line.strip().strip('"')
                vid_pid = _extract_vid_pid(line)
                if vid_pid:
                    vid_pids.add(vid_pid)
    except Exception as e:
        logger.debug(f"PowerShell video query failed: {e}")

    return vid_pids


def _query_windows_audio_devices() -> list:
    """Query Windows for USB audio devices with their VID:PIDs."""
    devices = []

    try:
        # PowerShell query for MEDIA class USB devices
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                "Get-PnpDevice -Class MEDIA -Status OK 2>$null | "
                "Where-Object { $_.InstanceId -like '*VID_*' } | "
                "Select-Object InstanceId,FriendlyName | "
                "ConvertTo-Csv -NoTypeInformation"
            ],
            capture_output=True, text=True, timeout=10,
            creationflags=_SUBPROCESS_FLAGS
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split("\n")
            if len(lines) > 1:
                reader = csv.DictReader(io.StringIO("\n".join(lines)))
                for row in reader:
                    instance_id = row.get("InstanceId", "")
                    friendly_name = row.get("FriendlyName", "")
                    vid_pid = _extract_vid_pid(instance_id)
                    if vid_pid:
                        devices.append({
                            "name": friendly_name,
                            "vid_pid": vid_pid,
                        })
    except Exception as e:
        logger.debug(f"PowerShell audio query failed: {e}")

    return devices


def _extract_vid_pid(device_id: str) -> str:
    """Extract VID:PID from Windows device ID (e.g., USB\\VID_046D&PID_0825\\...)."""
    match = re.search(r"VID_([0-9A-Fa-f]{4})&PID_([0-9A-Fa-f]{4})", device_id)
    if match:
        return f"{match.group(1).lower()}:{match.group(2).lower()}"
    return ""


class AudioScanner:
    """
    Continuously scans for audio input devices using sounddevice.

    Discovers hardware microphones, filtering out virtual/software devices:
    - Windows/Linux: requires "usb" in device name
    - macOS: uses CoreAudio transport type (USB + Built-in, excludes Virtual)

    Also filters out:
    - Webcam microphones (via VID:PID matching on Windows)
    - Duplicate entries (same device via different audio APIs)
    """

    DEFAULT_SCAN_INTERVAL = 2.0  # Scan every 2 seconds
    DEFAULT_SAMPLE_RATE = 44100

    def __init__(
        self,
        scan_interval: float = DEFAULT_SCAN_INTERVAL,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        on_device_found: Optional[AudioDeviceFoundCallback] = None,
        on_device_lost: Optional[AudioDeviceLostCallback] = None,
        exclude_filter: Optional[AudioIndexFilterCallback] = None,
    ):
        self._scan_interval = scan_interval
        self._sample_rate = sample_rate
        self._on_device_found = on_device_found
        self._on_device_lost = on_device_lost
        self._exclude_filter = exclude_filter

        self._known_devices: Dict[str, DiscoveredAudioDevice] = {}
        self._known_indices: Set[int] = set()
        self._scan_task: Optional[asyncio.Task] = None
        self._running = False

        # Cache of webcam audio indices detected via VID:PID (Windows only)
        self._webcam_audio_indices: Set[int] = set()

        # Cache of USB audio device names detected via CoreAudio (macOS only)
        self._macos_usb_device_names: Set[str] = set()

    @property
    def devices(self) -> Dict[str, DiscoveredAudioDevice]:
        """Get currently known devices (device_id -> device)."""
        return dict(self._known_devices)

    @property
    def is_running(self) -> bool:
        """Check if scanner is running."""
        return self._running

    async def start(self) -> None:
        """Start audio device scanning."""
        if self._running:
            return

        if not SOUNDDEVICE_AVAILABLE:
            logger.warning("Cannot start audio scanner - sounddevice not available")
            return

        self._running = True

        # Perform initial scan immediately
        await self._scan_devices()

        # Start continuous scanning
        self._scan_task = asyncio.create_task(self._scan_loop())
        logger.info("Audio scanner started")

    async def stop(self) -> None:
        """Stop audio device scanning."""
        if not self._running:
            return

        self._running = False

        if self._scan_task:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass
            self._scan_task = None

        # Notify about lost devices
        for device_id in list(self._known_devices.keys()):
            if self._on_device_lost:
                try:
                    await self._on_device_lost(device_id)
                except Exception as e:
                    logger.error(f"Error in device lost callback: {e}")

        self._known_devices.clear()
        self._known_indices.clear()
        logger.info("Audio scanner stopped")

    async def force_scan(self) -> None:
        """Force an immediate scan."""
        if self._running:
            await self._scan_devices()

    async def reannounce_devices(self) -> None:
        """Re-emit discovery events for all known devices."""
        logger.debug(f"Re-announcing {len(self._known_devices)} audio devices")
        for device in self._known_devices.values():
            if self._on_device_found:
                try:
                    await self._on_device_found(device)
                except Exception as e:
                    logger.error(f"Error re-announcing device: {e}")

    async def _scan_loop(self) -> None:
        """Main scanning loop."""
        # Windows: Don't continuously poll - wait for hotplug events
        if sys.platform == "win32":
            while self._running:
                try:
                    await asyncio.sleep(60)  # Heartbeat - no active scanning
                except asyncio.CancelledError:
                    break
            return

        # Linux/macOS: Continue polling
        while self._running:
            try:
                await asyncio.sleep(self._scan_interval)
                await self._scan_devices()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in audio scan loop: {e}")

    async def _scan_devices(self) -> None:
        """Scan for audio input devices and detect changes."""
        if not SOUNDDEVICE_AVAILABLE:
            return

        try:
            # Platform-specific USB device detection
            if sys.platform == "win32":
                # On Windows, detect webcam mics via VID:PID matching
                self._webcam_audio_indices = await asyncio.to_thread(
                    _get_windows_webcam_audio_indices
                )
                if self._webcam_audio_indices:
                    logger.debug(
                        f"Windows webcam mic indices: {self._webcam_audio_indices}"
                    )
            elif sys.platform == "darwin" and COREAUDIO_AVAILABLE:
                # On macOS, use CoreAudio to identify hardware audio devices
                # (USB + Built-in, excluding Virtual/Aggregate)
                self._macos_usb_device_names = await asyncio.to_thread(
                    get_usb_audio_device_names
                )
                if self._macos_usb_device_names:
                    logger.debug(
                        f"macOS hardware audio devices: {self._macos_usb_device_names}"
                    )

            # Run blocking query_devices() in thread
            devices = await asyncio.to_thread(sd.query_devices)
            current_indices: Set[int] = set()

            # Track seen device names to show only one entry per physical device
            # (Windows exposes same device via multiple APIs: MME, DirectSound, WASAPI, WDM-KS)
            seen_device_names: Set[str] = set()

            for index, info in enumerate(devices):
                # Only interested in input devices
                channels = int(info.get("max_input_channels", 0) or 0)
                if channels <= 0:
                    continue

                name = str(info.get("name") or f"Device {index}")

                # Filter for USB devices only (platform-specific)
                if sys.platform == "darwin" and COREAUDIO_AVAILABLE:
                    # macOS: Use CoreAudio transport type detection
                    if name not in self._macos_usb_device_names:
                        continue
                else:
                    # Windows/Linux: Check for "usb" in name
                    if "usb" not in name.lower():
                        continue

                # Windows: Check if this is a webcam mic (detected via VID:PID)
                if index in self._webcam_audio_indices:
                    logger.debug(
                        f"Excluding webcam mic {index} ({name}) - VID:PID matches camera"
                    )
                    continue

                # Check if this device should be excluded (e.g., webcam mic on Linux)
                if self._exclude_filter and self._exclude_filter(index):
                    logger.debug(f"Excluding audio device {index} ({name}) - filtered")
                    continue

                # Only show one entry per physical device (first one wins, typically MME)
                if name in seen_device_names:
                    logger.debug(f"Skipping duplicate device {index} ({name})")
                    continue
                seen_device_names.add(name)

                current_indices.add(index)

                # Skip if already known
                if index in self._known_indices:
                    continue

                # Get sample rate
                sample_rate = float(info.get("default_samplerate") or self._sample_rate)

                # Generate unique device ID
                device_id = f"audio_{index}"

                # New device discovered
                device = DiscoveredAudioDevice(
                    device_id=device_id,
                    sounddevice_index=index,
                    name=name,
                    channels=channels,
                    sample_rate=sample_rate,
                )

                self._known_devices[device_id] = device
                self._known_indices.add(index)
                logger.info(f"Audio device found: {name} (index={index}, channels={channels})")

                if self._on_device_found:
                    try:
                        await self._on_device_found(device)
                    except Exception as e:
                        logger.error(f"Error in device found callback: {e}")

            # Check for disconnected devices
            lost_indices = self._known_indices - current_indices
            for index in lost_indices:
                device_id = f"audio_{index}"
                device = self._known_devices.pop(device_id, None)
                self._known_indices.discard(index)

                if device:
                    logger.info(f"Audio device lost: {device.name} (index={index})")

                    if self._on_device_lost:
                        try:
                            await self._on_device_lost(device_id)
                        except Exception as e:
                            logger.error(f"Error in device lost callback: {e}")

        except Exception as e:
            logger.error(f"Error scanning audio devices: {e}")

    def get_device(self, device_id: str) -> Optional[DiscoveredAudioDevice]:
        """Get a specific device by ID."""
        return self._known_devices.get(device_id)

    def get_device_by_index(self, index: int) -> Optional[DiscoveredAudioDevice]:
        """Get a device by its sounddevice index."""
        device_id = f"audio_{index}"
        return self._known_devices.get(device_id)

    def set_exclude_filter(self, filter_fn: Optional[AudioIndexFilterCallback]) -> None:
        """Set or update the exclusion filter."""
        self._exclude_filter = filter_fn


__all__ = [
    "AudioScanner",
    "DiscoveredAudioDevice",
    "AudioDeviceFoundCallback",
    "AudioDeviceLostCallback",
    "AudioIndexFilterCallback",
    "SOUNDDEVICE_AVAILABLE",
]
