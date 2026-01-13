"""
GPS module discovery package.

GPS uses UART interface with fixed path on Raspberry Pi.
Discovery is simple - just check if the UART path exists.
"""

from rpi_logger.core.devices.discovery_protocol import BaseModuleDiscovery
from .spec import DISCOVERY_SPEC


class GpsDiscovery(BaseModuleDiscovery):
    """Discovery handler for GPS devices."""

    spec = DISCOVERY_SPEC

    # GPS doesn't need USB or XBee matchers - uses UART path
    # The UART path is specified in the spec


# Exports for discovery loader
__all__ = [
    "GpsDiscovery",
    "DISCOVERY_SPEC",
]
