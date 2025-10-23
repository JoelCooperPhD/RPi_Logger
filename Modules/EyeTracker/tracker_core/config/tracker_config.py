
from dataclasses import dataclass


@dataclass
class TrackerConfig:
    fps: float = 5.0
    resolution: tuple = (1280, 720)
    output_dir: str = "recordings"
    display_width: int = 640
    gui_logger_visible: bool = True  # Logger visibility in GUI
