
import asyncio
import logging
from typing import Optional, Any
import os

# Set cv2 to headless mode before importing to avoid conflicts with Tkinter
os.environ['OPENCV_VIDEOIO_PRIORITY_MSMF'] = '0'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import cv2
import numpy as np
from .config.tracker_config import TrackerConfig as Config

logger = logging.getLogger(__name__)


class FrameProcessor:

    def __init__(self, config: Config):
        self.config = config
        self._logged_frame_info = False
        self._logged_extraction = False
        self._logged_color_info = False
        self._logged_gaze_debug = False
        self._logged_gaze_error = False

    def _draw_gaze_indicator(self, frame: np.ndarray, gaze_x: int, gaze_y: int, is_worn: bool) -> None:
        """Draw gaze indicator (circle or cross) at specified location using config settings"""
        # Get colors from config
        if is_worn:
            color = (self.config.gaze_color_worn_b, self.config.gaze_color_worn_g, self.config.gaze_color_worn_r)
        else:
            color = (self.config.gaze_color_not_worn_b, self.config.gaze_color_not_worn_g, self.config.gaze_color_not_worn_r)

        # Draw based on shape config
        if self.config.gaze_shape == "cross":
            # Draw cross
            arm_length = self.config.gaze_circle_radius
            thickness = self.config.gaze_circle_thickness
            # Horizontal line
            cv2.line(frame, (gaze_x - arm_length, gaze_y), (gaze_x + arm_length, gaze_y), color, thickness)
            # Vertical line
            cv2.line(frame, (gaze_x, gaze_y - arm_length), (gaze_x, gaze_y + arm_length), color, thickness)
        else:
            # Draw circle (default)
            cv2.circle(frame, (gaze_x, gaze_y), self.config.gaze_circle_radius, color, self.config.gaze_circle_thickness)

        # Draw center dot
        cv2.circle(frame, (gaze_x, gaze_y), self.config.gaze_center_radius, color, -1)

    def process_frame(self, raw_frame: np.ndarray) -> np.ndarray:
        try:
            h, w = raw_frame.shape[:2]

            if not self._logged_frame_info:
                logger.info(f"Raw frame shape: {raw_frame.shape}")
                if len(raw_frame.shape) == 3:
                    logger.info(f"Channels: {raw_frame.shape[2]}")
                self._logged_frame_info = True

            scene_frame = raw_frame

            if h > w * 1.1:  # Height is larger than width - likely tiled
                scene_height = h * 2 // 3
                scene_frame = raw_frame[:scene_height, :]

                if not self._logged_extraction:
                    logger.info(f"Extracting scene camera from tiled frame")
                    logger.info(f"Original: {h}x{w}, Scene: {scene_frame.shape}")
                    self._logged_extraction = True

            if len(scene_frame.shape) == 2:  # Grayscale
                processed_frame = cv2.cvtColor(scene_frame, cv2.COLOR_GRAY2BGR)

                if not self._logged_color_info:
                    logger.info("Scene camera is grayscale/monochrome - this is normal for Pupil Labs devices")
                    self._logged_color_info = True

            elif len(scene_frame.shape) == 3:
                if scene_frame.shape[2] == 1:  # Single channel in 3D array
                    processed_frame = cv2.cvtColor(scene_frame.squeeze(), cv2.COLOR_GRAY2BGR)
                elif scene_frame.shape[2] == 3:  # Already 3 channels
                    processed_frame = scene_frame
                elif scene_frame.shape[2] == 4:  # RGBA
                    processed_frame = cv2.cvtColor(scene_frame, cv2.COLOR_RGBA2BGR)
                else:
                    logger.warning(f"Unexpected channel count: {scene_frame.shape[2]}")
                    processed_frame = scene_frame
            else:
                logger.warning(f"Unexpected scene frame shape: {scene_frame.shape}")
                processed_frame = scene_frame

            return processed_frame

        except Exception as e:
            logger.error(f"Error processing frame: {e}")
            return raw_frame

    def add_display_overlays(
        self,
        frame: np.ndarray,
        frame_count: int,
        camera_frames: int,
        start_time: Optional[float],
        recording: bool,
        last_gaze: Optional[Any],
        rolling_camera_fps: Optional[float] = None,
        dropped_frames: int = 0,
        duplicates: int = 0,
        requested_fps: float = 30.0,
        experiment_label: Optional[str] = None,
    ) -> np.ndarray:
        """Overlay for preview window (gaze indicator only)."""

        # Add gaze circle if available
        if last_gaze:
            h, w = frame.shape[:2]
            gaze_x, gaze_y = None, None

            if hasattr(last_gaze, 'x') and hasattr(last_gaze, 'y'):
                try:
                    raw_x = float(last_gaze.x)
                    raw_y = float(last_gaze.y)

                    if raw_x > 1.0 or raw_y > 1.0:
                        gaze_x = int((raw_x / 1600.0) * w)
                        scene_y_in_full_frame = raw_y
                        if scene_y_in_full_frame <= 1200:
                            gaze_y = int((scene_y_in_full_frame / 1200.0) * h)
                        else:
                            gaze_y = h - 1
                    else:
                        gaze_x = int(raw_x * w)
                        gaze_y = int(raw_y * h)
                except Exception:
                    pass

            if gaze_x is not None and gaze_y is not None:
                gaze_x = max(0, min(gaze_x, w - 1))
                gaze_y = max(0, min(gaze_y, h - 1))

                is_worn = not (hasattr(last_gaze, 'worn') and not last_gaze.worn)
                self._draw_gaze_indicator(frame, gaze_x, gaze_y, is_worn)

        return frame

    def add_minimal_recording_overlay(
        self,
        frame: np.ndarray,
        frame_number: int,
        last_gaze: Optional[Any] = None,
        include_gaze: bool = True
    ) -> np.ndarray:
        """
        Minimal overlay for recording: frame number in upper left (matching camera style).
        Optionally includes gaze circle.
        """
        # Use config values
        font_scale = self.config.overlay_font_scale
        thickness = self.config.overlay_thickness
        text_color = (
            self.config.overlay_color_r,
            self.config.overlay_color_g,
            self.config.overlay_color_b,
        )
        margin_left = self.config.overlay_margin_left
        line_start_y = self.config.overlay_line_start_y

        frame_text = f"{frame_number}"

        border_thickness = max(1, thickness * 3)
        border_color = (0, 0, 0)

        cv2.putText(
            frame,
            frame_text,
            (margin_left, line_start_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            border_color,
            border_thickness,
            cv2.LINE_AA
        )

        cv2.putText(
            frame,
            frame_text,
            (margin_left, line_start_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            text_color,
            thickness,
            cv2.LINE_AA
        )

        if include_gaze and last_gaze:
            h, w = frame.shape[:2]
            gaze_x, gaze_y = None, None

            if hasattr(last_gaze, 'x') and hasattr(last_gaze, 'y'):
                try:
                    raw_x = float(last_gaze.x)
                    raw_y = float(last_gaze.y)

                    if raw_x > 1.0 or raw_y > 1.0:
                        gaze_x = int((raw_x / 1600.0) * w)
                        scene_y_in_full_frame = raw_y
                        if scene_y_in_full_frame <= 1200:
                            gaze_y = int((scene_y_in_full_frame / 1200.0) * h)
                        else:
                            gaze_y = h - 1
                    else:
                        gaze_x = int(raw_x * w)
                        gaze_y = int(raw_y * h)
                except Exception:
                    pass

            if gaze_x is not None and gaze_y is not None:
                gaze_x = max(0, min(gaze_x, w - 1))
                gaze_y = max(0, min(gaze_y, h - 1))

                is_worn = not (hasattr(last_gaze, 'worn') and not last_gaze.worn)
                self._draw_gaze_indicator(frame, gaze_x, gaze_y, is_worn)

        return frame

    def scale_for_preview(self, frame: np.ndarray) -> np.ndarray:
        """
        Scale frame down to preview size early in pipeline.
        This reduces CPU for all downstream operations (overlay, display).
        """
        h, w = frame.shape[:2]
        if w == self.config.preview_width:
            return frame  # Already at preview size

        preview_size = (self.config.preview_width, self.config.preview_height)
        scaled = cv2.resize(frame, preview_size, interpolation=cv2.INTER_LINEAR)
        return scaled

    def scale_gaze_coords(self, gaze_x: float, gaze_y: float,
                         from_resolution: tuple, to_resolution: tuple) -> tuple:
        """
        Scale gaze coordinates from one resolution to another.

        Args:
            gaze_x, gaze_y: Gaze coordinates (may be normalized [0-1] or absolute)
            from_resolution: (width, height) of source frame
            to_resolution: (width, height) of target frame

        Returns:
            (scaled_x, scaled_y) in pixel coordinates for target resolution
        """
        from_width, from_height = from_resolution
        to_width, to_height = to_resolution

        # Handle both normalized and absolute coordinates
        if gaze_x > 1.0 or gaze_y > 1.0:
            # Absolute coordinates - need special handling for tiled frames
            pixel_x = (gaze_x / 1600.0) * from_width
            scene_y = gaze_y
            if scene_y <= 1200:
                pixel_y = (scene_y / 1200.0) * from_height
            else:
                pixel_y = from_height - 1
        else:
            # Normalized coordinates
            pixel_x = gaze_x * from_width
            pixel_y = gaze_y * from_height

        # Scale to target resolution
        scale_x = to_width / from_width
        scale_y = to_height / from_height

        return int(pixel_x * scale_x), int(pixel_y * scale_y)

    def display_frame(self, frame: np.ndarray):
        h, w = frame.shape[:2]
        aspect = h / w
        display_h = int(self.config.display_width * aspect)
        resized = cv2.resize(frame, (self.config.display_width, display_h))
        cv2.imshow("Gaze Tracker", resized)

    def create_window(self):
        cv2.namedWindow("Gaze Tracker", cv2.WINDOW_NORMAL)

    def destroy_windows(self):
        cv2.destroyAllWindows()

    def check_keyboard(self) -> Optional[str]:
        """
        Check for keyboard input in OpenCV window.

        Returns:
            'quit' if user pressed Q
            'record' if user pressed R
            'pause' if user pressed P (Phase 1.4)
            None otherwise
        """
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            return 'quit'
        elif key == ord('r'):
            return 'record'
        elif key == ord('p'):  # Phase 1.4: Pause/resume
            return 'pause'
        return None

    async def process_frame_async(self, raw_frame: np.ndarray) -> np.ndarray:
        return await asyncio.to_thread(self.process_frame, raw_frame)

    async def add_display_overlays_async(
        self,
        frame: np.ndarray,
        frame_count: int,
        camera_frames: int,
        start_time: Optional[float],
        recording: bool,
        last_gaze: Optional[Any],
        rolling_camera_fps: Optional[float] = None,
        dropped_frames: int = 0,
        duplicates: int = 0,
        requested_fps: float = 30.0,
        experiment_label: Optional[str] = None,
    ) -> np.ndarray:
        return await asyncio.to_thread(
            self.add_display_overlays,
            frame,
            frame_count,
            camera_frames,
            start_time,
            recording,
            last_gaze,
            rolling_camera_fps,
            dropped_frames,
            duplicates,
            requested_fps,
            experiment_label,
        )

    async def display_frame_async(self, frame: np.ndarray) -> None:
        await asyncio.to_thread(self.display_frame, frame)

    async def check_keyboard_async(self) -> Optional[str]:
        return await asyncio.to_thread(self.check_keyboard)
