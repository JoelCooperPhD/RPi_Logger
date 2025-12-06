"""
Preview frame receiver for the main process.

Decodes JPEG preview frames from workers and dispatches to UI.
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Dict, Optional

import cv2
import numpy as np

from rpi_logger.modules.Cameras.worker.protocol import RespPreviewFrame

logger = logging.getLogger(__name__)

# Backpressure configuration
MAX_PENDING_FRAMES = 3  # Max frames waiting to be consumed per camera
FRAME_DROP_LOG_INTERVAL = 30  # Log frame drops every N drops


class PreviewReceiver:
    """
    Receives preview frames from workers and dispatches to UI consumers.

    Replaces the PreviewPipeline for worker-based architecture.

    Includes backpressure mechanism to prevent memory buildup when UI is slow:
    - Tracks pending frames per camera
    - Drops frames if consumer is falling behind
    - Logs dropped frame statistics periodically
    """

    def __init__(self, max_pending: int = MAX_PENDING_FRAMES) -> None:
        self._consumers: dict[str, Callable[[np.ndarray], None]] = {}
        self._frame_counts: Dict[str, int] = {}
        self._decode_errors: Dict[str, int] = {}
        self._dropped_frames: Dict[str, int] = {}
        self._pending_frames: Dict[str, int] = {}
        self._last_frame_time: Dict[str, float] = {}
        self._max_pending = max_pending
        logger.info("[PREVIEW_RECV] PreviewReceiver initialized (max_pending=%d)", max_pending)

    def set_consumer(self, key: str, consumer: Callable[[np.ndarray], None]) -> None:
        """Register a consumer callback for a camera's preview frames."""
        logger.info("[PREVIEW_RECV] Consumer registered for %s", key)
        self._consumers[key] = consumer
        self._frame_counts[key] = 0
        self._decode_errors[key] = 0
        self._dropped_frames[key] = 0
        self._pending_frames[key] = 0
        self._last_frame_time[key] = 0.0

    def remove_consumer(self, key: str) -> None:
        """Unregister a consumer callback."""
        dropped = self._dropped_frames.get(key, 0)
        processed = self._frame_counts.get(key, 0)
        errors = self._decode_errors.get(key, 0)
        logger.info("[PREVIEW_RECV] Consumer removed for %s (processed=%d, dropped=%d, errors=%d)",
                   key, processed, dropped, errors)
        self._consumers.pop(key, None)
        self._frame_counts.pop(key, None)
        self._decode_errors.pop(key, None)
        self._dropped_frames.pop(key, None)
        self._pending_frames.pop(key, None)
        self._last_frame_time.pop(key, None)

    def on_preview_frame(self, key: str, msg: RespPreviewFrame) -> None:
        """
        Handle a preview frame from a worker.

        Decodes JPEG and dispatches to registered consumer.
        Implements backpressure by dropping frames if consumer is falling behind.
        """
        consumer = self._consumers.get(key)
        if not consumer:
            # Log only first time we see frames with no consumer
            if key not in self._frame_counts or self._frame_counts.get(key, 0) == 0:
                logger.warning("[PREVIEW_RECV] No consumer for %s - frame dropped", key)
            return

        # Backpressure: check if we should drop this frame
        pending = self._pending_frames.get(key, 0)
        if pending >= self._max_pending:
            # Consumer is falling behind - drop frame
            self._dropped_frames[key] = self._dropped_frames.get(key, 0) + 1
            dropped_count = self._dropped_frames[key]
            if dropped_count == 1 or dropped_count % FRAME_DROP_LOG_INTERVAL == 0:
                logger.warning("[PREVIEW_RECV] %s: Frame dropped (total dropped=%d, pending=%d)",
                             key, dropped_count, pending)
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
                    dropped = self._dropped_frames.get(key, 0)
                    logger.debug("[PREVIEW_RECV] %s: frame #%d decoded, shape=%s, dropped=%d",
                                key, count, frame.shape, dropped)

                # Track pending frames before dispatching
                self._pending_frames[key] = pending + 1
                self._last_frame_time[key] = time.monotonic()

                # Dispatch to consumer
                consumer(frame)

                # Frame consumed - reduce pending count
                self._pending_frames[key] = max(0, self._pending_frames.get(key, 1) - 1)
            else:
                self._decode_errors[key] = self._decode_errors.get(key, 0) + 1
                if self._decode_errors[key] <= 3:
                    logger.warning("[PREVIEW_RECV] %s: JPEG decode returned None (error #%d)",
                                  key, self._decode_errors[key])
        except Exception as e:
            self._decode_errors[key] = self._decode_errors.get(key, 0) + 1
            if self._decode_errors[key] <= 3:
                logger.error("[PREVIEW_RECV] %s: Failed to decode preview frame: %s", key, e)

    def get_stats(self, key: str) -> Dict[str, int]:
        """Get statistics for a camera's preview frames."""
        return {
            "processed": self._frame_counts.get(key, 0),
            "dropped": self._dropped_frames.get(key, 0),
            "errors": self._decode_errors.get(key, 0),
            "pending": self._pending_frames.get(key, 0),
        }


__all__ = ["PreviewReceiver"]
