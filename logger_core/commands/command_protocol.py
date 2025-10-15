#!/usr/bin/env python3
"""
JSON Command Protocol for Master-Module Communication

Defines message formats for controlling modules and receiving status updates.
"""

import datetime
import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("CommandProtocol")


class CommandMessage:
    """Represents commands from master to module subprocess."""

    @staticmethod
    def create(command: str, **kwargs) -> str:
        """
        Create a JSON command message.

        Args:
            command: Command name (e.g., 'start_recording', 'stop_recording')
            **kwargs: Additional command parameters

        Returns:
            JSON string ready to send to subprocess stdin
        """
        message = {
            "command": command,
            "timestamp": datetime.datetime.now().isoformat(),
        }
        message.update(kwargs)
        return json.dumps(message) + "\n"

    @staticmethod
    def parse(raw_json: str) -> Optional[Dict[str, Any]]:
        """
        Parse a JSON command message received from master.

        Args:
            raw_json: JSON string from stdin

        Returns:
            Parsed command dictionary, or None if invalid
        """
        try:
            data = json.loads(raw_json.strip())

            # Validate it's a dict with 'command' key
            if not isinstance(data, dict):
                logger.warning("Command is not a dict: %s", raw_json[:100])
                return None

            if "command" not in data:
                logger.warning("Command missing 'command' key: %s", raw_json[:100])
                return None

            return data

        except json.JSONDecodeError as e:
            logger.warning("Failed to parse JSON command: %s - %s", e, raw_json[:100])
            return None
        except Exception as e:
            logger.error("Unexpected error parsing command: %s - %s", e, raw_json[:100])
            return None

    @staticmethod
    def start_recording() -> str:
        """Create start_recording command."""
        return CommandMessage.create("start_recording")

    @staticmethod
    def stop_recording() -> str:
        """Create stop_recording command."""
        return CommandMessage.create("stop_recording")

    @staticmethod
    def take_snapshot() -> str:
        """Create take_snapshot command."""
        return CommandMessage.create("take_snapshot")

    @staticmethod
    def get_status() -> str:
        """Create get_status command."""
        return CommandMessage.create("get_status")

    @staticmethod
    def get_geometry() -> str:
        """Create get_geometry command (request current window geometry)."""
        return CommandMessage.create("get_geometry")

    @staticmethod
    def toggle_preview(camera_id: int = 0, enabled: bool = True) -> str:
        """
        Create toggle_preview command.

        Args:
            camera_id: Camera ID to toggle
            enabled: Preview enabled state
        """
        return CommandMessage.create("toggle_preview", camera_id=camera_id, enabled=enabled)

    @staticmethod
    def quit() -> str:
        """Create quit command."""
        return CommandMessage.create("quit")


class StatusMessage:
    """Parses status messages from module subprocess."""

    # Class-level output stream for sending status messages
    # When set, send() will write to this stream instead of sys.stdout
    # This is critical for modules that redirect stdout to log files
    output_stream = None

    def __init__(self, raw_json: str):
        """
        Initialize from raw JSON string.

        Args:
            raw_json: JSON string from module stdout
        """
        self.raw = raw_json.strip()
        self.data = None
        self.status_type = None
        self.timestamp = None
        self.payload = {}
        self.valid = False

        self._parse()

    @classmethod
    def configure(cls, output_stream) -> None:
        """
        Configure the output stream for status messages.

        This should be called before any status messages are sent,
        typically after stdout redirection to preserve communication
        with the parent process.

        Args:
            output_stream: File object to write status messages to (typically original stdout)
        """
        cls.output_stream = output_stream

    @staticmethod
    def send(status: str, data: Optional[Dict[str, Any]] = None) -> None:
        """
        Send a status message to stdout for parent process.

        Writes to StatusMessage.output_stream if configured, otherwise sys.stdout.

        Args:
            status: Status type (e.g., 'initialized', 'quitting')
            data: Optional payload data
        """
        import sys
        message = {
            "type": "status",
            "status": status,
            "timestamp": datetime.datetime.now().isoformat(),
            "data": data or {}
        }
        # Write to configured output stream or fall back to stdout
        output = StatusMessage.output_stream if StatusMessage.output_stream else sys.stdout
        print(json.dumps(message), file=output, flush=True)

    def _parse(self) -> None:
        """Parse JSON and extract fields."""
        try:
            self.data = json.loads(self.raw)

            # Validate message structure
            if not isinstance(self.data, dict):
                logger.warning("Status message is not a dict: %s", self.raw)
                return

            # Extract common fields
            if self.data.get("type") != "status":
                logger.debug("Non-status message: %s", self.data.get("type"))
                # Still might be valid, just not a standard status message
                return

            self.status_type = self.data.get("status")
            self.timestamp = self.data.get("timestamp")
            self.payload = self.data.get("data", {})
            self.valid = True

        except json.JSONDecodeError as e:
            logger.warning("Failed to parse JSON status: %s - %s", e, self.raw)
        except Exception as e:
            logger.error("Unexpected error parsing status: %s - %s", e, self.raw)

    def is_valid(self) -> bool:
        """Check if message was parsed successfully."""
        return self.valid

    def get_status_type(self) -> Optional[str]:
        """Get status type (e.g., 'initialized', 'recording_started')."""
        return self.status_type

    def get_payload(self) -> Dict[str, Any]:
        """Get status payload data."""
        return self.payload

    def get_timestamp(self) -> Optional[str]:
        """Get message timestamp."""
        return self.timestamp

    def is_error(self) -> bool:
        """Check if this is an error status."""
        return self.status_type == "error"

    def is_warning(self) -> bool:
        """Check if this is a warning status."""
        return self.status_type == "warning"

    def get_error_message(self) -> Optional[str]:
        """Get error message if this is an error status."""
        if self.is_error():
            return self.payload.get("message")
        return None

    def __repr__(self) -> str:
        if self.valid:
            return f"StatusMessage(type={self.status_type}, payload={self.payload})"
        return f"StatusMessage(invalid: {self.raw[:50]}...)"


# Common status types (for reference/type checking)
class StatusType:
    """Common status message types from modules."""
    INITIALIZING = "initializing"
    INITIALIZED = "initialized"
    RECORDING_STARTED = "recording_started"
    RECORDING_STOPPED = "recording_stopped"
    SNAPSHOT_TAKEN = "snapshot_taken"
    STATUS_REPORT = "status_report"
    PREVIEW_FRAME = "preview_frame"
    PREVIEW_TOGGLED = "preview_toggled"
    GEOMETRY_CHANGED = "geometry_changed"  # Window position/size changed
    ERROR = "error"
    WARNING = "warning"
    QUITTING = "quitting"


if __name__ == "__main__":
    # Test command creation
    print("Testing command creation:")
    print(CommandMessage.start_recording())
    print(CommandMessage.stop_recording())
    print(CommandMessage.get_status())
    print(CommandMessage.quit())

    # Test status parsing
    print("\nTesting status parsing:")
    test_status = '{"type": "status", "status": "initialized", "timestamp": "2025-01-01T12:00:00", "data": {"cameras": 2}}'
    msg = StatusMessage(test_status)
    print(f"Valid: {msg.is_valid()}")
    print(f"Type: {msg.get_status_type()}")
    print(f"Payload: {msg.get_payload()}")

    # Test error status
    error_status = '{"type": "status", "status": "error", "timestamp": "2025-01-01T12:00:00", "data": {"message": "Camera init failed"}}'
    err_msg = StatusMessage(error_status)
    print(f"\nError: {err_msg.is_error()}")
    print(f"Error message: {err_msg.get_error_message()}")
