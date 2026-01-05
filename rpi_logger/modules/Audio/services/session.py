"""Session directory management."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path


class SessionService:
    """Manage session directories."""
    def __init__(self, base_output_dir: Path, session_prefix: str, logger: logging.Logger) -> None:
        self.base_output_dir = base_output_dir
        self.session_prefix = session_prefix
        self._cached_current: Path | None = None
        self.logger = logger.getChild("SessionService")

    async def ensure_session_dir(self, current: Path | None) -> Path:
        target = current or self._cached_current

        if target is None:
            await asyncio.to_thread(self.base_output_dir.mkdir, parents=True, exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            target = self.base_output_dir / f"{self.session_prefix}_{timestamp}"
            await asyncio.to_thread(target.mkdir, parents=True, exist_ok=True)
            self._cached_current = target
            self.logger.info("Created session directory %s", target)
            return target

        exists = await asyncio.to_thread(target.exists)
        if not exists:
            await asyncio.to_thread(target.mkdir, parents=True, exist_ok=True)
            self.logger.info("Recreated missing session directory %s", target)
        else:
            self.logger.debug("Using existing session directory %s", target)
        self._cached_current = target
        return target
