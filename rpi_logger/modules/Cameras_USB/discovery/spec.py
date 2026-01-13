"""
Cameras_USB module discovery specification.

USB cameras use category-based discovery (custom scanner) rather than
VID/PID matching because cameras don't have standard USB identifiers.
"""

from rpi_logger.core.devices.discovery_protocol import ModuleDiscoverySpec
from rpi_logger.core.devices.types import DeviceFamily, InterfaceType


DISCOVERY_SPEC = ModuleDiscoverySpec(
    module_id="cameras_usb",
    display_name="Cameras-USB",
    family=DeviceFamily.CAMERA_USB,
    interfaces=[InterfaceType.USB],
    has_custom_scanner=True,  # Module provides its own scanner
    multi_instance=True,
)
