"""
Theme module for Logger UI.

Provides color palette, TTK styles, and custom widgets for the dark theme.
"""

from .colors import Colors
from .styles import Theme, Fonts
from .widgets import RoundedButton, MetricBar, RecordingBar

__all__ = ['Colors', 'Theme', 'Fonts', 'RoundedButton', 'MetricBar', 'RecordingBar']
