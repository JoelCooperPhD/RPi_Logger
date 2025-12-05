"""VOG module constants - device identifiers and protocol definitions.

Device identifiers must match hardware VID/PID exactly.
Protocol commands must match firmware exactly.
"""

MODULE_NAME = "VOG"
MODULE_DESCRIPTION = "VOG Visual Occlusion Glasses Monitor and Data Logger"

# =============================================================================
# Device Identifiers
# =============================================================================

# sVOG (wired Arduino-based device)
SVOG_VID = 0x16C0
SVOG_PID = 0x0483
SVOG_BAUD = 115200

# wVOG (wireless device, direct USB connection)
WVOG_VID = 0xF057
WVOG_PID = 0x08AE
WVOG_BAUD = 57600

# wVOG dongle (XBee host adapter)
WVOG_DONGLE_VID = 0x0403
WVOG_DONGLE_PID = 0x6015
WVOG_DONGLE_BAUD = WVOG_BAUD

# =============================================================================
# Timing Constants
# =============================================================================

# Delay after sending command to let firmware process (seconds)
COMMAND_DELAY = 0.05

# Wait time for config response (seconds)
CONFIG_RESPONSE_WAIT = 0.5


# =============================================================================
# Utility Functions
# =============================================================================

def determine_device_type_from_vid_pid(vid: int, pid: int) -> str:
    """Determine device type from VID/PID values.

    Args:
        vid: USB Vendor ID
        pid: USB Product ID

    Returns:
        'wvog' if VID/PID match wVOG device, 'svog' otherwise
    """
    if vid == WVOG_VID and pid == WVOG_PID:
        return 'wvog'
    return 'svog'
