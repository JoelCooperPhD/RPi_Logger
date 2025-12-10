"""Stream controls for managing stream viewer checkboxes and state."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Set

try:
    import tkinter as tk
except Exception:
    tk = None  # type: ignore

if TYPE_CHECKING:
    from .base_viewer import BaseStreamViewer


@dataclass
class StreamState:
    """State for a single stream viewer."""

    enabled: "tk.BooleanVar"
    viewer: Optional["BaseStreamViewer"] = None


@dataclass
class StreamConfig:
    """Configuration for stream defaults and labels."""

    name: str
    label: str
    default_enabled: bool = False


# Stream configuration defining order, labels, and defaults
# Note: Video is not included as it's the core purpose of the module and always enabled
STREAM_CONFIGS = [
    StreamConfig("eyes", "Eyes"),
    StreamConfig("audio", "Audio"),
    StreamConfig("imu", "IMU"),
    StreamConfig("events", "Events"),
]


class StreamControls:
    """Manages stream checkboxes and coordinates with stream viewers.

    Provides:
    - Menu checkboxes for each stream
    - State management for enabled/disabled streams
    - Coordination between checkboxes and viewer widgets
    - Config persistence support
    """

    STREAM_NAMES = [cfg.name for cfg in STREAM_CONFIGS]

    def __init__(
        self,
        root: "tk.Tk",
        logger: logging.Logger,
    ) -> None:
        """Initialize stream controls.

        Args:
            root: Tkinter root window (needed for BooleanVar)
            logger: Logger instance
        """
        self._root = root
        self._logger = logger.getChild("StreamControls")
        self._states: Dict[str, StreamState] = {}
        self._on_change_callback: Optional[Callable[[str, bool], None]] = None

        # Initialize states with default values
        self._init_states()

    def _init_states(self) -> None:
        """Initialize stream states with default values."""
        if tk is None:
            return

        for cfg in STREAM_CONFIGS:
            var = tk.BooleanVar(value=cfg.default_enabled)
            self._states[cfg.name] = StreamState(enabled=var)

    def build_menu(self, menu: "tk.Menu") -> None:
        """Add stream checkboxes to a menu.

        Args:
            menu: Tkinter Menu to add checkboxes to
        """
        if tk is None or menu is None:
            return

        # Add separator and section header
        menu.add_separator()
        menu.add_command(label="Streams", state="disabled")

        # Add checkbox for each stream
        for cfg in STREAM_CONFIGS:
            state = self._states.get(cfg.name)
            if state is None:
                continue

            menu.add_checkbutton(
                label=cfg.label,
                variable=state.enabled,
                command=lambda s=cfg.name: self._on_toggle(s),
            )

    def _on_toggle(self, stream: str) -> None:
        """Handle checkbox toggle.

        Args:
            stream: Name of the stream that was toggled
        """
        state = self._states.get(stream)
        if state is None:
            return

        enabled = state.enabled.get()
        self._logger.info("Stream '%s' %s", stream, "enabled" if enabled else "disabled")

        # Update viewer visibility
        if state.viewer is not None:
            state.viewer.set_enabled(enabled)

        # Special handling for gaze - it's an overlay on video, not a separate viewer
        # Gaze enabled/disabled is handled by the video viewer's gaze_overlay_enabled

        # Notify callback
        if self._on_change_callback:
            self._on_change_callback(stream, enabled)

    def register_viewer(self, stream: str, viewer: "BaseStreamViewer") -> None:
        """Associate a viewer with a stream.

        The viewer's enabled state will be synchronized with the checkbox.

        Args:
            stream: Stream name (e.g., 'video', 'eyes')
            viewer: BaseStreamViewer instance
        """
        state = self._states.get(stream)
        if state is None:
            self._logger.warning("Unknown stream '%s' - cannot register viewer", stream)
            return

        state.viewer = viewer
        # Sync viewer state with checkbox
        viewer.set_enabled(state.enabled.get())
        self._logger.debug("Registered viewer for stream '%s'", stream)

    def set_on_change_callback(self, callback: Callable[[str, bool], None]) -> None:
        """Set callback for stream state changes.

        The callback receives (stream_name, is_enabled) when a checkbox changes.

        Args:
            callback: Function to call on state changes
        """
        self._on_change_callback = callback

    def is_enabled(self, stream: str) -> bool:
        """Check if a stream is enabled.

        Args:
            stream: Stream name

        Returns:
            True if enabled, False otherwise
        """
        state = self._states.get(stream)
        if state is None:
            return False
        return state.enabled.get()

    def set_enabled(self, stream: str, enabled: bool) -> None:
        """Set stream enabled state programmatically.

        Args:
            stream: Stream name
            enabled: Whether to enable the stream
        """
        state = self._states.get(stream)
        if state is None:
            return

        state.enabled.set(enabled)
        # Trigger the toggle handler to update viewer
        self._on_toggle(stream)

    def get_enabled_streams(self) -> Set[str]:
        """Return set of currently enabled stream names.

        Returns:
            Set of enabled stream names
        """
        return {
            name for name, state in self._states.items()
            if state.enabled.get()
        }

    def load_from_config(self, config: Any) -> None:
        """Load stream enabled states from config object.

        Args:
            config: TrackerConfig object with stream_*_enabled attributes
        """
        # Note: video is always enabled, so not included in config persistence
        stream_config_map = {
            "gaze": "stream_gaze_enabled",
            "eyes": "stream_eyes_enabled",
            "imu": "stream_imu_enabled",
            "events": "stream_events_enabled",
            "audio": "stream_audio_enabled",
        }

        for stream, attr in stream_config_map.items():
            if hasattr(config, attr):
                enabled = getattr(config, attr)
                state = self._states.get(stream)
                if state is not None:
                    state.enabled.set(enabled)
                    # Update viewer if registered
                    if state.viewer is not None:
                        state.viewer.set_enabled(enabled)

        self._logger.debug("Loaded stream states from config")

    def save_to_config(self, config: Any) -> None:
        """Save stream enabled states to config object.

        Args:
            config: TrackerConfig object with stream_*_enabled attributes
        """
        # Note: video is always enabled, so not included in config persistence
        stream_config_map = {
            "gaze": "stream_gaze_enabled",
            "eyes": "stream_eyes_enabled",
            "imu": "stream_imu_enabled",
            "events": "stream_events_enabled",
            "audio": "stream_audio_enabled",
        }

        for stream, attr in stream_config_map.items():
            state = self._states.get(stream)
            if state is not None and hasattr(config, attr):
                setattr(config, attr, state.enabled.get())

        self._logger.debug("Saved stream states to config")

    def get_viewer(self, stream: str) -> Optional["BaseStreamViewer"]:
        """Get the viewer registered for a stream.

        Args:
            stream: Stream name

        Returns:
            BaseStreamViewer instance or None if not registered
        """
        state = self._states.get(stream)
        return state.viewer if state else None


__all__ = ["StreamControls", "STREAM_CONFIGS"]
