
import logging
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
            logger.error("Failed to parse geometry string: '%s'", geometry_str)
            return None

        width = int(match.group(1))
        height = int(match.group(2))
        x = int(match.group(3))  # Includes sign
        y = int(match.group(4))  # Includes sign

        return (width, height, x, y)

    except Exception as e:
        logger.error("Exception parsing geometry string '%s': %s", geometry_str, e)
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
            logger.debug(
                "Clamping window to visible region (screen=%d, reserve=%d, height=%d, y=%d->%d)",
                screen_height, SCREEN_BOTTOM_RESERVED, height, y, max_y,
            )
            y = max_y

    return width, height, x, y


def _get_screen_height(root_widget) -> Optional[int]:
    """Get screen height from a Tk widget."""
    try:
        return int(root_widget.winfo_screenheight())
    except Exception:
        return None


def send_geometry_to_parent(root_widget, instance_id: Optional[str] = None) -> bool:
    """Send current window geometry to parent process.

    Sends raw Tk coordinates. The geometry is clamped to keep the window
    above the reserved screen bottom area (RPi taskbar).

    Args:
        root_widget: The Tkinter root window
        instance_id: Optional instance ID for multi-instance modules (e.g., "DRT:ACM0")

    Returns:
        True if sent successfully, False otherwise
    """
    try:
        logger.debug("Sending geometry to parent process")
        from rpi_logger.core.commands import StatusMessage

        geometry_str = root_widget.geometry()
        logger.debug("Current geometry string: %s", geometry_str)

        parsed = parse_geometry_string(geometry_str)
        if not parsed:
            logger.error("Failed to parse geometry: '%s'", geometry_str)
            return False

        width, height, x, y = parsed

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
            logger.debug("Including instance_id in geometry payload: %s", instance_id)

        StatusMessage.send("geometry_changed", payload)
        logger.info("Sent geometry to parent: %dx%d+%d+%d (instance: %s)",
                    width, height, x, y, instance_id or "none")
        return True

    except ImportError as e:
        logger.debug("StatusMessage not available (standalone mode): %s", e)
        return False
    except Exception as e:
        logger.error("Failed to send geometry to parent: %s", e, exc_info=True)
        return False
