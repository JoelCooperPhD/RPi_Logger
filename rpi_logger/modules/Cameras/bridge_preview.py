"""Preview coordination controller for Cameras runtime."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Tuple

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.Cameras.config import DEFAULT_PREVIEW_SIZE, DEFAULT_PREVIEW_FPS
from rpi_logger.modules.Cameras.utils import parse_resolution, parse_fps
from rpi_logger.modules.Cameras.worker.protocol import RespPreviewFrame

if TYPE_CHECKING:
    from rpi_logger.modules.Cameras.runtime.coordinator import WorkerManager, PreviewReceiver
    from rpi_logger.modules.Cameras.storage import KnownCamerasCache


class PreviewController:
    """
    Coordinates preview streaming across camera workers.

    Responsibilities:
    - Starting and stopping preview for cameras
    - Managing preview receiver and frame consumers
    - Getting preview settings from cache
    - Routing preview frames to the view
    """

    def __init__(
        self,
        *,
        preview_receiver: "PreviewReceiver",
        worker_manager: "WorkerManager",
        cache: "KnownCamerasCache",
        frame_pusher: Callable[[str, Any], None],
        logger: LoggerLike = None,
    ) -> None:
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._preview_receiver = preview_receiver
        self._worker_manager = worker_manager
        self._cache = cache
        self._frame_pusher = frame_pusher
        self._frame_counts: Dict[str, int] = {}

    def on_preview_frame(self, key: str, msg: RespPreviewFrame) -> None:
        """Handle a preview frame from a worker - route to receiver."""
        self._frame_counts[key] = self._frame_counts.get(key, 0) + 1
        count = self._frame_counts[key]
        if count == 1 or count % 30 == 0:
            self._logger.debug(
                "[PREVIEW] %s: frame #%d, %dx%d, %d bytes",
                key, count, msg.width, msg.height, len(msg.frame_data)
            )
        self._preview_receiver.on_preview_frame(key, msg)

    async def start_preview(self, key: str) -> None:
        """Start preview streaming for a camera."""
        self._logger.info("[PREVIEW START] Setting up preview for %s...", key)

        # Track frames pushed to view for debugging
        frame_count = [0]

        def consumer(frame):
            frame_count[0] += 1
            if frame_count[0] == 1 or frame_count[0] % 30 == 0:
                self._logger.debug(
                    "[PREVIEW PUSH] %s: pushing frame #%d to view, shape=%s",
                    key, frame_count[0], frame.shape if hasattr(frame, 'shape') else 'unknown'
                )
            self._frame_pusher(key, frame)

        self._preview_receiver.set_consumer(key, consumer)
        self._logger.debug("[PREVIEW START] Consumer registered for %s", key)

        # Get per-camera settings (or defaults)
        preview_size, target_fps = await self.get_preview_settings(key)

        self._logger.info(
            "[PREVIEW START] Sending start_preview command to worker %s (size=%s, fps=%.1f)",
            key, preview_size, target_fps
        )
        await self._worker_manager.start_preview(
            key,
            preview_size=preview_size,
            target_fps=target_fps,
            jpeg_quality=80,
        )

        # Wire up shared memory to preview receiver (if allocated)
        handle = self._worker_manager.get_worker(key)
        if handle and handle.preview_shm is not None:
            self._preview_receiver.set_shared_memory(key, handle.preview_shm)
            self._logger.info("[PREVIEW START] Shared memory wired to receiver for %s", key)

        self._logger.info("[PREVIEW START] Preview started for %s", key)

    async def stop_preview(self, key: str) -> None:
        """Stop preview streaming for a camera."""
        self._logger.info("[PREVIEW STOP] Stopping preview for %s", key)
        await self._worker_manager.stop_preview(key)
        self._preview_receiver.remove_consumer(key)

    async def restart_preview(self, key: str) -> None:
        """Restart preview with updated settings."""
        handle = self._worker_manager.get_worker(key)
        if handle and handle.is_previewing:
            self._logger.info("[PREVIEW] Restarting preview for %s with new settings", key)
            await self._worker_manager.stop_preview(key)
            await self.start_preview(key)

    async def get_preview_settings(self, key: str) -> Tuple[Tuple[int, int], float]:
        """Get preview size and fps for a camera from saved settings or defaults."""
        saved = await self._cache.get_settings(key)

        preview_size = parse_resolution(
            saved.get("preview_resolution") if saved else None,
            DEFAULT_PREVIEW_SIZE
        )
        target_fps = parse_fps(
            saved.get("preview_fps") if saved else None,
            DEFAULT_PREVIEW_FPS
        )

        return preview_size, target_fps

    def clear_camera(self, key: str) -> None:
        """Clean up preview state for a removed camera."""
        self._frame_counts.pop(key, None)
        self._preview_receiver.remove_consumer(key)


__all__ = ["PreviewController"]
