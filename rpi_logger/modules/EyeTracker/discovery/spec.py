"""
EyeTracker module discovery specification.

Eye trackers use network-based discovery (mDNS/Zeroconf).
"""

from rpi_logger.core.devices.discovery_protocol import ModuleDiscoverySpec
from rpi_logger.core.devices.types import DeviceFamily, InterfaceType


DISCOVERY_SPEC = ModuleDiscoverySpec(
    module_id="eyetracker",
    display_name="EyeTracker-Neon",
    family=DeviceFamily.EYE_TRACKER,
    interfaces=[InterfaceType.NETWORK],
    has_custom_scanner=True,  # Module provides its own network scanner
    multi_instance=False,
)
