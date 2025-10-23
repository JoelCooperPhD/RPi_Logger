"""
Shared constants used across multiple modules.

This module contains constants that are common to multiple modules
to avoid duplication and ensure consistency.
"""

# Device discovery and initialization timeouts
DEVICE_DISCOVERY_TIMEOUT_SECONDS = 5.0  # Timeout for finding devices
DEVICE_DISCOVERY_RETRY_SECONDS = 3.0     # Retry interval for device discovery

# Cleanup and shutdown timeouts
CLEANUP_TIMEOUT_SECONDS = 2.0            # Timeout for cleanup operations

# Error message formatting
MAX_ERROR_MESSAGE_LENGTH = 200           # Maximum length for error messages

# Polling intervals
KEYBOARD_POLL_INTERVAL = 0.001           # 1ms for keyboard input polling
