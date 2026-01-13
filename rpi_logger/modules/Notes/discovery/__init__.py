"""
Notes module discovery package.

Notes is an internal/virtual module with no hardware discovery.
It's always available as a software-only annotation module.
"""

from rpi_logger.core.devices.discovery_protocol import BaseModuleDiscovery
from .spec import DISCOVERY_SPEC


class NotesDiscovery(BaseModuleDiscovery):
    """Discovery handler for Notes module."""

    spec = DISCOVERY_SPEC

    # Notes is internal - no discovery needed


# Exports for discovery loader
__all__ = [
    "NotesDiscovery",
    "DISCOVERY_SPEC",
]
