"""
DRT Protocol Constants

Defines command and response protocols for all DRT device types:
- sDRT: Simple Detection Response Task
- wDRT: Wireless Detection Response Task

Each device type has its own command set and response format.
"""

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

# sDRT command line terminator
SDRT_LINE_ENDING = '\n\r'

# sDRT CSV logging fields
SDRT_CSV_HEADER = (
    "module,trial,device_id,label,device_time_ms,device_time_unix,record_time_unix,"
    "record_time_mono,responses,reaction_time_ms"
)

# ISO Standard preset configuration for sDRT
SDRT_ISO_PRESET = {
    'lowerISI': 3000,    # 3 seconds minimum inter-stimulus interval
    'upperISI': 5000,    # 5 seconds maximum inter-stimulus interval
    'stimDur': 1000,     # 1 second stimulus duration
    'intensity': 255,    # Maximum intensity (0-255)
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

# wDRT command line terminator
WDRT_LINE_ENDING = '\n'

# wDRT CSV logging fields
WDRT_CSV_HEADER = (
    "module,trial,device_id,label,device_time_ms,device_time_unix,record_time_unix,"
    "record_time_mono,responses,reaction_time_ms,battery_percent"
)

# wDRT configuration parameter mapping
# Maps device parameter names to human-readable names
WDRT_CONFIG_PARAMS = {
    'ONTM': 'stimDur',      # Stimulus on-time (duration)
    'ISIH': 'upperISI',     # Inter-stimulus interval high
    'ISIL': 'lowerISI',     # Inter-stimulus interval low
    'DBNC': 'debounce',     # Debounce time
    'SPCT': 'intensity',    # Stimulus percent (intensity)
}

# =============================================================================
# Shared Constants
# =============================================================================

# Response delimiter used in both protocols
RESPONSE_DELIMITER = '>'

# Default read timeout in seconds
DEFAULT_READ_TIMEOUT = 1.0

# Default write timeout in seconds
DEFAULT_WRITE_TIMEOUT = 0.1

# Reaction time value indicating no response (timeout/miss)
RT_TIMEOUT_VALUE = -1
