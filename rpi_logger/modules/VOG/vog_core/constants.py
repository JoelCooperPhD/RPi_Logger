"""sVOG command protocol constants - must match existing firmware exactly."""

MODULE_NAME = "VOG"
MODULE_DESCRIPTION = "sVOG Visual Occlusion Glasses Monitor and Data Logger"

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
