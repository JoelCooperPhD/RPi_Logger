"""Shared preference helpers for module configs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional, Set

from rpi_logger.core.config_manager import ConfigManager, get_config_manager
from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger(__name__)


@dataclass(slots=True)
class PreferenceChange:
    """Describes which keys were updated or removed in a preference write."""

    updated: Dict[str, Any]
    removed: Set[str]


class ModulePreferences:
    """Lightweight wrapper around ConfigManager for module-specific configs."""

    def __init__(
        self,
        config_path: Path,
        *,
        config_manager: Optional[ConfigManager] = None,
        on_change: Optional[Callable[[PreferenceChange], None]] = None,
        initial_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._config_path = Path(config_path)
        self._manager = config_manager or get_config_manager()
        self._on_change = on_change
        self._cache: Dict[str, Any] = {}
        if initial_data:
            self._cache = dict(initial_data)
        else:
            self.reload()

    # ------------------------------------------------------------------
    # Basic accessors

    def snapshot(self) -> Dict[str, Any]:
        return dict(self._cache)

    def get(self, key: str, default: Optional[Any] = None) -> Any:
        return self._cache.get(key, default)

    def get_bool(self, key: str, default: bool = False) -> bool:
        if key not in self._cache:
            return default
        return str(self._cache[key]).strip().lower() in {"true", "1", "yes", "on"}

    def reload(self) -> Dict[str, Any]:
        try:
            self._cache = self._manager.read_config(self._config_path)
        except Exception:
            self._cache = {}
        return self.snapshot()

    def scope(self, prefix: str, *, separator: str = ".") -> "ScopedPreferences":
        """Return a scoped view that automatically prefixes keys."""

        return ScopedPreferences(self, prefix, separator=separator)

    # ------------------------------------------------------------------
    # Mutation helpers

    def write_sync(
        self,
        updates: Dict[str, Any],
        *,
        remove_keys: Optional[Iterable[str]] = None,
    ) -> bool:
        if not updates and not remove_keys:
            return True

        success = True
        if updates:
            success = self._manager.write_config(self._config_path, updates)
        if success and remove_keys:
            self._strip_keys_from_file(set(remove_keys))

        if success and (updates or remove_keys):
            self._apply_cache_updates(updates, remove_keys)
        return success

    async def write_async(
        self,
        updates: Dict[str, Any],
        *,
        remove_keys: Optional[Iterable[str]] = None,
    ) -> bool:
        if not updates and not remove_keys:
            return True

        success = True
        if updates:
            success = await self._manager.write_config_async(self._config_path, updates)
        if success and remove_keys:
            await asyncio.to_thread(self._strip_keys_from_file, set(remove_keys))

        if success and (updates or remove_keys):
            self._apply_cache_updates(updates, remove_keys)
        return success

    # ------------------------------------------------------------------
    # Internal helpers

    def _apply_cache_updates(
        self,
        updates: Dict[str, Any],
        remove_keys: Optional[Iterable[str]],
    ) -> None:
        if updates:
            for key, value in updates.items():
                self._cache[key] = self._stringify_value(value)
        removed_set: Set[str] = set(remove_keys or ())
        for key in removed_set:
            self._cache.pop(key, None)

        if self._on_change:
            change = PreferenceChange(updated=dict(updates), removed=removed_set)
            try:
                self._on_change(change)
            except Exception:  # pragma: no cover - defensive logging
                logger.debug("Preference change callback failed", exc_info=True)

    def _strip_keys_from_file(self, keys: Set[str]) -> None:
        if not keys:
            return
        try:
            if not self._config_path.exists():
                return
            lines = self._config_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return
        filtered: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith('#') or '=' not in stripped:
                filtered.append(line)
                continue
            key = stripped.split('=', 1)[0].strip()
            if key in keys:
                continue
            filtered.append(line)
        try:
            self._config_path.write_text("\n".join(filtered) + "\n", encoding="utf-8")
        except Exception:
            return

    @staticmethod
    def _stringify_value(value: Any) -> str:
        if isinstance(value, bool):
            return str(value).lower()
        return str(value)


class ScopedPreferences:
    """Wrapper around ModulePreferences that automatically prefixes keys."""

    def __init__(self, base: ModulePreferences, prefix: str, *, separator: str = ".") -> None:
        self._base = base
        cleaned_prefix = prefix.strip()
        self._prefix = cleaned_prefix.rstrip(separator)
        self._separator = separator

    def _qualify(self, key: str) -> str:
        if not self._prefix:
            return key
        if not key:
            return self._prefix
        return f"{self._prefix}{self._separator}{key}"

    def snapshot(self) -> Dict[str, Any]:
        base_snapshot = self._base.snapshot()
        if not self._prefix:
            return base_snapshot
        prefix = f"{self._prefix}{self._separator}"
        scoped: Dict[str, Any] = {}
        for key, value in base_snapshot.items():
            if key.startswith(prefix):
                scoped[key[len(prefix):]] = value
        return scoped

    def get(self, key: str, default: Optional[Any] = None) -> Any:
        return self._base.get(self._qualify(key), default)

    def get_bool(self, key: str, default: bool = False) -> bool:
        return self._base.get_bool(self._qualify(key), default)

    def write_sync(
        self,
        updates: Dict[str, Any],
        *,
        remove_keys: Optional[Iterable[str]] = None,
    ) -> bool:
        qualified_updates = {self._qualify(k): v for k, v in updates.items()}
        qualified_removals = [self._qualify(k) for k in remove_keys or ()]
        return self._base.write_sync(qualified_updates, remove_keys=qualified_removals)

    async def write_async(
        self,
        updates: Dict[str, Any],
        *,
        remove_keys: Optional[Iterable[str]] = None,
    ) -> bool:
        qualified_updates = {self._qualify(k): v for k, v in updates.items()}
        qualified_removals = [self._qualify(k) for k in remove_keys or ()]
        return await self._base.write_async(qualified_updates, remove_keys=qualified_removals)

    def scope(self, prefix: str, *, separator: str = ".") -> "ScopedPreferences":
        combined = self._qualify(prefix)
        return self._base.scope(combined, separator=separator)


__all__ = [
    "ModulePreferences",
    "PreferenceChange",
    "ScopedPreferences",
]
