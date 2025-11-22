"""Shared overlay defaults used by video overlays across modules."""

# Centralize the overlay defaults so modules like Cameras and USBCameras
# render identical text (font size, colors, spacing, etc.) on recordings.
CAMERA_OVERLAY_DEFAULTS = {
    "resolution_preset": 0,
    "resolution_width": 1920,
    "resolution_height": 1080,
    "preview_preset": 5,
    "preview_width": 640,
    "preview_height": 360,
    "target_fps": 30.0,
    "min_cameras": 1,
    "allow_partial": True,
    "discovery_timeout": 5.0,
    "discovery_retry": 3.0,
    "output_dir": "recordings",
    "session_prefix": "session",
    "auto_start_recording": False,
    "show_preview": True,
    "console_output": False,
    "libcamera_log_level": "WARN",
    "font_scale_base": 0.6,
    "thickness_base": 2,
    "font_type": "SIMPLEX",
    "outline_enabled": True,
    "outline_extra_thickness": 2,
    "line_start_y": 30,
    "line_spacing": 30,
    "margin_left": 10,
    "text_color_b": 255,
    "text_color_g": 255,
    "text_color_r": 255,
    "outline_color_b": 0,
    "outline_color_g": 0,
    "outline_color_r": 0,
    "line_type": 16,
    "background_enabled": False,
    "background_shape": "rectangle",
    "background_color_b": 0,
    "background_color_g": 0,
    "background_color_r": 0,
    "background_opacity": 0.6,
    "background_padding_top": 10,
    "background_padding_bottom": 10,
    "background_padding_left": 10,
    "background_padding_right": 10,
    "background_corner_radius": 10,
    "show_camera_and_time": True,
    "show_session": True,
    "show_requested_fps": True,
    "show_sensor_fps": True,
    "show_display_fps": True,
    "show_frame_counter": True,
    "show_recording_info": True,
    "show_recording_filename": True,
    "show_controls": True,
    "show_frame_number": True,
    "scale_mode": "auto",
    "manual_scale_factor": 3.0,
}


def get_camera_overlay_defaults() -> dict:
    """Return a copy so callers can mutate without affecting the shared base."""
    return dict(CAMERA_OVERLAY_DEFAULTS)


__all__ = ["CAMERA_OVERLAY_DEFAULTS", "get_camera_overlay_defaults"]
