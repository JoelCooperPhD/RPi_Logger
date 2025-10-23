
import logging

logger = logging.getLogger(__name__)


class CameraConfig:

    @staticmethod
    def validate_fps(requested_fps: float, min_fps: float = 1.0, max_fps: float = 60.0) -> float:
        if requested_fps > max_fps:
            logger.warning(
                "Requested FPS (%.1f) exceeds hardware limit (%.1f). Capping at %.1f FPS.",
                requested_fps, max_fps, max_fps
            )
            return max_fps
        elif requested_fps < min_fps:
            logger.warning(
                "Requested FPS (%.1f) is below minimum (%.1f). Setting to %.1f FPS.",
                requested_fps, min_fps, min_fps
            )
            return min_fps
        return requested_fps

    @staticmethod
    def calculate_frame_duration_us(fps: float) -> int:
        return int(1e6 / fps)

    @staticmethod
    def log_resolution_info(camera_id: int, width: int, height: int):
        try:
            from cli_utils import RESOLUTION_TO_PRESET, RESOLUTION_PRESETS

            resolution_tuple = (width, height)
            if resolution_tuple in RESOLUTION_TO_PRESET:
                preset_num = RESOLUTION_TO_PRESET[resolution_tuple]
                _, _, desc, aspect = RESOLUTION_PRESETS[preset_num]
                logger.info(
                    "Camera %d using resolution preset %d: %dx%d - %s (%s)",
                    camera_id, preset_num, width, height, desc, aspect
                )
            else:
                logger.info("Camera %d using custom resolution: %dx%d", camera_id, width, height)
        except ImportError:
            logger.info("Camera %d using resolution: %dx%d", camera_id, width, height)
