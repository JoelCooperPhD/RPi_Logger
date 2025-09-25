#!/usr/bin/env python3
"""
Configuration for Gaze Tracker
"""

from dataclasses import dataclass


@dataclass
class Config:
    """Configuration for gaze tracker"""
    fps: float = 5.0
    resolution: tuple = (1280, 720)
    output_dir: str = "video_out"
    display_width: int = 640