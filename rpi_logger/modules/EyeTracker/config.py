"""Typed configuration for the EyeTracker module."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Tuple

from rpi_logger.modules.base.preferences import ScopedPreferences
from rpi_logger.modules.base.typed_config import (
    get_pref_bool,
    get_pref_float,
    get_pref_int,
    get_pref_path,
    get_pref_str,
)


@dataclass(slots=True)
class EyeTrackerConfig:
    """Typed configuration for the EyeTracker (Neon) module."""

    # Module metadata
    display_name: str = "EyeTracker-Neon"
    enabled: bool = True

    # Output settings
    output_dir: Path = field(default_factory=lambda: Path("neon-eyetracker"))
    session_prefix: str = "neon_eyetracker"
    log_level: str = "info"
    console_output: bool = False

    # Capture settings
    target_fps: float = 10.0
    eyes_fps: float = 30.0
    resolution_width: int = 1280
    resolution_height: int = 720
    auto_start_recording: bool = False

    # Preview settings
    preview_preset: int = 4
    preview_width: int = 640
    preview_height: int = 480
    gui_preview_update_hz: int = 5

    # Discovery settings
    discovery_timeout: float = 5.0
    discovery_retry: float = 3.0

    # Recording overlay settings
    enable_recording_overlay: bool = True
    include_gaze_in_recording: bool = True
    overlay_font_scale: float = 0.6
    overlay_thickness: int = 2
    overlay_color: Tuple[int, int, int] = (255, 255, 255)
    overlay_margin_left: int = 10
    overlay_line_start_y: int = 30

    # Gaze indicator settings
    gaze_circle_radius: int = 60
    gaze_circle_thickness: int = 6
    gaze_center_radius: int = 4
    gaze_shape: str = "circle"
    gaze_color_worn: Tuple[int, int, int] = (255, 0, 0)

    # Stream viewer settings
    stream_video_enabled: bool = True
    stream_gaze_enabled: bool = True
    stream_eyes_enabled: bool = True
    stream_imu_enabled: bool = True
    stream_events_enabled: bool = True
    stream_audio_enabled: bool = True

    # Audio stream
    audio_stream_param: str = "audio=scene"

    # UI visibility (master logger integration)
    gui_io_stub_visible: bool = False
    view_show_io_panel: bool = False
    view_show_logger: bool = False
    window_geometry: str = "320x200"

    @classmethod
    def from_preferences(
        cls, prefs: ScopedPreferences, args: Any = None
    ) -> "EyeTrackerConfig":
        """Build config from preferences with optional CLI overrides."""
        defaults = cls()

        # Build overlay color tuple
        overlay_color = (
            get_pref_int(prefs, "overlay_color_r", defaults.overlay_color[0]),
            get_pref_int(prefs, "overlay_color_g", defaults.overlay_color[1]),
            get_pref_int(prefs, "overlay_color_b", defaults.overlay_color[2]),
        )

        # Build gaze color tuple
        gaze_color_worn = (
            get_pref_int(prefs, "gaze_color_worn_r", defaults.gaze_color_worn[0]),
            get_pref_int(prefs, "gaze_color_worn_g", defaults.gaze_color_worn[1]),
            get_pref_int(prefs, "gaze_color_worn_b", defaults.gaze_color_worn[2]),
        )

        config = cls(
            # Module metadata
            display_name=get_pref_str(prefs, "display_name", defaults.display_name),
            enabled=get_pref_bool(prefs, "enabled", defaults.enabled),
            # Output settings
            output_dir=get_pref_path(prefs, "output_dir", defaults.output_dir),
            session_prefix=get_pref_str(prefs, "session_prefix", defaults.session_prefix),
            log_level=get_pref_str(prefs, "log_level", defaults.log_level),
            console_output=get_pref_bool(prefs, "console_output", defaults.console_output),
            # Capture settings
            target_fps=get_pref_float(prefs, "target_fps", defaults.target_fps),
            eyes_fps=get_pref_float(prefs, "eyes_fps", defaults.eyes_fps),
            resolution_width=get_pref_int(prefs, "resolution_width", defaults.resolution_width),
            resolution_height=get_pref_int(prefs, "resolution_height", defaults.resolution_height),
            auto_start_recording=get_pref_bool(prefs, "auto_start_recording", defaults.auto_start_recording),
            # Preview settings
            preview_preset=get_pref_int(prefs, "preview_preset", defaults.preview_preset),
            preview_width=get_pref_int(prefs, "preview_width", defaults.preview_width),
            preview_height=get_pref_int(prefs, "preview_height", defaults.preview_height),
            gui_preview_update_hz=get_pref_int(prefs, "gui_preview_update_hz", defaults.gui_preview_update_hz),
            # Discovery settings
            discovery_timeout=get_pref_float(prefs, "discovery_timeout", defaults.discovery_timeout),
            discovery_retry=get_pref_float(prefs, "discovery_retry", defaults.discovery_retry),
            # Recording overlay
            enable_recording_overlay=get_pref_bool(prefs, "enable_recording_overlay", defaults.enable_recording_overlay),
            include_gaze_in_recording=get_pref_bool(prefs, "include_gaze_in_recording", defaults.include_gaze_in_recording),
            overlay_font_scale=get_pref_float(prefs, "overlay_font_scale", defaults.overlay_font_scale),
            overlay_thickness=get_pref_int(prefs, "overlay_thickness", defaults.overlay_thickness),
            overlay_color=overlay_color,
            overlay_margin_left=get_pref_int(prefs, "overlay_margin_left", defaults.overlay_margin_left),
            overlay_line_start_y=get_pref_int(prefs, "overlay_line_start_y", defaults.overlay_line_start_y),
            # Gaze indicator
            gaze_circle_radius=get_pref_int(prefs, "gaze_circle_radius", defaults.gaze_circle_radius),
            gaze_circle_thickness=get_pref_int(prefs, "gaze_circle_thickness", defaults.gaze_circle_thickness),
            gaze_center_radius=get_pref_int(prefs, "gaze_center_radius", defaults.gaze_center_radius),
            gaze_shape=get_pref_str(prefs, "gaze_shape", defaults.gaze_shape),
            gaze_color_worn=gaze_color_worn,
            # Stream viewers
            stream_video_enabled=get_pref_bool(prefs, "stream_video_enabled", defaults.stream_video_enabled),
            stream_gaze_enabled=get_pref_bool(prefs, "stream_gaze_enabled", defaults.stream_gaze_enabled),
            stream_eyes_enabled=get_pref_bool(prefs, "stream_eyes_enabled", defaults.stream_eyes_enabled),
            stream_imu_enabled=get_pref_bool(prefs, "stream_imu_enabled", defaults.stream_imu_enabled),
            stream_events_enabled=get_pref_bool(prefs, "stream_events_enabled", defaults.stream_events_enabled),
            stream_audio_enabled=get_pref_bool(prefs, "stream_audio_enabled", defaults.stream_audio_enabled),
            # Audio
            audio_stream_param=get_pref_str(prefs, "audio_stream_param", defaults.audio_stream_param),
            # UI visibility
            gui_io_stub_visible=get_pref_bool(prefs, "gui_io_stub_visible", defaults.gui_io_stub_visible),
            view_show_io_panel=get_pref_bool(prefs, "view.show_io_panel", defaults.view_show_io_panel),
            view_show_logger=get_pref_bool(prefs, "view.show_logger", defaults.view_show_logger),
            window_geometry=get_pref_str(prefs, "window_geometry", defaults.window_geometry),
        )

        # Apply CLI argument overrides if provided
        if args is not None:
            config = config._apply_args_override(args)

        return config

    def _apply_args_override(self, args: Any) -> "EyeTrackerConfig":
        """Apply CLI argument overrides to config values."""
        # Get current values as dict for mutation
        values = asdict(self)

        # Map CLI args to config fields (only override if explicitly set)
        arg_mappings = {
            "output_dir": "output_dir",
            "session_prefix": "session_prefix",
            "log_level": "log_level",
            "console_output": "console_output",
            "target_fps": "target_fps",
            "auto_start_recording": "auto_start_recording",
            "preview_width": "preview_width",
            "discovery_timeout": "discovery_timeout",
            "discovery_retry": "discovery_retry",
            "gui_preview_update_hz": "gui_preview_update_hz",
            "audio_stream_param": "audio_stream_param",
        }

        for arg_name, config_key in arg_mappings.items():
            if hasattr(args, arg_name):
                val = getattr(args, arg_name)
                if val is not None:
                    values[config_key] = val

        # Handle resolution tuple from args
        if hasattr(args, "resolution") and args.resolution:
            values["resolution_width"], values["resolution_height"] = args.resolution

        # Handle preview height (calculated from width)
        if hasattr(args, "preview_width") and args.preview_width:
            values["preview_height"] = int(args.preview_width * 3 / 4)

        return EyeTrackerConfig(**values)

    def to_dict(self) -> dict[str, Any]:
        """Export config values as dictionary."""
        return asdict(self)

    @property
    def resolution(self) -> Tuple[int, int]:
        """Return resolution as (width, height) tuple."""
        return (self.resolution_width, self.resolution_height)


__all__ = ["EyeTrackerConfig"]
