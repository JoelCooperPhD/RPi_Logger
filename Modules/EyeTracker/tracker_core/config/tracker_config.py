#!/usr/bin/env python3
"""
Eye Tracker Configuration

Dataclass for tracker configuration settings.
"""

from dataclasses import dataclass


@dataclass
class TrackerConfig:
    """Configuration for eye tracker."""
    fps: float = 5.0
    resolution: tuple = (1280, 720)
    output_dir: str = "recordings"
    display_width: int = 640
