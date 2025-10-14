#!/usr/bin/env python3
"""
JSON command protocol for master-slave communication.

Defines message formats and utilities for command/status exchange.
"""

import datetime
import json
import sys
from typing import Any, Dict, Optional


class CommandMessage:
    """Represents a command from master to slave."""

    @staticmethod
    def parse(json_line: str) -> Optional[Dict[str, Any]]:
        """
        Parse JSON command from stdin.

        Args:
            json_line: JSON string from master

        Returns:
            Parsed command dict or None if invalid
        """
        try:
            return json.loads(json_line)
        except json.JSONDecodeError:
            return None


class StatusMessage:
    """Handles status messages from slave to master."""

    # Class variable to hold the output stream (can be overridden for slave mode)
    output_stream = None

    @staticmethod
    def send(status_type: str, data: Optional[Dict[str, Any]] = None) -> None:
        """
        Send status message to master via stdout.

        Args:
            status_type: Type of status ('initialized', 'recording_started', etc.)
            data: Optional data dict to include in message
        """
        message = {
            "type": "status",
            "status": status_type,
            "timestamp": datetime.datetime.now().isoformat(),
            "data": data or {}
        }
        # Use override stream if set, otherwise use sys.stdout
        output = StatusMessage.output_stream if StatusMessage.output_stream else sys.stdout
        output.write(json.dumps(message) + "\n")
        output.flush()
