"""
VOG module discovery specification.

Defines the VID/PIDs and XBee patterns for VOG device discovery.
"""

from rpi_logger.core.devices.discovery_protocol import (
    ModuleDiscoverySpec,
    USBDeviceSpec,
    XBeePattern,
)
from rpi_logger.core.devices.types import DeviceFamily, InterfaceType


DISCOVERY_SPEC = ModuleDiscoverySpec(
    module_id="vog",
    display_name="VOG",
    family=DeviceFamily.VOG,
    interfaces=[InterfaceType.USB, InterfaceType.XBEE],
    usb_devices=[
        # sVOG - Wired serial VOG
        USBDeviceSpec(
            vid=0x16C0,
            pid=0x0483,
            baudrate=115200,
            name="sVOG",
        ),
        # wVOG_USB - Wireless VOG connected via USB
        USBDeviceSpec(
            vid=0xF057,
            pid=0x08AE,
            baudrate=57600,
            name="wVOG_USB",
        ),
    ],
    xbee_patterns=[
        # wVOG_* - Wireless VOG via XBee coordinator
        XBeePattern(prefix="wVOG", baudrate=57600),
    ],
    multi_instance=True,
)
