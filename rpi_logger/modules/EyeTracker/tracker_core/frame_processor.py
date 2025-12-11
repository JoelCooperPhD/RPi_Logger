import asyncio
from typing import Optional, Any, Tuple, Dict
import os

# Set cv2 to headless mode before importing to avoid conflicts with Tkinter
os.environ['OPENCV_VIDEOIO_PRIORITY_MSMF'] = '0'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import cv2
import numpy as np
from rpi_logger.core.logging_utils import get_module_logger
from .config.tracker_config import TrackerConfig as Config

logger = get_module_logger(__name__)


class FrameProcessor:

    def __init__(self, config: Config):
        self.config = config
        self._logged_gaze_error = False
        # Phase 2.2: Sprite cache for gaze indicators
        self._gaze_sprite_cache: Dict[tuple, np.ndarray] = {}
        # Phase 2.3: Duplicate frame detection
        self._last_frame_hash: Optional[int] = None
        self._last_processed: Optional[np.ndarray] = None
        self._last_was_grayscale: bool = False
        self._duplicate_count = 0

    def _get_gaze_color(self) -> Tuple[int, int, int]:
        """Get gaze indicator color."""
        return (self.config.gaze_color_worn_b, self.config.gaze_color_worn_g, self.config.gaze_color_worn_r)

    def _get_gaze_sprite(self, radius: int, thickness: int, color: Tuple[int, int, int],
                         shape: str, center_radius: int) -> np.ndarray:
        """Get cached gaze indicator sprite with contrasting outline for visibility."""
        cache_key = (radius, thickness, color, shape, center_radius)
        if cache_key not in self._gaze_sprite_cache:
            # Create sprite with alpha channel for blending
            # Extra padding for outline
            outline_thickness = thickness + 2
            size = radius * 2 + outline_thickness * 2 + 8
            sprite = np.zeros((size, size, 4), dtype=np.uint8)
            center = size // 2

            # Determine contrasting outline color (black or white based on main color brightness)
            brightness = (color[0] + color[1] + color[2]) / 3
            outline_color = (0, 0, 0) if brightness > 127 else (255, 255, 255)

            if shape == "cross":
                # Draw outline first (thicker, contrasting color)
                cv2.line(sprite, (center - radius, center), (center + radius, center),
                        (*outline_color, 255), outline_thickness)
                cv2.line(sprite, (center, center - radius), (center, center + radius),
                        (*outline_color, 255), outline_thickness)
                # Draw main cross on top
                cv2.line(sprite, (center - radius, center), (center + radius, center),
                        (*color, 255), thickness)
                cv2.line(sprite, (center, center - radius), (center, center + radius),
                        (*color, 255), thickness)
            else:
                # Draw outline circle first (thicker, contrasting color)
                cv2.circle(sprite, (center, center), radius, (*outline_color, 255), outline_thickness)
                # Draw main circle on top
                cv2.circle(sprite, (center, center), radius, (*color, 255), thickness)

            # Draw center dot with outline
            cv2.circle(sprite, (center, center), center_radius + 1, (*outline_color, 255), -1)
            cv2.circle(sprite, (center, center), center_radius, (*color, 255), -1)

            self._gaze_sprite_cache[cache_key] = sprite

            # Limit cache size
            if len(self._gaze_sprite_cache) > 20:
                # Remove oldest entry
                oldest_key = next(iter(self._gaze_sprite_cache))
                del self._gaze_sprite_cache[oldest_key]

        return self._gaze_sprite_cache[cache_key]

    def _draw_gaze_indicator(self, frame: np.ndarray, gaze_x: int, gaze_y: int) -> None:
        """Draw gaze indicator using cached sprite (faster than cv2.circle every frame)."""
        color = self._get_gaze_color()
        sprite = self._get_gaze_sprite(
            self.config.gaze_circle_radius,
            self.config.gaze_circle_thickness,
            color,
            self.config.gaze_shape,
            self.config.gaze_center_radius,
        )

        # Calculate blit region
        sprite_h, sprite_w = sprite.shape[:2]
        half_h, half_w = sprite_h // 2, sprite_w // 2

        # Frame bounds
        frame_h, frame_w = frame.shape[:2]

        # Source and destination regions (handle edge clipping)
        src_y1 = max(0, half_h - gaze_y)
        src_y2 = min(sprite_h, half_h + (frame_h - gaze_y))
        src_x1 = max(0, half_w - gaze_x)
        src_x2 = min(sprite_w, half_w + (frame_w - gaze_x))

        dst_y1 = max(0, gaze_y - half_h)
        dst_y2 = min(frame_h, gaze_y + half_h)
        dst_x1 = max(0, gaze_x - half_w)
        dst_x2 = min(frame_w, gaze_x + half_w)

        if dst_y2 > dst_y1 and dst_x2 > dst_x1:
            # Blend sprite onto frame using alpha
            sprite_region = sprite[src_y1:src_y2, src_x1:src_x2]
            alpha = sprite_region[:, :, 3:4] / 255.0
            frame_region = frame[dst_y1:dst_y2, dst_x1:dst_x2]
            blended = (sprite_region[:, :, :3] * alpha + frame_region * (1 - alpha)).astype(np.uint8)
            frame[dst_y1:dst_y2, dst_x1:dst_x2] = blended

    def process_frame(self, raw_frame: np.ndarray) -> np.ndarray:
        """Process frame (legacy API - always returns BGR)."""
        frame, _ = self.process_frame_lazy(raw_frame)
        return frame

    def process_frame_lazy(self, raw_frame: np.ndarray, *, skip_duplicates: bool = False) -> Tuple[np.ndarray, bool]:
        """
        Process raw frame from camera with lazy color conversion.

        Args:
            raw_frame: Raw frame from camera
            skip_duplicates: If True, return cached result for duplicate frames

        Returns:
            Tuple of (processed_frame, is_grayscale)
            Keeps grayscale frames as-is when possible for efficiency.
        """
        try:
            # Phase 2.3: Fast duplicate detection using sparse sampling
            if skip_duplicates:
                # Sample every 64th pixel in a grid pattern for fast hash
                sample = raw_frame[::64, ::64]
                frame_hash = hash(sample.tobytes())

                if frame_hash == self._last_frame_hash and self._last_processed is not None:
                    self._duplicate_count += 1
                    return self._last_processed, self._last_was_grayscale

            h, w = raw_frame.shape[:2]
            scene_frame = raw_frame

            if h > w * 1.1:  # Height is larger than width - likely tiled
                scene_height = h * 2 // 3
                scene_frame = raw_frame[:scene_height, :]

            processed: np.ndarray
            is_grayscale: bool

            if len(scene_frame.shape) == 2:  # Grayscale
                # Phase 2.1: Return grayscale directly, let caller convert if needed
                processed, is_grayscale = scene_frame, True

            elif len(scene_frame.shape) == 3:
                if scene_frame.shape[2] == 1:  # Single channel in 3D array
                    processed, is_grayscale = scene_frame.squeeze(), True  # Still grayscale
                elif scene_frame.shape[2] == 3:  # Already BGR
                    processed, is_grayscale = scene_frame, False
                elif scene_frame.shape[2] == 4:  # RGBA
                    processed, is_grayscale = cv2.cvtColor(scene_frame, cv2.COLOR_RGBA2BGR), False
                else:
                    processed, is_grayscale = scene_frame, False
            else:
                processed, is_grayscale = scene_frame, len(scene_frame.shape) == 2

            # Cache for next comparison
            if skip_duplicates:
                self._last_frame_hash = frame_hash
                self._last_processed = processed
                self._last_was_grayscale = is_grayscale

            return processed, is_grayscale

        except Exception as e:
            logger.error("Error processing frame: %s", e)
            return raw_frame, len(raw_frame.shape) == 2

    @property
    def duplicate_frames_skipped(self) -> int:
        return self._duplicate_count

    def ensure_bgr(self, frame: np.ndarray, is_grayscale: bool) -> np.ndarray:
        """Convert to BGR only when needed (for overlay drawing)."""
        if is_grayscale:
            return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        return frame

    def add_display_overlays(
        self,
        frame: np.ndarray,
        last_gaze: Optional[Any],
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
                except (ValueError, TypeError) as e:
                    if not self._logged_gaze_error:
                        logger.debug("Gaze coordinate conversion error: %s", e)
                        self._logged_gaze_error = True

            if gaze_x is not None and gaze_y is not None:
                gaze_x = max(0, min(gaze_x, w - 1))
                gaze_y = max(0, min(gaze_y, h - 1))
                self._draw_gaze_indicator(frame, gaze_x, gaze_y)

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
                except (ValueError, TypeError) as e:
                    if not self._logged_gaze_error:
                        logger.debug("Gaze coordinate conversion error: %s", e)
                        self._logged_gaze_error = True

            if gaze_x is not None and gaze_y is not None:
                gaze_x = max(0, min(gaze_x, w - 1))
                gaze_y = max(0, min(gaze_y, h - 1))
                self._draw_gaze_indicator(frame, gaze_x, gaze_y)

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
        scaled = cv2.resize(frame, preview_size, interpolation=cv2.INTER_AREA)
        return scaled

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

    async def process_frame_lazy_async(self, raw_frame: np.ndarray) -> Tuple[np.ndarray, bool]:
        return await asyncio.to_thread(self.process_frame_lazy, raw_frame)
