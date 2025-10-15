"""
Command Processing Package

Handles JSON command protocol for slave mode and command execution.
Re-exports shared protocol from logger_core.
"""

# Import from shared logger_core commands
from logger_core.commands import CommandMessage, StatusMessage

# Import camera-specific handler
from .command_handler import CommandHandler

__all__ = [
    'CommandMessage',
    'StatusMessage',
    'CommandHandler',
]
