"""
Shared memory preview buffer management.

Provides zero-copy preview frame transfer between worker and main process
by using shared memory with double-buffering.
"""
from __future__ import annotations

import logging
from multiprocessing.shared_memory import SharedMemory
from typing import Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class PreviewSharedBuffer:
    """
    Double-buffered shared memory for preview frames.

    Uses two shared memory buffers to avoid blocking:
    - Worker writes to buffer A while main reads buffer B
    - Simple sequence counter determines which buffer is current
    - No locks needed - atomic counter + memory barrier sufficient

    The worker attaches to existing shared memory created by the main process.
    """

    def __init__(
        self,
        name_a: str,
        name_b: str,
        width: int,
        height: int,
        *,
        create: bool = False,
    ) -> None:
        """
        Initialize shared memory buffer.

        Args:
            name_a: Name of first shared memory buffer
            name_b: Name of second shared memory buffer
            width: Frame width in pixels
            height: Frame height in pixels
            create: If True, create new shared memory; if False, attach to existing
        """
        self._width = width
        self._height = height
        self._shape = (height, width, 3)  # BGR format
        self._buffer_size = height * width * 3

        if create:
            self._shm_a = SharedMemory(name=name_a, create=True, size=self._buffer_size)
            self._shm_b = SharedMemory(name=name_b, create=True, size=self._buffer_size)
            logger.info(
                "Created shared memory buffers: %s, %s (%d bytes each)",
                name_a, name_b, self._buffer_size
            )
        else:
            self._shm_a = SharedMemory(name=name_a)
            self._shm_b = SharedMemory(name=name_b)
            logger.info("Attached to shared memory buffers: %s, %s", name_a, name_b)

        self._name_a = name_a
        self._name_b = name_b
        self._current = 0  # Current buffer index (0 or 1)
        self._sequence = 0  # Monotonic frame counter
        self._is_creator = create

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @property
    def shape(self) -> Tuple[int, int, int]:
        return self._shape

    @property
    def name_a(self) -> str:
        return self._name_a

    @property
    def name_b(self) -> str:
        return self._name_b

    def write_frame(self, frame: np.ndarray) -> Tuple[int, int]:
        """
        Write frame to next buffer.

        Args:
            frame: BGR numpy array with shape (height, width, 3)

        Returns:
            Tuple of (buffer_id, sequence) for the written frame

        Raises:
            ValueError: If frame shape doesn't match expected shape
        """
        if frame.shape != self._shape:
            raise ValueError(
                f"Frame shape {frame.shape} doesn't match expected {self._shape}"
            )

        # Toggle to next buffer
        self._current = 1 - self._current
        self._sequence += 1

        # Get the target buffer
        shm = self._shm_a if self._current == 0 else self._shm_b

        # Create numpy view of shared memory and copy frame data
        buf = np.ndarray(self._shape, dtype=np.uint8, buffer=shm.buf)
        np.copyto(buf, frame)

        return self._current, self._sequence

    def read_frame(self, buffer_id: int) -> np.ndarray:
        """
        Read frame from specified buffer.

        Args:
            buffer_id: Buffer index (0 or 1)

        Returns:
            BGR numpy array view into shared memory

        Note:
            Returns a VIEW into shared memory, not a copy.
            The caller should copy if they need to retain the data.
        """
        shm = self._shm_a if buffer_id == 0 else self._shm_b
        return np.ndarray(self._shape, dtype=np.uint8, buffer=shm.buf)

    def read_frame_copy(self, buffer_id: int) -> np.ndarray:
        """
        Read frame from specified buffer, returning a copy.

        Args:
            buffer_id: Buffer index (0 or 1)

        Returns:
            BGR numpy array (copied from shared memory)
        """
        return self.read_frame(buffer_id).copy()

    def close(self) -> None:
        """Close shared memory handles (does not unlink)."""
        try:
            self._shm_a.close()
        except Exception as e:
            logger.debug("Error closing shm_a: %s", e)
        try:
            self._shm_b.close()
        except Exception as e:
            logger.debug("Error closing shm_b: %s", e)

    def unlink(self) -> None:
        """
        Unlink (delete) shared memory.

        Should only be called by the process that created the shared memory.
        """
        if not self._is_creator:
            logger.warning("unlink() called but this instance did not create the buffers")
            return

        try:
            self._shm_a.unlink()
            logger.debug("Unlinked shared memory: %s", self._name_a)
        except Exception as e:
            logger.debug("Error unlinking shm_a: %s", e)
        try:
            self._shm_b.unlink()
            logger.debug("Unlinked shared memory: %s", self._name_b)
        except Exception as e:
            logger.debug("Error unlinking shm_b: %s", e)

    def close_and_unlink(self) -> None:
        """Close handles and unlink shared memory."""
        self.close()
        self.unlink()


def generate_shm_names(camera_key: str) -> Tuple[str, str]:
    """
    Generate unique shared memory names for a camera.

    Args:
        camera_key: Unique camera identifier (e.g., "picam:0" or "usb:/dev/video0")

    Returns:
        Tuple of (name_a, name_b) for the two buffers
    """
    # Sanitize key for use in shared memory name
    # SharedMemory names have platform-specific restrictions
    safe_key = camera_key.replace(":", "_").replace("/", "_").replace("\\", "_")
    return (f"cam_prev_{safe_key}_a", f"cam_prev_{safe_key}_b")


__all__ = ["PreviewSharedBuffer", "generate_shm_names"]
