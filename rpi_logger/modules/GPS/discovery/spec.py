"""
GPS module discovery specification.

GPS uses UART interface with a fixed path on Raspberry Pi.
"""

from rpi_logger.core.devices.discovery_protocol import ModuleDiscoverySpec
from rpi_logger.core.devices.types import DeviceFamily, InterfaceType


DISCOVERY_SPEC = ModuleDiscoverySpec(
    module_id="gps",
    display_name="GPS",
    family=DeviceFamily.GPS,
    interfaces=[InterfaceType.UART],
    uart_path="/dev/serial0",
    multi_instance=False,
    platforms=["raspberry_pi"],  # Only available on Raspberry Pi
)
