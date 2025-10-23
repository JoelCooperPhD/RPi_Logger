
import logging
from pathlib import Path
from typing import Optional

from picamera2.encoders import H264Encoder
from picamera2.outputs import FileOutput

logger = logging.getLogger(__name__)


class H264EncoderWrapper:

    def __init__(self, picam2, bitrate: int = 10_000_000):
        self.picam2 = picam2
        self.bitrate = bitrate
        self._encoder: Optional[H264Encoder] = None
        self._output: Optional[FileOutput] = None
        self._is_running = False

    @property
    def is_running(self) -> bool:
        return self._is_running

    def start(self, video_path: Path) -> None:
        if self._is_running:
            raise RuntimeError("Encoder is already running")

        self._encoder = H264Encoder(bitrate=self.bitrate)
        self._output = FileOutput(str(video_path))

        try:
            self.picam2.start_encoder(self._encoder, self._output)
            self._is_running = True
            logger.debug("H264 encoder started: %s @ %d bps", video_path, self.bitrate)
        except Exception as e:
            logger.error("Failed to start H264 encoder: %s", e)
            self._encoder = None
            self._output = None
            raise

    def stop(self) -> None:
        if not self._is_running:
            return

        try:
            logger.debug("Stopping H264 encoder...")
            self.picam2.stop_encoder()
            logger.debug("Encoder stopped")
        except Exception as e:
            logger.warning("Error stopping encoder: %s", e)
        finally:
            self._encoder = None
            self._output = None
            self._is_running = False
