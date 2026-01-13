"""Cameras_CSI module - CSI camera handling with Elm/Redux architecture.

Single-camera runtime for Raspberry Pi CSI cameras using pure state machine
(Store) for business logic and StubCodexSupervisor for UI shell.
"""

from .bridge import CSICamerasRuntime, factory

__all__ = ["CSICamerasRuntime", "factory"]
