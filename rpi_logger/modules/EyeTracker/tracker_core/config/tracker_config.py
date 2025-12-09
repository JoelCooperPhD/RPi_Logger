
from dataclasses import dataclass
from typing import Optional


@dataclass
class TrackerConfig:
    fps: float = 5.0
    resolution: tuple = (1280, 720)
    output_dir: str = "recordings"
    display_width: int = 640

    # Phase 1.3: Preview resolution for early scaling
    preview_width: int = 640
    preview_height: Optional[int] = None

    # Recording overlay settings (matching camera module)
    enable_recording_overlay: bool = True
    include_gaze_in_recording: bool = True
    overlay_font_scale: float = 0.6
    overlay_thickness: int = 2
    overlay_color_r: int = 255
    overlay_color_g: int = 255
    overlay_color_b: int = 255
    overlay_margin_left: int = 10
    overlay_line_start_y: int = 30

    # Gaze indicator settings
    gaze_circle_radius: int = 30
    gaze_circle_thickness: int = 3
    gaze_center_radius: int = 2
    gaze_shape: str = "circle"
    gaze_color_worn_b: int = 255
    gaze_color_worn_g: int = 255
    gaze_color_worn_r: int = 0
    gaze_color_not_worn_b: int = 0
    gaze_color_not_worn_g: int = 0
    gaze_color_not_worn_r: int = 255

    # Data export controls
    enable_advanced_gaze_logging: bool = False
    expand_eye_event_details: bool = True
    enable_audio_recording: bool = False
    audio_stream_param: str = "audio=scene"
    enable_device_status_logging: bool = False
    device_status_poll_interval: float = 5.0

    # Phase 3.1: Frame selection mode
    # "timer" - maintains consistent output FPS, duplicates frames when camera slower (default)
    # "camera" - only writes unique camera frames, variable timing (for frame-accurate analysis)
    frame_selection_mode: str = "timer"

    def __post_init__(self):
        """Calculate preview height to maintain aspect ratio"""
        if self.preview_height is None:
            width, height = self.resolution
            aspect_ratio = height / width
            self.preview_height = int(self.preview_width * aspect_ratio)
