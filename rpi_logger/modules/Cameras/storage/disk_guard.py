"""Disk space guard to prevent recording on low free space."""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger


@dataclass(slots=True)
class DiskStatus:
    ok: bool
    free_gb: float
    threshold_gb: float


class DiskGuard:
    """Periodic free-space checker."""

    def __init__(
        self,
        *,
        threshold_gb: float = 1.0,
        check_interval_ms: int = 5_000,
        logger: LoggerLike = None,
    ) -> None:
        self._threshold = max(0.0, threshold_gb)
        self._interval = max(1, check_interval_ms) / 1000.0
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._last_status: Optional[DiskStatus] = None

    async def ensure_ok(self, path: Path) -> DiskStatus:
        status = await asyncio.to_thread(self._check, path)
        self._update_and_warn(status)
        return status

    async def start_monitoring(self, path: Path) -> None:
        if self._task:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop(path), name="DiskGuard")

    async def stop(self) -> None:
        if not self._task:
            return
        self._stop_event.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    def last_status(self) -> Optional[DiskStatus]:
        return self._last_status

    def check(self, path: Path) -> bool:
        """Synchronous check if disk space is sufficient."""
        status = self._check(path)
        self._update_and_warn(status)
        return status.ok

    async def _loop(self, path: Path) -> None:
        try:
            while not self._stop_event.is_set():
                self._last_status = await asyncio.to_thread(self._check, path)
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            return

    def _check(self, path: Path) -> DiskStatus:
        try:
            usage = shutil.disk_usage(path)
            free_gb = usage.free / (1024**3)
        except Exception:
            free_gb = 0.0
        ok = free_gb >= self._threshold
        return DiskStatus(ok=ok, free_gb=free_gb, threshold_gb=self._threshold)

    def _update_and_warn(self, status: DiskStatus) -> None:
        """Update last status and warn if insufficient space."""
        self._last_status = status
        if not status.ok:
            self._logger.warning(
                "Disk guard blocking recording: free=%.2f GB threshold=%.2f GB",
                status.free_gb,
                status.threshold_gb,
            )


__all__ = ["DiskGuard", "DiskStatus"]
