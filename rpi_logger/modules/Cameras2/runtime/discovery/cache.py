"""Discovery cache integration with KnownCameras."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.Cameras2.runtime import CameraId, CameraRuntimeState
from rpi_logger.modules.Cameras2.storage import KnownCamerasCache


class DiscoveryCache:
    """Simple facade around KnownCamerasCache for discovery flows."""

    def __init__(self, cache_path: Path, *, logger: LoggerLike = None) -> None:
        self._cache = KnownCamerasCache(cache_path, logger=logger)
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)

    async def get(self, camera_id: CameraId) -> Optional[CameraRuntimeState]:
        state = await self._cache.get(camera_id)
        if state:
            self._logger.debug("Discovery cache hit for %s", camera_id.key)
        else:
            self._logger.debug("Discovery cache miss for %s", camera_id.key)
        return state

    async def update(self, state: CameraRuntimeState) -> None:
        await self._cache.update(state)

    async def save(self) -> None:
        await self._cache.save()


__all__ = ["DiscoveryCache"]
