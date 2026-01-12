"""
Audio device scanner using sounddevice.

Discovers USB microphones and other audio input devices.
Follows the same pattern as USBScanner and NetworkScanner for consistency.
"""

import asyncio
import sys
from dataclasses import dataclass
from typing import Callable, Optional, Dict, Set, Awaitable, TYPE_CHECKING

if TYPE_CHECKING:
    from .master_registry import MasterDeviceRegistry

from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger("AudioScanner")

# Try to import sounddevice - it's optional
try:
    import sounddevice as sd
    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    SOUNDDEVICE_AVAILABLE = False
    logger.warning("sounddevice not available - audio device discovery disabled")


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


class AudioScanner:
    """
    Continuously scans for audio input devices using sounddevice.

    Discovers USB microphones by filtering for devices with "usb" in the name.

    Usage:
        scanner = AudioScanner(
            on_device_found=handle_found,
            on_device_lost=handle_lost,
        )
        await scanner.start()
        # ... later ...
        await scanner.stop()
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
        """Re-emit discovery events for all known devices.

        Call this when a connection type gets enabled to re-announce
        devices that were previously discovered but ignored.
        """
        logger.debug(f"Re-announcing {len(self._known_devices)} audio devices")
        for device in self._known_devices.values():
            if self._on_device_found:
                try:
                    await self._on_device_found(device)
                except Exception as e:
                    logger.error(f"Error re-announcing device: {e}")

    async def _scan_loop(self) -> None:
        """Main scanning loop.

        On Windows, the USBHotplugMonitor triggers force_scan() when USB
        devices change, so we don't need to continuously poll.

        On Linux, we continue polling since sounddevice query is lightweight.
        """
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
            # Run blocking query_devices() in thread
            devices = await asyncio.to_thread(sd.query_devices)
            current_indices: Set[int] = set()

            for index, info in enumerate(devices):
                # Only interested in input devices
                channels = int(info.get("max_input_channels", 0) or 0)
                if channels <= 0:
                    continue

                name = str(info.get("name") or f"Device {index}")

                # Filter for USB devices only
                if "usb" not in name.lower():
                    continue

                # Check if this device should be excluded (e.g., webcam mic)
                if self._exclude_filter and self._exclude_filter(index):
                    logger.debug(f"Excluding audio device {index} ({name}) - filtered")
                    continue

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
        """Set or update the exclusion filter.

        This allows dynamically filtering out certain audio devices,
        such as webcam microphones which are managed by the camera module.

        Args:
            filter_fn: Callback that returns True if an index should be excluded.
                       Pass None to disable filtering.
        """
        self._exclude_filter = filter_fn

    def set_registry_filter(self, registry: "MasterDeviceRegistry") -> None:
        """Set up filtering using a MasterDeviceRegistry.

        Automatically excludes audio devices that are webcam microphones,
        based on the registry's knowledge of which devices are webcams.

        Args:
            registry: The MasterDeviceRegistry to check for webcam mics.
        """
        self._exclude_filter = registry.is_audio_index_webcam_mic
        logger.debug("Audio scanner now filtering webcam mics via registry")
