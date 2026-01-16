"""
EyeTracker module API package.

Provides EyeTracker (Pupil Labs Neon) specific API endpoints and controller methods.
"""

from .spec import API_SPEC
from .controller import EyeTrackerApiMixin
from .routes import setup_eyetracker_routes

__all__ = [
    "API_SPEC",
    "EyeTrackerApiMixin",
    "setup_eyetracker_routes",
]
