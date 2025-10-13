"""
Operation Modes Package

Different operational modes for the camera system:
- Interactive: Preview with keyboard controls
- Slave: JSON command-driven with optional preview
- Headless: Automatic recording without UI
"""

from .base_mode import BaseMode
from .interactive_mode import InteractiveMode
from .slave_mode import SlaveMode
from .headless_mode import HeadlessMode

__all__ = [
    'BaseMode',
    'InteractiveMode',
    'SlaveMode',
    'HeadlessMode',
]
