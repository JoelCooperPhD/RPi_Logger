#!/usr/bin/env python3
"""
Async supervisor for audio system.
Maintains audio device availability with automatic retry on hardware failures.
"""

from typing import Type

from Modules.base import BaseSupervisor
from .audio_system import AudioSystem, AudioInitializationError
from .constants import DEVICE_DISCOVERY_RETRY


class AudioSupervisor(BaseSupervisor[AudioSystem, AudioInitializationError]):
    """Async wrapper that maintains audio device availability."""

    def __init__(self, args):
        super().__init__(args, default_retry_interval=DEVICE_DISCOVERY_RETRY)

    def create_system(self) -> AudioSystem:
        """Create audio system instance."""
        return AudioSystem(self.args)

    def get_initialization_error_type(self) -> Type[AudioInitializationError]:
        """Get audio initialization error type for retry logic."""
        return AudioInitializationError
