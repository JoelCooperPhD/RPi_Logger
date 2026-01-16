"""
Cameras module API package.

Provides Cameras (USB webcam) specific API endpoints and controller methods.
"""

from .spec import API_SPEC
from .controller import CamerasApiMixin
from .routes import setup_cameras_routes

__all__ = [
    "API_SPEC",
    "CamerasApiMixin",
    "setup_cameras_routes",
]
