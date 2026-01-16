"""
Notes module API package.

Provides Notes-specific API endpoints and controller methods.
"""

from .spec import API_SPEC
from .controller import NotesApiMixin
from .routes import setup_notes_routes

__all__ = [
    "API_SPEC",
    "NotesApiMixin",
    "setup_notes_routes",
]
