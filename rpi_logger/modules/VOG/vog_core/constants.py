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
# sVOG Protocol Constants
# =============================================================================

# sVOG Commands (Arduino protocol)
SVOG_COMMANDS = {
    'exp_start': '>do_expStart|<<',
    'exp_stop': '>do_expStop|<<',
    'trial_start': '>do_trialStart|<<',
    'trial_stop': '>do_trialStop|<<',
    'peek_open': '>do_peekOpen|<<',
    'peek_close': '>do_peekClose|<<',
    'get_device_ver': '>get_deviceVer|<<',
    'get_config_name': '>get_configName|<<',
    'get_max_open': '>get_configMaxOpen|<<',
    'get_max_close': '>get_configMaxClose|<<',
    'get_debounce': '>get_configDebounce|<<',
    'get_click_mode': '>get_configClickMode|<<',
    'get_button_control': '>get_configButtonControl|<<',
    'set_config_name': '>set_configName|{val}<<',
    'set_max_open': '>set_configMaxOpen|{val}<<',
    'set_max_close': '>set_configMaxClose|{val}<<',
    'set_debounce': '>set_configDebounce|{val}<<',
    'set_click_mode': '>set_configClickMode|{val}<<',
    'set_button_control': '>set_configButtonControl|{val}<<',
}

# Response keywords from device
SVOG_RESPONSE_KEYWORDS = [
    'deviceVer',
    'configName',
    'configMaxOpen',
    'configMaxClose',
    'configDebounce',
    'configClickMode',
    'configButtonControl',
    'stm',
    'data',
]

# Response types for parsing
SVOG_RESPONSE_TYPES = {
    'deviceVer': 'version',
    'configName': 'config',
    'configMaxOpen': 'config',
    'configMaxClose': 'config',
    'configDebounce': 'config',
    'configClickMode': 'config',
    'configButtonControl': 'config',
    'stm': 'stimulus',
    'data': 'data',
}

# CSV header for data output
CSV_HEADER = "Device ID, Label, Unix time in UTC, Milliseconds Since Record, Trial Number, Shutter Open, Shutter Closed"


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
