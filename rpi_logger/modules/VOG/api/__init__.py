"""
VOG module API package.

Provides VOG-specific API endpoints and controller methods.
"""

from .spec import API_SPEC
from .controller import VOGApiMixin
from .routes import setup_vog_routes

__all__ = [
    "API_SPEC",
    "VOGApiMixin",
    "setup_vog_routes",
]
