"""
REST API for Logger System.

Provides programmatic control over all application features via HTTP/JSON endpoints.
Enables automated testing and verification through the existing logging system.

Usage:
    python -m rpi_logger --api --api-port 8080

The API runs alongside the GUI, providing HTTP endpoints for programmatic control.
"""

from .server import APIServer
from .controller import APIController

__all__ = ["APIServer", "APIController"]
