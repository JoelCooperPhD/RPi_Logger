#!/usr/bin/env python3
"""
CAMERA OVERLAY - Overlay rendering only.

This module handles ONLY overlay rendering:
- Text overlays (camera info, FPS, frame counters, etc.)
- Recording indicators
- Control hints
- Background boxes

Takes a frame, config, and metadata → Returns frame with overlays
"""

import datetime
import logging
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger("CameraOverlay")


class CameraOverlay:
    """
    Overlay renderer for camera frames.

    Stateless - just renders overlays based on provided config and metadata.
    """

    def __init__(self, camera_id: int, overlay_config: dict):
        self.camera_id = camera_id
        self.config = overlay_config
        self.logger = logging.getLogger(f"CameraOverlay{camera_id}")

    def add_overlays(
        self,
        frame: np.ndarray,
        *,
        capture_fps: float,
        collation_fps: float,
        captured_frames: int,
        collated_frames: int,
        requested_fps: float,
        is_recording: bool,
        recording_filename: Optional[str],
        recorded_frames: int,
        session_name: str,
    ) -> np.ndarray:
        """
        Add overlays to frame.

        NOTE: Recording overlay is added via post_callback (main stream only).
        Preview overlay is added here because capture_array("lores") bypasses post_callback.
        """
        cfg = self.config

        # Only render overlay if enabled
        if not cfg.get('show_frame_number', True):
            return frame

        # Simple frame number overlay (matches recording exactly)
        font_scale = cfg.get('font_scale_base', 0.6)
        thickness = cfg.get('thickness_base', 1)

        # Text color (BGR)
        text_color_b = cfg.get('text_color_b', 0)
        text_color_g = cfg.get('text_color_g', 0)
        text_color_r = cfg.get('text_color_r', 0)
        text_color = (text_color_b, text_color_g, text_color_r)

        margin_left = cfg.get('margin_left', 10)
        line_start_y = cfg.get('line_start_y', 30)

        # Draw frame number (matches recording format exactly)
        cv2.putText(
            frame,
            f"Frame: {collated_frames}",
            (margin_left, line_start_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            text_color,
            thickness,
            cv2.LINE_AA
        )

        # Draw recording indicator (red circle in upper right corner)
        if is_recording:
            # Get frame dimensions
            frame_height, frame_width = frame.shape[:2]

            # Position: upper right corner with margin
            margin_right = cfg.get('rec_indicator_margin_right', 20)
            margin_top = cfg.get('rec_indicator_margin_top', 20)
            radius = cfg.get('rec_indicator_radius', 6)

            # Calculate center position for the circle
            center_x = frame_width - margin_right
            center_y = margin_top

            # Draw red circle (BGR: red = (0, 0, 255))
            cv2.circle(
                frame,
                (center_x, center_y),
                radius,
                (0, 0, 255),  # Red color in BGR
                -1,  # Filled circle
                cv2.LINE_AA
            )

        return frame
