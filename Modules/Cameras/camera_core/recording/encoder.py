#!/usr/bin/env python3
"""
Hardware H.264 encoder wrapper for picamera2.
Provides simple interface for starting/stopping hardware-accelerated video encoding.
"""

import logging
from pathlib import Path
from typing import Optional

from picamera2.encoders import H264Encoder
from picamera2.outputs import FileOutput

logger = logging.getLogger("H264EncoderWrapper")


class H264EncoderWrapper:
    """
    Wrapper for picamera2 H264Encoder with hardware acceleration.

    Manages encoder lifecycle and file output.

    Args:
        picam2: Picamera2 instance to attach encoder to
        bitrate: Video bitrate in bits per second
    """

    def __init__(self, picam2, bitrate: int = 10_000_000):
        self.picam2 = picam2
        self.bitrate = bitrate
        self._encoder: Optional[H264Encoder] = None
        self._output: Optional[FileOutput] = None
        self._is_running = False

    @property
    def is_running(self) -> bool:
        """Check if encoder is currently running"""
        return self._is_running

    def start(self, video_path: Path) -> None:
        """
        Start hardware-accelerated H.264 encoding to file.

        Args:
            video_path: Path to output video file (.h264)

        Raises:
            RuntimeError: If encoder is already running
            Exception: If encoder fails to start
        """
        if self._is_running:
            raise RuntimeError("Encoder is already running")

        # Create H264 encoder with hardware acceleration
        self._encoder = H264Encoder(bitrate=self.bitrate)
        self._output = FileOutput(str(video_path))

        # Start encoder
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
        """
        Stop hardware encoder.

        Safe to call even if encoder is not running.
        """
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
