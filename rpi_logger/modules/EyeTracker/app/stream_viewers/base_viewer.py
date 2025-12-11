"""Base class for all stream viewer widgets."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Optional

try:
    import tkinter as tk
    from tkinter import ttk
except Exception:
    tk = None  # type: ignore
    ttk = None  # type: ignore


class BaseStreamViewer(ABC):
    """Abstract base class for stream viewer widgets.

    Each stream viewer is responsible for:
    - Building its UI within a parent frame
    - Showing/hiding itself using grid()/grid_forget()
    - Updating its display with stream data
    """

    def __init__(
        self,
        parent: "tk.Frame",
        stream_name: str,
        logger: logging.Logger,
        *,
        row: int = 0,
    ) -> None:
        """Initialize the stream viewer.

        Args:
            parent: Parent tkinter frame to build UI in
            stream_name: Name of the stream (e.g., 'video', 'imu')
            logger: Logger instance for this viewer
            row: Grid row position for this viewer
        """
        self._parent = parent
        self._stream_name = stream_name
        self._logger = logger
        self._row = row
        self._frame: Optional["ttk.Frame"] = None
        self._enabled = False
        self._visible = False

    @property
    def stream_name(self) -> str:
        """Return the name of the stream this viewer displays."""
        return self._stream_name

    @property
    def enabled(self) -> bool:
        """Return whether this viewer is enabled."""
        return self._enabled

    @property
    def visible(self) -> bool:
        """Return whether this viewer is currently visible."""
        return self._visible

    @abstractmethod
    def build_ui(self) -> "ttk.Frame":
        """Build and return the viewer's root frame.

        Subclasses must implement this to create their UI widgets.
        The frame should be created but not gridded - show() handles that.

        Returns:
            The root frame containing all viewer widgets
        """
        pass

    @abstractmethod
    def update(self, data: Any) -> None:
        """Update the display with new stream data.

        Args:
            data: Stream-specific data to display
        """
        pass

    def show(self) -> None:
        """Show the viewer by gridding its frame."""
        if self._frame and not self._visible:
            self._frame.grid(row=self._row, column=0, sticky="ew", pady=(4, 0))
            self._visible = True

    def hide(self) -> None:
        """Hide the viewer by removing it from grid."""
        if self._frame and self._visible:
            self._frame.grid_forget()
            self._visible = False

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the viewer.

        When enabled, the viewer is shown. When disabled, it is hidden.

        Args:
            enabled: Whether to enable the viewer
        """
        self._enabled = enabled
        if enabled:
            self.show()
        else:
            self.hide()

    def set_row(self, row: int) -> None:
        """Update the grid row position.

        Args:
            row: New row position
        """
        self._row = row
        if self._visible:
            self.hide()
            self.show()

    def cleanup(self) -> None:
        """Clean up viewer resources.

        Subclasses can override to release resources like animation handles.
        """
        pass


__all__ = ["BaseStreamViewer"]
