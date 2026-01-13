"""
DRT XBee node ID parsing.

Parses XBee node IDs to identify wireless DRT devices.
"""

import re
from typing import Optional

from rpi_logger.core.devices.discovery_protocol import DeviceMatch
from rpi_logger.core.devices.types import InterfaceType
from .spec import DISCOVERY_SPEC


def parse_drt_node_id(node_id: str) -> Optional[DeviceMatch]:
    """
    Parse XBee node ID for DRT devices.

    Expected formats:
    - "wDRT_XX" or "wDRT XX" where XX is a number

    Args:
        node_id: The XBee node identifier string

    Returns:
        DeviceMatch if recognized, None otherwise
    """
    for pattern in DISCOVERY_SPEC.xbee_patterns:
        regex = re.compile(
            rf'^{re.escape(pattern.prefix)}[_\s]*(\d+)$',
            re.IGNORECASE
        )
        match = regex.match(node_id.strip())
        if match:
            device_number = int(match.group(1))
            return DeviceMatch(
                module_id=DISCOVERY_SPEC.module_id,
                device_name=f"{pattern.prefix}_{device_number:02d}",
                family=DISCOVERY_SPEC.family,
                interface_type=InterfaceType.XBEE,
                baudrate=pattern.baudrate,
                device_number=device_number,
            )
    return None
