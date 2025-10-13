#!/usr/bin/env python3
"""
Frame overlay handler for adding visual annotations to camera frames.

Adds frame numbers and other overlays to both recording and preview streams.
Uses MappedArray for zero-copy direct buffer access.
"""

import logging
from typing import Callable, Optional

import cv2
from picamera2 import MappedArray

logger = logging.getLogger("FrameOverlay")


class FrameOverlayHandler:
    """
    Manages frame overlay rendering for camera streams.

    Uses picamera2 post_callback mechanism to add overlays directly to
    frame buffers before encoding/display (zero-copy operation).

    Args:
        camera_id: Camera identifier for logging
        overlay_config: Dictionary with overlay configuration
        enable_overlay: Whether overlay is enabled
    """

    def __init__(self, camera_id: int, overlay_config: dict, enable_overlay: bool = True):
        self.camera_id = camera_id
        self.overlay_config = overlay_config
        self.enable_overlay = enable_overlay
        self._frame_count = 0
        self._is_recording = False

    def reset_frame_count(self) -> None:
        """Reset frame counter (called when starting recording)"""
        self._frame_count = 0

    def set_recording(self, is_recording: bool) -> None:
        """Update recording state (affects which streams get overlay)"""
        self._is_recording = is_recording

    def get_frame_count(self) -> int:
        """Get current frame count"""
        return self._frame_count

    def create_callback(self) -> Callable:
        """
        Create post_callback function for picamera2.

        Returns:
            Callback function suitable for picamera2.post_callback
        """
        def overlay_callback(request):
            """
            Post-callback that adds overlay to BOTH main and lores streams.

            This is called by picamera2 for every frame before encoding/display.
            We add frame number overlay here so it appears identically on both:
            - main stream → H.264 encoder → recording
            - lores stream → capture loop → preview

            CRITICAL: Uses MappedArray to get DIRECT access to frame buffers.
            This ensures cv2.putText modifications affect what encoder/preview see.
            Using make_array() would return a COPY, which wouldn't affect encoding.

            EFFICIENCY: Overlay is rendered ONCE per stream at camera level,
            not duplicated in Python processing code. Single source of truth.
            """
            if not self.enable_overlay:
                return request

            try:
                # Increment frame count
                self._frame_count += 1

                # Get overlay configuration
                font_scale = self.overlay_config.get('font_scale_base', 0.6)
                thickness = self.overlay_config.get('thickness_base', 1)

                # Text color (BGR in config → RGB for picamera2)
                text_color_b = self.overlay_config.get('text_color_b', 0)
                text_color_g = self.overlay_config.get('text_color_g', 0)
                text_color_r = self.overlay_config.get('text_color_r', 0)
                text_color = (text_color_r, text_color_g, text_color_b)

                margin_left = self.overlay_config.get('margin_left', 10)
                line_start_y = self.overlay_config.get('line_start_y', 30)

                frame_text = f"Frame: {self._frame_count}"

                # Add overlay to MAIN stream (for recording) when encoder is running
                if self._is_recording:
                    try:
                        with MappedArray(request, "main") as m:
                            cv2.putText(
                                m.array,
                                frame_text,
                                (margin_left, line_start_y),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                font_scale,
                                text_color,
                                thickness,
                                cv2.LINE_AA
                            )
                    except Exception as e:
                        if self._frame_count <= 3:
                            logger.warning("Camera %d: Could not overlay on main stream: %s",
                                         self.camera_id, e)

            except Exception as e:
                logger.error("Error in overlay callback for camera %d: %s", self.camera_id, e)

            return request

        return overlay_callback
