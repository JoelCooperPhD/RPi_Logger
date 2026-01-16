"""DRT protocol constants for sDRT and wDRT devices."""

from typing import Dict

# =============================================================================
# sDRT Protocol
# =============================================================================

SDRT_COMMANDS: Dict[str, str] = {
    # Experiment control
    'start': 'exp_start',
    'stop': 'exp_stop',

    # Stimulus control
    'stim_on': 'stim_on',
    'stim_off': 'stim_off',

    # Configuration
    'get_config': 'get_config',
    'set_lowerISI': 'set_lowerISI',
    'set_upperISI': 'set_upperISI',
    'set_stimDur': 'set_stimDur',
    'set_intensity': 'set_intensity',
}

SDRT_RESPONSES: Dict[str, str] = {
    'clk': 'click',      # Click/response detected
    'trl': 'trial',      # Trial data
    'end': 'end',        # Experiment ended
    'stm': 'stimulus',   # Stimulus state change
    'cfg': 'config',     # Configuration data
}

SDRT_LINE_ENDING = '\n\r'

SDRT_CSV_HEADER = (
    "trial,module,device_id,label,record_time_unix,record_time_mono,"
    "device_time_unix,device_time_offset,responses,reaction_time_ms"
)

SDRT_ISO_PRESET = {
    'lowerISI': 3000,
    'upperISI': 5000,
    'stimDur': 1000,
    'intensity': 255,
}


# =============================================================================
# wDRT Protocol
# =============================================================================

WDRT_COMMANDS: Dict[str, str] = {
    # Experiment/trial control
    'start': 'trl>1',
    'stop': 'trl>0',

    # Stimulus control
    'stim_on': 'dev>1',
    'stim_off': 'dev>0',

    # Configuration
    'get_config': 'get_cfg>',
    'set': 'set>',
    'iso': 'dev>iso',

    # Device management
    'get_battery': 'get_bat>',
    'set_rtc': 'set_rtc>',
}

WDRT_RESPONSES: Dict[str, str] = {
    'cfg': 'config',       # Configuration data
    'stm': 'stimulus',     # Stimulus state change
    'bty': 'battery',      # Battery percentage
    'exp': 'experiment',   # Experiment state
    'trl': 'trial',        # Trial number
    'rt': 'reaction_time', # Reaction time
    'clk': 'click',        # Click/response detected
    'dta': 'data',         # Data packet (combined trial data)
    'rtc': 'rtc',          # RTC sync response
}

WDRT_LINE_ENDING = '\n'

WDRT_CSV_HEADER = (
    "trial,module,device_id,label,record_time_unix,record_time_mono,"
    "device_time_unix,device_time_offset,responses,reaction_time_ms,battery_percent"
)

WDRT_CONFIG_PARAMS = {
    'ONTM': 'stimDur',
    'ISIH': 'upperISI',
    'ISIL': 'lowerISI',
    'DBNC': 'debounce',
    'SPCT': 'intensity',
}

# Shared constants
RESPONSE_DELIMITER = '>'
DEFAULT_READ_TIMEOUT = 1.0
DEFAULT_WRITE_TIMEOUT = 0.1
RT_TIMEOUT_VALUE = -1
