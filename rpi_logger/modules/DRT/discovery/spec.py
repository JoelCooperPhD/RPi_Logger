"""
DRT module discovery specification.

Defines the VID/PIDs and XBee patterns for DRT device discovery.
"""

from rpi_logger.core.devices.discovery_protocol import (
    ModuleDiscoverySpec,
    USBDeviceSpec,
    XBeePattern,
)
from rpi_logger.core.devices.types import DeviceFamily, InterfaceType


DISCOVERY_SPEC = ModuleDiscoverySpec(
    module_id="drt",
    display_name="DRT",
    family=DeviceFamily.DRT,
    interfaces=[InterfaceType.USB, InterfaceType.XBEE],
    usb_devices=[
        # sDRT - Wired serial DRT
        USBDeviceSpec(
            vid=0x239A,
            pid=0x801E,
            baudrate=9600,
            name="sDRT",
        ),
        # wDRT_USB - Wireless DRT connected via USB
        USBDeviceSpec(
            vid=0xF056,
            pid=0x0457,
            baudrate=921600,
            name="wDRT_USB",
        ),
    ],
    xbee_patterns=[
        # wDRT_* - Wireless DRT via XBee coordinator
        XBeePattern(prefix="wDRT", baudrate=921600),
    ],
    multi_instance=True,
)
