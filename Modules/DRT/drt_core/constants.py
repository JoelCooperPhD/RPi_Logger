MODULE_NAME = "DRT"
MODULE_DESCRIPTION = "sDRT Device Monitor and Data Logger"

DRT_VID = 0x239A
DRT_PID = 0x801F
DEFAULT_BAUDRATE = 9600
SERIAL_TIMEOUT = 1.0
SERIAL_WRITE_TIMEOUT = 1.0

DRT_COMMANDS = {
    'exp_start': 'exp_start',
    'exp_stop': 'exp_stop',
    'stim_on': 'stim_on',
    'stim_off': 'stim_off',
    'get_config': 'get_config',
    'get_lowerISI': 'get_lowerISI',
    'set_lowerISI': 'set_lowerISI',
    'get_upperISI': 'get_upperISI',
    'set_upperISI': 'set_upperISI',
    'get_stimDur': 'get_stimDur',
    'set_stimDur': 'set_stimDur',
    'get_intensity': 'get_intensity',
    'set_intensity': 'set_intensity',
    'get_name': 'get_name',
}

ISO_PRESET_CONFIG = {
    'lowerISI': 3000,
    'upperISI': 5000,
    'stimDur': 1000,
    'intensity': 255,
}

DRT_RESPONSE_TYPES = {
    'clk': 'click',
    'trl': 'trial',
    'end': 'experiment_end',
    'stm': 'stimulus',
    'cfg': 'config',
}
