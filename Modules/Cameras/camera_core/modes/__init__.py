"""
Operation Modes Package

Different operational modes for the camera system:
- GUIMode: Interactive graphical interface (tkinter)
- SlaveMode: JSON command-driven with optional preview
- HeadlessMode: Automatic recording without UI
"""

from .base_mode import BaseMode
from .gui_mode import GUIMode
from .slave_mode import SlaveMode
from .headless_mode import HeadlessMode

__all__ = [
    'BaseMode',
    'GUIMode',
    'SlaveMode',
    'HeadlessMode',
]
