
from dataclasses import dataclass
from typing import Optional


@dataclass
class TrackerConfig:
    # Recording settings (downsampled from Neon raw 1600x1200 @ 30Hz)
    fps: float = 10.0
    resolution: tuple = (800, 600)
    output_dir: str = "recordings"

    # Preview settings
    preview_width: int = 400
    preview_height: Optional[int] = None
    preview_fps: float = 10.0
    display_width: int = 640

    # Stream viewer enable states (persisted)
    stream_video_enabled: bool = True
    stream_gaze_enabled: bool = True
    stream_eyes_enabled: bool = False
    stream_imu_enabled: bool = False
    stream_events_enabled: bool = False
    stream_audio_enabled: bool = False

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
    gaze_circle_radius: int = 60
    gaze_circle_thickness: int = 6
    gaze_center_radius: int = 4
    gaze_shape: str = "circle"
    gaze_color_worn_b: int = 0
    gaze_color_worn_g: int = 0
    gaze_color_worn_r: int = 255

    # Data export controls
    audio_stream_param: str = "audio=scene"

    # IMU visualization settings
    imu_sparkline_duration_sec: float = 10.0  # Seconds of motion history to display
    imu_motion_still_threshold: float = 0.02  # g deviation for STILL state (subtle head movements)
    imu_motion_rapid_threshold: float = 0.08  # g deviation for RAPID state

    # Neon scene camera delivers 30 fps
    NEON_SCENE_FPS: float = 30.0

    def __post_init__(self):
        """Calculate preview height to maintain aspect ratio"""
        if self.preview_height is None:
            width, height = self.resolution
            aspect_ratio = height / width
            self.preview_height = int(self.preview_width * aspect_ratio)

    def recording_skip_factor(self) -> int:
        """Compute frame skip factor from fps.

        Since the Neon scene camera delivers 30fps, we skip frames to achieve
        lower effective FPS. For example:
        - 30 fps -> skip_factor=1 (write every frame)
        - 15 fps -> skip_factor=2 (write every 2nd frame)
        - 10 fps -> skip_factor=3 (write every 3rd frame)
        - 7.5 fps -> skip_factor=4 (write every 4th frame)
        """
        return max(1, round(self.NEON_SCENE_FPS / self.fps))

    def preview_skip_factor(self) -> int:
        """Compute frame skip factor from preview_fps.

        Same logic as recording_skip_factor but for preview display.
        """
        return max(1, round(self.NEON_SCENE_FPS / self.preview_fps))
