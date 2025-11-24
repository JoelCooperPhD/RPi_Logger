"""Retention helpers for Cameras sessions."""

from __future__ import annotations

import asyncio
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Set

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger


@dataclass(slots=True)
class RetentionSummary:
    pruned: int
    pruned_paths: list[str]
    skipped_active: int
    errors: list[str]
    duration_ms: float


async def prune_sessions(
    base_path: Path,
    max_sessions: int,
    *,
    exclude_active: Optional[Iterable[Path]] = None,
    dry_run: bool = False,
    logger: LoggerLike = None,
) -> RetentionSummary:
    """Prune oldest session directories beyond max_sessions."""

    log = ensure_structured_logger(logger, fallback_name=__name__)
    start = time.perf_counter()
    pruned: list[str] = []
    errors: list[str] = []
    excluded: Set[Path] = {Path(p).resolve() for p in (exclude_active or [])}

    try:
        base = Path(base_path)
        if not base.exists():
            return RetentionSummary(0, [], 0, [], 0.0)
        entries = await asyncio.to_thread(_list_sessions, base)
    except Exception as exc:
        log.warning("Failed to list sessions in %s: %s", base_path, exc)
        return RetentionSummary(0, [], 0, [str(exc)], (time.perf_counter() - start) * 1000)

    # Sort newest -> oldest by mtime
    entries.sort(key=lambda item: item[1], reverse=True)
    to_prune = entries[max_sessions:] if max_sessions >= 0 else []

    skipped_active = 0
    for path, _ in to_prune:
        resolved = path.resolve()
        if resolved in excluded:
            skipped_active += 1
            continue
        if dry_run:
            pruned.append(str(path))
            continue
        try:
            await asyncio.to_thread(shutil.rmtree, path)
            pruned.append(str(path))
        except Exception as exc:  # pragma: no cover - defensive logging
            errors.append(f"{path}: {exc}")
            log.warning("Failed to prune %s: %s", path, exc)

    duration_ms = (time.perf_counter() - start) * 1000
    if pruned:
        log.info("Pruned %d session(s): %s", len(pruned), pruned)
    return RetentionSummary(len(pruned), pruned, skipped_active, errors, duration_ms)


# ---------------------------------------------------------------------------
# Internal helpers


def _list_sessions(base_path: Path) -> list[tuple[Path, float]]:
    items: list[tuple[Path, float]] = []
    for entry in base_path.iterdir():
        if not entry.is_dir():
            continue
        try:
            mtime = entry.stat().st_mtime
        except Exception:
            mtime = 0.0
        items.append((entry, mtime))
    return items


__all__ = ["RetentionSummary", "prune_sessions"]
