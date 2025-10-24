
from dataclasses import dataclass
from typing import Optional


@dataclass
class TrackerConfig:
    fps: float = 5.0
    resolution: tuple = (1280, 720)
    output_dir: str = "recordings"
    display_width: int = 640
    gui_logger_visible: bool = True  # Logger visibility in GUI

    # Phase 1.3: Preview resolution for early scaling
    preview_width: int = 640
    preview_height: Optional[int] = None

    def __post_init__(self):
        """Calculate preview height to maintain aspect ratio"""
        if self.preview_height is None:
            width, height = self.resolution
            aspect_ratio = height / width
            self.preview_height = int(self.preview_width * aspect_ratio)
