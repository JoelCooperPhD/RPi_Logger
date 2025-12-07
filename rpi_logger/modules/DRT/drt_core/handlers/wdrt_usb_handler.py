"""
wDRT USB Handler

Protocol handler for wDRT devices connected via USB.
"""

from pathlib import Path
from typing import Any

from .wdrt_base_handler import WDRTBaseHandler
from ..device_types import DRTDeviceType


class WDRTUSBHandler(WDRTBaseHandler):
    """Handler for wDRT devices connected via USB."""

    def __init__(
        self,
        device_id: str,
        output_dir: Path,
        transport: Any
    ):
        super().__init__(device_id, output_dir, transport)
        self._rtc_synced = False

    @property
    def device_type(self) -> DRTDeviceType:
        return DRTDeviceType.WDRT_USB

    async def start(self) -> None:
        """Start the handler and sync RTC on first connection."""
        await super().start()

        if not self._rtc_synced:
            await self.sync_rtc()
            self._rtc_synced = True

    def _format_device_id_for_csv(self) -> str:
        port_clean = self.device_id.lstrip('/').replace('/', '_').lower()
        return f"wDRT_{port_clean}"
