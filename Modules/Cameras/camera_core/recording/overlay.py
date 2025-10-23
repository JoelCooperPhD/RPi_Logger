
import logging
import threading
from typing import Callable, Optional

import cv2
from picamera2 import MappedArray

logger = logging.getLogger(__name__)


class FrameOverlayHandler:

    def __init__(self, camera_id: int, overlay_config: dict, enable_overlay: bool = True):
        self.camera_id = camera_id
        self.overlay_config = overlay_config
        self.enable_overlay = enable_overlay
        self._frame_count = 0
        self._is_recording = False
        self._count_lock = threading.Lock()  # Protect frame counter from race conditions

    def reset_frame_count(self) -> None:
        with self._count_lock:
            self._frame_count = 0

    def set_recording(self, is_recording: bool) -> None:
        self._is_recording = is_recording

    def get_frame_count(self) -> int:
        with self._count_lock:
            return self._frame_count

    def create_callback(self) -> Callable:
        def overlay_callback(request):
            if not self.enable_overlay:
                return request

            try:
                with self._count_lock:
                    self._frame_count += 1
                    current_frame_num = self._frame_count

                font_scale = self.overlay_config.get('font_scale_base', 0.6)
                thickness = self.overlay_config.get('thickness_base', 1)

                text_color_b = self.overlay_config.get('text_color_b', 0)
                text_color_g = self.overlay_config.get('text_color_g', 0)
                text_color_r = self.overlay_config.get('text_color_r', 0)
                text_color = (text_color_r, text_color_g, text_color_b)

                margin_left = self.overlay_config.get('margin_left', 10)
                line_start_y = self.overlay_config.get('line_start_y', 30)

                frame_text = f"{current_frame_num}"

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
                        if current_frame_num <= 3:
                            logger.warning("Camera %d: Could not overlay on main stream: %s",
                                         self.camera_id, e)

            except Exception as e:
                logger.error("Error in overlay callback for camera %d: %s", self.camera_id, e)

            return request

        return overlay_callback
