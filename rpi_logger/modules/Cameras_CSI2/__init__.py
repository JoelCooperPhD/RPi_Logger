"""Cameras_CSI2 module - CSI camera handling with Elm/Redux architecture.

Single-camera runtime for Raspberry Pi CSI cameras using pure state machine
(Store) for business logic and StubCodexSupervisor for UI shell.
"""

import sys
from pathlib import Path

# Ensure module can find sibling packages
_module_dir = Path(__file__).resolve().parent
if str(_module_dir) not in sys.path:
    sys.path.insert(0, str(_module_dir))

from bridge import CSI2CamerasRuntime, factory

__all__ = ["CSI2CamerasRuntime", "factory"]
