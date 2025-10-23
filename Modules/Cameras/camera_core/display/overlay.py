
import datetime
import logging
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class CameraOverlay:

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
        cfg = self.config

        if not cfg.get('show_frame_number', True):
            return frame

        font_scale = cfg.get('font_scale_base', 0.6)
        thickness = cfg.get('thickness_base', 1)

        text_color_b = cfg.get('text_color_b', 0)
        text_color_g = cfg.get('text_color_g', 0)
        text_color_r = cfg.get('text_color_r', 0)
        text_color = (text_color_b, text_color_g, text_color_r)

        margin_left = cfg.get('margin_left', 10)
        line_start_y = cfg.get('line_start_y', 30)

        cv2.putText(
            frame,
            f"{collated_frames}",
            (margin_left, line_start_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            text_color,
            thickness,
            cv2.LINE_AA
        )

        if is_recording:
            frame_height, frame_width = frame.shape[:2]

            margin_right = cfg.get('rec_indicator_margin_right', 20)
            margin_top = cfg.get('rec_indicator_margin_top', 20)
            radius = cfg.get('rec_indicator_radius', 6)

            center_x = frame_width - margin_right
            center_y = margin_top

            cv2.circle(
                frame,
                (center_x, center_y),
                radius,
                (0, 0, 255),  # Red color in BGR
                -1,  # Filled circle
                cv2.LINE_AA
            )

        return frame
