"""
DRT module discovery package.

Provides device identification for DRT (Detection Response Task) devices:
- sDRT: Wired serial DRT (VID=0x239A, PID=0x801E, 9600 baud)
- wDRT_USB: Wireless DRT connected via USB (VID=0xF056, PID=0x0457, 921600 baud)
- wDRT_Wireless: Wireless DRT via XBee (node pattern wDRT_*, 921600 baud)
"""

from typing import Optional

from rpi_logger.core.devices.discovery_protocol import (
    BaseModuleDiscovery,
    DeviceMatch,
)
from .spec import DISCOVERY_SPEC
from .usb import identify_drt_device
from .xbee import parse_drt_node_id


class DRTDiscovery(BaseModuleDiscovery):
    """Discovery handler for DRT devices."""

    spec = DISCOVERY_SPEC

    def identify_usb_device(self, vid: int, pid: int) -> Optional[DeviceMatch]:
        """Check if VID/PID matches a DRT device."""
        return identify_drt_device(vid, pid)

    def parse_xbee_node(self, node_id: str) -> Optional[DeviceMatch]:
        """Parse XBee node ID for DRT devices."""
        return parse_drt_node_id(node_id)


# Exports for discovery loader
__all__ = [
    "DRTDiscovery",
    "DISCOVERY_SPEC",
    "identify_drt_device",
    "parse_drt_node_id",
]
