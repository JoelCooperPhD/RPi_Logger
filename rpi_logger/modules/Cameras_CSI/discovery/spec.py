"""
Cameras_CSI module discovery specification.

CSI cameras use category-based discovery using libcamera CLI.
Only available on Raspberry Pi.
"""

from rpi_logger.core.devices.discovery_protocol import ModuleDiscoverySpec
from rpi_logger.core.devices.types import DeviceFamily, InterfaceType


DISCOVERY_SPEC = ModuleDiscoverySpec(
    module_id="cameras_csi",
    display_name="Cameras-CSI",
    family=DeviceFamily.CAMERA_CSI,
    interfaces=[InterfaceType.CSI],
    has_custom_scanner=True,  # Module provides its own scanner
    multi_instance=True,
    platforms=["raspberry_pi"],  # Only available on Raspberry Pi
)
