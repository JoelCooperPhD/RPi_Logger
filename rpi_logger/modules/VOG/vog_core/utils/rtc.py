"""
RTC Synchronization Utilities

Functions for synchronizing real-time clock on wVOG devices.
"""

from time import gmtime
from typing import Tuple


def format_rtc_sync() -> str:
    """
    Format the current time for RTC synchronization.

    Returns a comma-separated string in the format expected by wVOG devices:
    year,month,day,weekday,hour,minute,second,subsecond

    The subsecond value is fixed at 123 (as per RS_Logger implementation).

    Returns:
        Formatted RTC sync string
    """
    tt = gmtime()
    # Format: year, month, day, weekday, hour, minute, second, subsecond
    return f'{tt[0]},{tt[1]},{tt[2]},{tt[6]},{tt[3]},{tt[4]},{tt[5]},123'


def parse_rtc_response(response: str) -> Tuple[int, ...]:
    """
    Parse an RTC response from a wVOG device.

    Args:
        response: RTC response string (comma-separated values)

    Returns:
        Tuple of (year, month, day, weekday, hour, minute, second, subsecond)
    """
    parts = response.split(',')
    return tuple(int(p) for p in parts)
