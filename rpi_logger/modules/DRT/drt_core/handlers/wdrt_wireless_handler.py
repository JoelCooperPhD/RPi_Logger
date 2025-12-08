"""
wDRT Wireless Handler

Protocol handler for wDRT devices connected via XBee.
Uses the same protocol as wDRT USB but over wireless transport.
"""

import asyncio
from pathlib import Path
from typing import Any, Optional

from .wdrt_base_handler import WDRTBaseHandler
from ..device_types import DRTDeviceType


class WDRTWirelessHandler(WDRTBaseHandler):
    """Handler for wDRT devices connected via XBee wireless."""

    def __init__(
        self,
        device_id: str,
        output_dir: Path,
        transport: Any
    ):
        super().__init__(device_id, output_dir, transport)
        self._rtc_synced = False

    async def start(self) -> None:
        """Start the handler, reset device, sync RTC, and begin battery polling."""
        await super().start()

        # Stop any running experiment from a previous session
        await self.send_command('stop')

        if not self._rtc_synced:
            await self.sync_rtc()
            self._rtc_synced = True

        # Start background battery polling
        self._start_battery_polling()

    @property
    def device_type(self) -> DRTDeviceType:
        return DRTDeviceType.WDRT_WIRELESS

    @property
    def node_id(self) -> str:
        """Return the XBee node ID."""
        return self.device_id

    async def get_battery(self) -> Optional[int]:
        """Request battery with slightly longer delay for wireless."""
        if await self.send_command('get_battery'):
            await asyncio.sleep(0.3)
            return self._battery_percent
        return None

    def _format_device_id_for_csv(self) -> str:
        node_clean = self.device_id.replace('_', '').lower()
        return f"wDRT_{node_clean}"
