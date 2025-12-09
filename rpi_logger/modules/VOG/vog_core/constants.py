"""VOG module constants.

Protocol timing constants.
Device discovery is handled by the main logger - this module receives device assignments.

Note: Baud rates are documented in the protocol class docstrings
(SVOGProtocol: 115200, WVOGProtocol: 57600) and provided externally
when devices are assigned.
"""

# Timing Constants
COMMAND_DELAY = 0.05  # Delay after sending command (seconds)

