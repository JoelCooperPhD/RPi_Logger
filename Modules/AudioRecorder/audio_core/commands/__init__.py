#!/usr/bin/env python3
"""
JSON command protocol for master-slave communication.
Re-exports shared protocol from logger_core.
"""

# Import from shared logger_core commands
from logger_core.commands import CommandMessage, StatusMessage

# Import audio-specific handler
from .command_handler import CommandHandler

__all__ = ['CommandMessage', 'StatusMessage', 'CommandHandler']
