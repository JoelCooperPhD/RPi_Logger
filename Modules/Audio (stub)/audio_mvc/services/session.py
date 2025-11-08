"""Session directory helpers for the audio stub."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Optional


class SessionService:
    """Manage creation of experiment session directories."""

    def __init__(self, base_output_dir: Path, session_prefix: str) -> None:
        self.base_output_dir = base_output_dir
        self.session_prefix = session_prefix

    async def ensure_session_dir(self, current: Optional[Path]) -> Path:
        if current is None:
            await asyncio.to_thread(self.base_output_dir.mkdir, parents=True, exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            current = self.base_output_dir / f"{self.session_prefix}_{timestamp}"
            await asyncio.to_thread(current.mkdir, parents=True, exist_ok=True)
            return current

        exists = await asyncio.to_thread(current.exists)
        if not exists:
            await asyncio.to_thread(current.mkdir, parents=True, exist_ok=True)
        return current
