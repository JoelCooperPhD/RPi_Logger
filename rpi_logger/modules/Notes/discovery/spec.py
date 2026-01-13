"""
Notes module discovery specification.

Notes is an internal/virtual module with no hardware discovery.
"""

from rpi_logger.core.devices.discovery_protocol import ModuleDiscoverySpec
from rpi_logger.core.devices.types import DeviceFamily, InterfaceType


DISCOVERY_SPEC = ModuleDiscoverySpec(
    module_id="notes",
    display_name="Notes",
    family=DeviceFamily.INTERNAL,
    interfaces=[InterfaceType.INTERNAL],
    is_internal=True,  # Software-only, always available
    multi_instance=False,
)
