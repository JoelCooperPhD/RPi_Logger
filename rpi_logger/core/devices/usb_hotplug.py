"""
USB Hotplug Monitor - Detects USB device changes without polling hardware.

On Windows, polling USB cameras with cv2.VideoCapture() causes:
- Camera lights to flash
- Cameras in use to disappear from discovery
- Excessive CPU usage and delays

This monitor provides a lightweight alternative:
- Counts USB devices periodically (very fast, no hardware interaction)
- Only notifies subscribers when the count changes
- Subscribers then do their specific device discovery

This matches the approach used by RS_Logger which works reliably on Windows.
"""

import asyncio
import sys
from typing import Callable, List, Awaitable, Optional

from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger("USBHotplugMonitor")

USBChangeCallback = Callable[[], Awaitable[None]]


def count_usb_devices() -> int:
    """Count connected USB devices (lightweight check).

    This does NOT interact with hardware - it just counts enumerated devices.
    On Windows, this uses serial port enumeration which is very fast.
    On Linux, this reads /sys/bus/usb/devices which is also lightweight.
    """
    if sys.platform == "win32":
        return _count_usb_devices_windows()
    else:
        return _count_usb_devices_linux()


def _count_usb_devices_windows() -> int:
    """Count USB devices on Windows using serial ports + basic device count.

    Uses serial.tools.list_ports which is lightweight and doesn't
    activate any hardware. This provides a fast way to detect when
    USB devices are plugged/unplugged.
    """
    try:
        import serial.tools.list_ports
        # Count serial COM ports - this is very fast
        serial_count = len(list(serial.tools.list_ports.comports()))
        return serial_count
    except Exception as e:
        logger.debug(f"Error counting Windows USB devices: {e}")
        return 0


def _count_usb_devices_linux() -> int:
    """Count USB devices on Linux via /sys/bus/usb/devices.

    This reads the sysfs filesystem which is a kernel interface -
    no hardware interaction required.
    """
    from pathlib import Path
    try:
        usb_path = Path("/sys/bus/usb/devices")
        if usb_path.exists():
            # Count only real USB devices (format: X-Y or X-Y.Z, not usb1, usb2, etc.)
            devices = [
                d for d in usb_path.iterdir()
                if d.is_dir() and "-" in d.name
            ]
            return len(devices)
        return 0
    except Exception as e:
        logger.debug(f"Error counting Linux USB devices: {e}")
        return 0


class USBHotplugMonitor:
    """
    Monitors for USB device changes and notifies subscribers.

    Instead of each scanner polling hardware, this monitor:
    1. Tracks USB device count (very lightweight)
    2. Only notifies scanners when count changes
    3. Scanners then do their specific discovery

    This eliminates the problems caused by continuous hardware polling:
    - Camera lights flashing
    - Cameras disappearing when in use
    - Slow startup from repeated OpenCV probing

    Usage:
        monitor = USBHotplugMonitor()
        monitor.subscribe(my_scanner.force_scan)
        await monitor.start()
        # ... scanners only rescan when USB changes detected
        await monitor.stop()
    """

    # Check interval - how often to count USB devices
    # This is very fast (< 1ms) so we can check frequently
    DEFAULT_CHECK_INTERVAL = 1.0

    def __init__(self, check_interval: float = DEFAULT_CHECK_INTERVAL):
        """Initialize the USB hotplug monitor.

        Args:
            check_interval: How often to check USB device count (seconds).
                           Default is 1 second which is lightweight.
        """
        self._check_interval = check_interval
        self._last_count = 0
        self._subscribers: List[USBChangeCallback] = []
        self._running = False
        self._task: Optional[asyncio.Task] = None

    @property
    def is_running(self) -> bool:
        """Check if the monitor is running."""
        return self._running

    @property
    def device_count(self) -> int:
        """Get the last known USB device count."""
        return self._last_count

    def subscribe(self, callback: USBChangeCallback) -> None:
        """Register a callback to be notified on USB device changes.

        The callback should be an async function that triggers
        the scanner's device discovery.

        Args:
            callback: Async function to call when USB devices change.
        """
        if callback not in self._subscribers:
            self._subscribers.append(callback)
            logger.debug(f"USB hotplug subscriber added (total: {len(self._subscribers)})")

    def unsubscribe(self, callback: USBChangeCallback) -> None:
        """Remove a callback from notifications.

        Args:
            callback: The callback to remove.
        """
        if callback in self._subscribers:
            self._subscribers.remove(callback)
            logger.debug(f"USB hotplug subscriber removed (total: {len(self._subscribers)})")

    async def start(self) -> None:
        """Start monitoring for USB device changes.

        Performs an initial device count and starts the monitoring loop.
        """
        if self._running:
            return

        self._running = True

        # Get initial count (run in thread to not block event loop)
        self._last_count = await asyncio.to_thread(count_usb_devices)
        logger.info(f"USB hotplug monitor started (initial count: {self._last_count})")

        # Start the monitoring loop
        self._task = asyncio.create_task(self._monitor_loop())

    async def stop(self) -> None:
        """Stop monitoring for USB device changes."""
        if not self._running:
            return

        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        logger.info("USB hotplug monitor stopped")

    async def _monitor_loop(self) -> None:
        """Main monitoring loop - checks device count periodically.

        When the count changes, notifies all subscribers so they can
        run their specific device discovery.
        """
        while self._running:
            try:
                await asyncio.sleep(self._check_interval)

                # Count USB devices (lightweight, runs in thread)
                current_count = await asyncio.to_thread(count_usb_devices)

                if current_count != self._last_count:
                    change = current_count - self._last_count
                    direction = "added" if change > 0 else "removed"
                    logger.info(
                        f"USB change detected: {self._last_count} -> {current_count} "
                        f"({abs(change)} device(s) {direction})"
                    )
                    self._last_count = current_count

                    # Notify all subscribers
                    await self._notify_subscribers()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in USB hotplug monitor: {e}")

    async def _notify_subscribers(self) -> None:
        """Notify all subscribers of a USB device change.

        Calls each subscriber's callback (typically a scanner's force_scan).
        Errors in one callback don't prevent others from being called.
        """
        for callback in self._subscribers:
            try:
                await callback()
            except Exception as e:
                logger.error(f"Error in USB hotplug callback: {e}")

    async def trigger_rescan(self) -> None:
        """Manually trigger a rescan notification to all subscribers.

        Useful for forcing a refresh without waiting for hardware changes.
        """
        logger.debug("Manual USB rescan triggered")
        await self._notify_subscribers()


__all__ = ["USBHotplugMonitor", "count_usb_devices"]
