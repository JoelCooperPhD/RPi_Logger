#!/usr/bin/env python3
"""
Base mode class for audio recording system.

Provides common functionality for all operational modes.
"""

from typing import TYPE_CHECKING
from Modules.base.modes import BaseMode as CoreBaseMode

if TYPE_CHECKING:
    from ..audio_system import AudioSystem


class BaseMode(CoreBaseMode):
    """Base class for audio operational modes."""

    def __init__(self, audio_system: 'AudioSystem'):
        """
        Initialize base mode.

        Args:
            audio_system: Audio system instance
        """
        super().__init__(audio_system)
