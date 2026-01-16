
import os
import re
from typing import Optional, Tuple

from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger(__name__)

# Reserve space for the system bar at the bottom of the Raspberry Pi display.
# This prevents windows from being positioned where they'd be hidden under the taskbar.
# Can be overridden via environment variable for other systems.
_BOTTOM_MARGIN_ENV = "RPILOGGER_BOTTOM_UI_MARGIN"
try:
    SCREEN_BOTTOM_RESERVED = max(0, int(os.environ.get(_BOTTOM_MARGIN_ENV, "48")))
except ValueError:
    SCREEN_BOTTOM_RESERVED = 48


def parse_geometry_string(geometry_str: str) -> Optional[Tuple[int, int, int, int]]:
    """Parse a Tk geometry string into (width, height, x, y)."""
    try:
        match = re.match(r'(\d+)x(\d+)([\+\-]\d+)([\+\-]\d+)', geometry_str)
        if not match:
            logger.warning("Failed to parse geometry string: '%s'", geometry_str)
            return None

        width = int(match.group(1))
        height = int(match.group(2))
        x = int(match.group(3))  # Includes sign
        y = int(match.group(4))  # Includes sign

        return (width, height, x, y)

    except Exception as e:
        logger.warning("Exception parsing geometry string '%s': %s", geometry_str, e)
        return None


def format_geometry_string(width: int, height: int, x: int, y: int) -> str:
    """Format geometry values into a Tk geometry string."""
    return f"{width}x{height}+{x}+{y}"


def clamp_geometry_to_screen(
    width: int,
    height: int,
    x: int,
    y: int,
    *,
    screen_height: Optional[int] = None,
) -> Tuple[int, int, int, int]:
    """Clamp geometry so window bottom stays above the reserved screen area.

    This prevents windows from being positioned under the RPi taskbar.
    Does NOT modify coordinates for title bar offset - stores raw Tk coords.
    """
    width = int(width)
    height = int(height)
    x = int(x)
    y = int(y)

    if screen_height is not None and screen_height > 0:
        # Ensure window bottom doesn't go below visible area
        bottom_limit = max(0, screen_height - SCREEN_BOTTOM_RESERVED)
        max_y = max(0, bottom_limit - height)
        if y > max_y:
            y = max_y

    return width, height, x, y


def _get_screen_height(root_widget) -> Optional[int]:
    """Get screen height from a Tk widget."""
    try:
        return int(root_widget.winfo_screenheight())
    except Exception:
        return None


def get_frame_position(root_widget) -> Tuple[int, int, int, int]:
    """Get window frame position, compensating for X11 geometry asymmetry.

    On X11, after user interaction, geometry() may return content area position
    while the setter expects frame position. This causes windows to drift down
    by the title bar height each time they're saved and restored.

    This function detects the issue and returns the correct frame position.

    Returns:
        (width, height, frame_x, frame_y)
    """
    root_widget.update_idletasks()

    # Get position from geometry string
    geom_str = root_widget.geometry()
    parsed = parse_geometry_string(geom_str)
    if not parsed:
        raise ValueError(f"Failed to parse geometry: '{geom_str}'")

    width, height, geom_x, geom_y = parsed

    # Get absolute content position (always reliable)
    root_x = root_widget.winfo_rootx()
    root_y = root_widget.winfo_rooty()

    # Calculate offset between geometry() position and winfo position
    # - If geometry() returns frame position (correct): offset = title_bar_height > 0
    # - If geometry() returns content position (X11 bug): offset = 0
    offset_x = root_x - geom_x
    offset_y = root_y - geom_y

    # Determine frame position
    if offset_y >= 10:
        # offset_y is a reasonable title bar height (10+ pixels)
        # This means geometry() returned frame position correctly
        frame_x = geom_x
        frame_y = geom_y
    else:
        # offset_y is suspiciously small (< 10 pixels)
        # This suggests geometry() returned content position (X11 bug)
        # We need to convert content position to frame position
        # Frame position = content position - title_bar_height
        # Since we can't measure title bar when buggy, use estimate
        estimated_title_bar = 37  # Common title bar height on GNOME/GTK
        frame_x = geom_x  # X offset is typically 0
        frame_y = geom_y - estimated_title_bar
        # Ensure we don't go negative
        frame_y = max(0, frame_y)

    return width, height, frame_x, frame_y


def send_geometry_to_parent(root_widget, instance_id: Optional[str] = None) -> bool:
    """Send current window geometry to parent process.

    Sends frame position (not content position) to ensure consistent restore.
    The geometry is clamped to keep the window above the reserved screen
    bottom area (RPi taskbar).

    Args:
        root_widget: The Tkinter root window
        instance_id: Optional instance ID for multi-instance modules (e.g., "DRT:ACM0")

    Returns:
        True if sent successfully, False otherwise
    """
    try:
        from rpi_logger.core.commands import StatusMessage

        # Get frame position (compensates for X11 geometry asymmetry)
        try:
            width, height, x, y = get_frame_position(root_widget)
        except ValueError as e:
            logger.warning("Failed to get frame position: %s", e)
            return False

        # Clamp to screen bounds (keeps window above taskbar)
        width, height, x, y = clamp_geometry_to_screen(
            width, height, x, y,
            screen_height=_get_screen_height(root_widget),
        )

        payload = {
            "width": width,
            "height": height,
            "x": x,
            "y": y,
        }

        # Include instance_id for multi-instance geometry persistence
        if instance_id:
            payload["instance_id"] = instance_id

        StatusMessage.send("geometry_changed", payload)
        return True

    except ImportError:
        return False  # Expected in standalone mode
    except Exception as e:
        logger.warning("Failed to send geometry to parent: %s", e, exc_info=True)
        return False
