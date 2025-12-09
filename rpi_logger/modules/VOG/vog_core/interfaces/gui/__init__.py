"""VOG GUI Components Package

Contains GUI widgets for the VOG module:
- VOGPlotter: Real-time plotting widget with dark theme
- VOGConfigWindow: Configuration dialog for device settings
"""

from .vog_plotter import VOGPlotter, HAS_MATPLOTLIB
from .config_window import VOGConfigWindow

__all__ = [
    'VOGPlotter',
    'VOGConfigWindow',
    'HAS_MATPLOTLIB',
]
