#!/usr/bin/env python3
"""
Async supervisor for eye tracker system.
Maintains device availability with automatic retry on hardware failures.
"""

from typing import Type

from Modules.base import BaseSupervisor
from .tracker_system import TrackerSystem, TrackerInitializationError
from .constants import DEVICE_DISCOVERY_RETRY


class TrackerSupervisor(BaseSupervisor[TrackerSystem, TrackerInitializationError]):
    """Async wrapper that maintains tracker device availability."""

    def __init__(self, args):
        super().__init__(args, default_retry_interval=DEVICE_DISCOVERY_RETRY)

    def create_system(self) -> TrackerSystem:
        """Create tracker system instance."""
        return TrackerSystem(self.args)

    def get_initialization_error_type(self) -> Type[TrackerInitializationError]:
        """Get tracker initialization error type for retry logic."""
        return TrackerInitializationError

    def get_system_name(self) -> str:
        """Get human-readable system name for logging."""
        return "Eye tracker"
