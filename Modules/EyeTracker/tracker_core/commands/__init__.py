"""
JSON command protocol for eye tracker system.
Re-exports shared protocol from logger_core.
"""

# Import from shared logger_core commands
from logger_core.commands import CommandMessage, StatusMessage

# Import tracker-specific handler
from .command_handler import CommandHandler

__all__ = [
    'CommandMessage',
    'StatusMessage',
    'CommandHandler',
]
