"""Disk space guard for Cameras2 recordings."""

from __future__ import annotations

import asyncio
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Optional

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger


class DiskHealth:
    OK = "ok"
    BLOCKED = "blocked"
    RECOVERING = "recovering"


@dataclass(slots=True)
class DiskStatus:
    state: str
    free_bytes: int
    total_bytes: int
    required_bytes: int
    threshold_bytes: int
    checked_at: float
    reason: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.state == DiskHealth.OK


class DiskGuard:
    """Periodically checks free disk space and signals when below threshold."""

    def __init__(
        self,
        *,
        threshold_gb: float,
        check_interval_ms: int = 5000,
        logger: LoggerLike = None,
    ) -> None:
        self._threshold_bytes = int(threshold_gb * 1_000_000_000)
        self._interval = max(0.5, check_interval_ms / 1000.0)
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)

    async def check_before_start(self, path: Path, required_bytes: int = 0) -> DiskStatus:
        """Single preflight check before recording begins."""

        status = await self._check(path, required_bytes)
        if not status.ok:
            self._logger.warning(
                "Disk guard blocked start: free=%0.2fGB required=%0.2fGB threshold=%0.2fGB (%s)",
                status.free_bytes / 1e9,
                required_bytes / 1e9,
                self._threshold_bytes / 1e9,
                status.reason or status.state,
            )
        return status

    async def monitor(
        self,
        path: Path,
        *,
        stop_event: asyncio.Event,
        required_bytes: int = 0,
    ) -> AsyncIterator[DiskStatus]:
        """Yield disk status periodically until stop_event is set."""

        previous_ok = True
        while not stop_event.is_set():
            status = await self._check(path, required_bytes)
            if status.ok:
                if not previous_ok:
                    status.state = DiskHealth.RECOVERING
            yield status
            previous_ok = status.ok
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    # ------------------------------------------------------------------
    # Internal helpers

    async def _check(self, path: Path, required_bytes: int) -> DiskStatus:
        try:
            usage = await asyncio.to_thread(shutil.disk_usage, path)
            free_bytes = int(usage.free)
            total_bytes = int(usage.total)
        except Exception as exc:
            # On failure, assume blocked to be safe.
            now = time.time()
            self._logger.warning("Disk guard failed to read usage for %s: %s", path, exc)
            return DiskStatus(
                state=DiskHealth.BLOCKED,
                free_bytes=0,
                total_bytes=0,
                required_bytes=required_bytes,
                threshold_bytes=self._threshold_bytes,
                checked_at=now,
                reason=str(exc),
            )

        now = time.time()
        needed = max(required_bytes, self._threshold_bytes)
        ok = free_bytes >= needed
        state = DiskHealth.OK if ok else DiskHealth.BLOCKED
        return DiskStatus(
            state=state,
            free_bytes=free_bytes,
            total_bytes=total_bytes,
            required_bytes=required_bytes,
            threshold_bytes=self._threshold_bytes,
            checked_at=now,
            reason=None if ok else "low_disk_space",
        )


__all__ = ["DiskGuard", "DiskStatus", "DiskHealth"]
