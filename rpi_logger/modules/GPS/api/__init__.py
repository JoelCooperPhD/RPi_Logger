"""
GPS module API package.

Provides GPS-specific API endpoints and controller methods.
"""

from .spec import API_SPEC
from .controller import GPSApiMixin
from .routes import setup_gps_routes

__all__ = [
    "API_SPEC",
    "GPSApiMixin",
    "setup_gps_routes",
]
