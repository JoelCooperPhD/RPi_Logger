"""
Audio module API package.

Provides Audio-specific API endpoints and controller methods.
"""

from .spec import API_SPEC
from .controller import AudioApiMixin
from .routes import setup_audio_routes

__all__ = [
    "API_SPEC",
    "AudioApiMixin",
    "setup_audio_routes",
]
