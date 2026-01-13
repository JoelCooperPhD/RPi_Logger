"""
Audio module discovery specification.

Audio devices use category-based discovery (custom scanner) using sounddevice.
"""

from rpi_logger.core.devices.discovery_protocol import ModuleDiscoverySpec
from rpi_logger.core.devices.types import DeviceFamily, InterfaceType


DISCOVERY_SPEC = ModuleDiscoverySpec(
    module_id="audio",
    display_name="Audio",
    family=DeviceFamily.AUDIO,
    interfaces=[InterfaceType.USB],
    has_custom_scanner=True,  # Module provides its own scanner
    multi_instance=True,
)
