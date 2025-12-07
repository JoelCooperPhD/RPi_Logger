"""VOG module constants.

Protocol timing and module metadata.
Device discovery is handled by the main logger - this module receives device assignments.
"""

MODULE_NAME = "VOG"
MODULE_DESCRIPTION = "VOG Visual Occlusion Glasses Monitor and Data Logger"

# Protocol baud rates (used when creating transports)
SVOG_BAUD = 115200
WVOG_BAUD = 57600

# Timing Constants
COMMAND_DELAY = 0.05  # Delay after sending command (seconds)
CONFIG_RESPONSE_WAIT = 0.5  # Wait time for config response (seconds)

