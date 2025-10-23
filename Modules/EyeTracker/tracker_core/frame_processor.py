
import asyncio
import time
import datetime
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

    def add_overlays(
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
        h, w = frame.shape[:2]
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.6
        thickness = 2

        overlay = frame.copy()
        banner_height = 200
        cv2.rectangle(overlay, (0, 0), (w, banner_height), (255, 255, 255), -1)
        cv2.addWeighted(frame, 0.7, overlay, 0.3, 0, dst=frame)

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(frame, f"Time: {timestamp}", (10, 25),
                   font, font_scale, (0, 0, 0), thickness)

        if start_time:
            available_fps = rolling_camera_fps if rolling_camera_fps is not None else (camera_frames / (time.time() - start_time) if start_time else 0)

            cv2.putText(frame, f"Available FPS: {available_fps:.1f}", (10, 50),
                       font, font_scale, (0, 0, 0), thickness)
            cv2.putText(frame, f"Requested FPS: {requested_fps:.1f}", (10, 75),
                       font, font_scale, (0, 0, 0), thickness)
            cv2.putText(frame, f"Dropped: {dropped_frames}", (10, 100),
                       font, font_scale, (0, 0, 0), thickness)
            cv2.putText(frame, f"Duplicated: {duplicates}", (10, 125),
                       font, font_scale, (0, 0, 0), thickness)
            cv2.putText(frame, f"Display Frames: {frame_count}", (10, 150),
                       font, font_scale, (0, 0, 0), thickness)

        if experiment_label:
            cv2.putText(frame, f"Experiment: {experiment_label}", (10, 175),
                       font, font_scale, (0, 0, 0), thickness)

        if recording:
            cv2.putText(frame, "RECORDING", (w - 150, 30),
                       font, font_scale, (0, 0, 255), thickness)

        if last_gaze:
            gaze_x, gaze_y = None, None

            # Debug gaze data once
            if not self._logged_gaze_debug:
                logger.info(f"Gaze x: {getattr(last_gaze, 'x', 'None')}, y: {getattr(last_gaze, 'y', 'None')}")
                if hasattr(last_gaze, 'x') and hasattr(last_gaze, 'y'):
                    logger.info(f"Raw gaze coordinates: x={last_gaze.x}, y={last_gaze.y}")
                    logger.info(f"Frame dimensions: {w}x{h}")
                self._logged_gaze_debug = True

            if hasattr(last_gaze, 'x') and hasattr(last_gaze, 'y'):
                try:
                    raw_x = float(last_gaze.x)
                    raw_y = float(last_gaze.y)

                    if raw_x > 1.0 or raw_y > 1.0:

                        gaze_x = int((raw_x / 1600.0) * w)

                        scene_y_in_full_frame = raw_y
                        if scene_y_in_full_frame <= 1200:  # Within scene camera area
                            gaze_y = int((scene_y_in_full_frame / 1200.0) * h)
                        else:
                            gaze_y = h - 1
                    else:
                        gaze_x = int(raw_x * w)
                        gaze_y = int(raw_y * h)

                except Exception as e:
                    if not self._logged_gaze_error:
                        logger.error(f"Gaze coordinate error: {e}")
                        self._logged_gaze_error = True

            if gaze_x is not None and gaze_y is not None:
                gaze_x = max(0, min(gaze_x, w - 1))
                gaze_y = max(0, min(gaze_y, h - 1))

                color = (0, 255, 255)  # Yellow for worn
                if hasattr(last_gaze, 'worn') and not last_gaze.worn:
                    color = (0, 0, 255)  # Red if not worn

                cv2.circle(frame, (gaze_x, gaze_y), 30, color, 3)
                cv2.circle(frame, (gaze_x, gaze_y), 2, color, -1)

        cv2.putText(frame, "Q: Quit | R: Record", (w - 200, h - 10),
                   font, 0.5, (255, 255, 255), 1)

        return frame

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
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            return 'quit'
        elif key == ord('r'):
            return 'record'
        return None

    async def process_frame_async(self, raw_frame: np.ndarray) -> np.ndarray:
        return await asyncio.to_thread(self.process_frame, raw_frame)

    async def add_overlays_async(
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
            self.add_overlays,
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
