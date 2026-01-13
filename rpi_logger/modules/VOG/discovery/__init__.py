"""
VOG module discovery package.

Provides device identification for VOG (Visual Occlusion Glasses) devices:
- sVOG: Wired serial VOG (VID=0x16C0, PID=0x0483, 115200 baud)
- wVOG_USB: Wireless VOG connected via USB (VID=0xF057, PID=0x08AE, 57600 baud)
- wVOG_Wireless: Wireless VOG via XBee (node pattern wVOG_*, 57600 baud)
"""

from typing import Optional

from rpi_logger.core.devices.discovery_protocol import (
    BaseModuleDiscovery,
    DeviceMatch,
)
from .spec import DISCOVERY_SPEC
from .usb import identify_vog_device
from .xbee import parse_vog_node_id


class VOGDiscovery(BaseModuleDiscovery):
    """Discovery handler for VOG devices."""

    spec = DISCOVERY_SPEC

    def identify_usb_device(self, vid: int, pid: int) -> Optional[DeviceMatch]:
        """Check if VID/PID matches a VOG device."""
        return identify_vog_device(vid, pid)

    def parse_xbee_node(self, node_id: str) -> Optional[DeviceMatch]:
        """Parse XBee node ID for VOG devices."""
        return parse_vog_node_id(node_id)


# Exports for discovery loader
__all__ = [
    "VOGDiscovery",
    "DISCOVERY_SPEC",
    "identify_vog_device",
    "parse_vog_node_id",
]
