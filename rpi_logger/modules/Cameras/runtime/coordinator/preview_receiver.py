"""
Preview frame receiver for the main process.

Decodes JPEG preview frames from workers and dispatches to UI.
"""
from __future__ import annotations

import logging
from typing import Callable, Dict, Optional

import cv2
import numpy as np

from rpi_logger.modules.Cameras.worker.protocol import RespPreviewFrame

logger = logging.getLogger(__name__)


class PreviewReceiver:
    """
    Receives preview frames from workers and dispatches to UI consumers.

    Replaces the PreviewPipeline for worker-based architecture.
    """

    def __init__(self) -> None:
        self._consumers: dict[str, Callable[[np.ndarray], None]] = {}
        self._frame_counts: Dict[str, int] = {}
        self._decode_errors: Dict[str, int] = {}
        logger.info("[PREVIEW_RECV] PreviewReceiver initialized")

    def set_consumer(self, key: str, consumer: Callable[[np.ndarray], None]) -> None:
        """Register a consumer callback for a camera's preview frames."""
        logger.info("[PREVIEW_RECV] Consumer registered for %s", key)
        self._consumers[key] = consumer
        self._frame_counts[key] = 0
        self._decode_errors[key] = 0

    def remove_consumer(self, key: str) -> None:
        """Unregister a consumer callback."""
        logger.info("[PREVIEW_RECV] Consumer removed for %s (processed %d frames, %d decode errors)",
                   key, self._frame_counts.get(key, 0), self._decode_errors.get(key, 0))
        self._consumers.pop(key, None)
        self._frame_counts.pop(key, None)
        self._decode_errors.pop(key, None)

    def on_preview_frame(self, key: str, msg: RespPreviewFrame) -> None:
        """
        Handle a preview frame from a worker.

        Decodes JPEG and dispatches to registered consumer.
        """
        consumer = self._consumers.get(key)
        if not consumer:
            # Log only first time we see frames with no consumer
            if key not in self._frame_counts or self._frame_counts.get(key, 0) == 0:
                logger.warning("[PREVIEW_RECV] No consumer for %s - frame dropped", key)
            return

        self._frame_counts[key] = self._frame_counts.get(key, 0) + 1
        count = self._frame_counts[key]

        try:
            # Decode JPEG
            arr = np.frombuffer(msg.frame_data, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is not None:
                if count == 1:
                    logger.info("[PREVIEW_RECV] %s: First frame decoded! shape=%s, jpeg_size=%d bytes",
                               key, frame.shape, len(msg.frame_data))
                elif count % 30 == 0:
                    logger.debug("[PREVIEW_RECV] %s: frame #%d decoded, shape=%s",
                                key, count, frame.shape)
                consumer(frame)
            else:
                self._decode_errors[key] = self._decode_errors.get(key, 0) + 1
                if self._decode_errors[key] <= 3:
                    logger.warning("[PREVIEW_RECV] %s: JPEG decode returned None (error #%d)",
                                  key, self._decode_errors[key])
        except Exception as e:
            self._decode_errors[key] = self._decode_errors.get(key, 0) + 1
            if self._decode_errors[key] <= 3:
                logger.error("[PREVIEW_RECV] %s: Failed to decode preview frame: %s", key, e)


__all__ = ["PreviewReceiver"]
