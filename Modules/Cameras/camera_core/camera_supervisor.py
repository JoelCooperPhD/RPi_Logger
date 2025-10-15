#!/usr/bin/env python3
"""
Async supervisor for camera system.
Maintains camera availability with automatic retry on hardware failures.
"""

from typing import Type

from Modules.base import BaseSupervisor
from .camera_system import CameraSystem, CameraInitializationError


class CameraSupervisor(BaseSupervisor[CameraSystem, CameraInitializationError]):
    """Async wrapper that maintains camera availability."""

    def __init__(self, args):
        super().__init__(args, default_retry_interval=3.0)

    def create_system(self) -> CameraSystem:
        """Create camera system instance."""
        return CameraSystem(self.args)

    def get_initialization_error_type(self) -> Type[CameraInitializationError]:
        """Get camera initialization error type for retry logic."""
        return CameraInitializationError
