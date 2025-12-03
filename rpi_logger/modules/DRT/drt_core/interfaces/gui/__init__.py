"""
DRT GUI Components Package

Contains GUI widgets for the DRT module:
- TkinterGUI: Main DRT GUI
- DRTPlotter: Real-time plotting widget
- SDRTConfigWindow: sDRT configuration dialog
- WDRTConfigWindow: wDRT configuration dialog
- BatteryWidget: Battery indicator for wDRT
- QuickStatusPanel: Trial data display panel
"""

from .battery_widget import BatteryWidget, CompactBatteryWidget
from .wdrt_config_window import WDRTConfigWindow

__all__ = [
    'BatteryWidget',
    'CompactBatteryWidget',
    'WDRTConfigWindow',
]
