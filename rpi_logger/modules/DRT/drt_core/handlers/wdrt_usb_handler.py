"""wDRT Handler for USB and Wireless devices."""

from pathlib import Path
from typing import Any, Optional
import asyncio

from .wdrt_base_handler import WDRTBaseHandler
from ..device_types import DRTDeviceType


class WDRTUSBHandler(WDRTBaseHandler):
    """Handler for wDRT devices (USB or Wireless)."""

    def __init__(
        self,
        device_id: str,
        output_dir: Path,
        transport: Any,
        device_type: DRTDeviceType = DRTDeviceType.WDRT_USB
    ):
        super().__init__(device_id, output_dir, transport)
        self._device_type = device_type
        self._rtc_synced = False

    @property
    def device_type(self) -> DRTDeviceType:
        return self._device_type

    @property
    def node_id(self) -> str:
        """XBee node ID for wireless devices."""
        return self.device_id

    async def start(self) -> None:
        await super().start()
        await self.send_command('stop')

        if not self._rtc_synced:
            await self.sync_rtc()
            self._rtc_synced = True

        self._start_battery_polling()

    async def get_battery(self) -> Optional[int]:
        """Request battery with wireless-compatible delay."""
        if await self.send_command('get_battery'):
            delay = 0.3 if self._device_type == DRTDeviceType.WDRT_WIRELESS else 0.2
            await asyncio.sleep(delay)
            return self._battery_percent
        return None

    def _format_device_id_for_csv(self) -> str:
        port_clean = self.device_id.lstrip('/').replace('/', '_').lower()
        return f"wDRT_{port_clean}"


# Alias for backward compatibility
WDRTWirelessHandler = WDRTUSBHandler
