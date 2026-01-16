"""Shared preference helpers for module configs.

This module provides:
- ModulePreferences: wrapper around ConfigManager for per-module config files
- ScopedPreferences: namespaced view into preferences (e.g., "view.show_logger")
- StatePersistence: protocol for runtime state that should survive restarts
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Protocol, Set, runtime_checkable

from rpi_logger.core.config_manager import ConfigManager, get_config_manager
from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger(__name__)


# ---------------------------------------------------------------------------
# State Persistence Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class StatePersistence(Protocol):
    """Protocol for runtime state classes that support persistence.

    Implement this protocol to enable automatic state save/restore:

        class MyState(StatePersistence):
            def __init__(self):
                self.selected_ids: List[int] = []
                self.last_value: str = ""

            def get_persistable_state(self) -> Dict[str, Any]:
                return {
                    "selected_ids": ",".join(str(i) for i in self.selected_ids),
                    "last_value": self.last_value,
                }

            def restore_from_state(self, data: Dict[str, Any]) -> None:
                ids_str = data.get("selected_ids", "")
                self.selected_ids = [int(x) for x in ids_str.split(",") if x]
                self.last_value = data.get("last_value", "")

            @classmethod
            def state_prefix(cls) -> str:
                return "mystate"  # Keys stored as mystate.selected_ids, etc.
    """

    def get_persistable_state(self) -> Dict[str, Any]:
        """Return state that should be persisted across restarts.

        Returns:
            Dict of key-value pairs. Values should be primitives (str, int, float, bool)
            or simple comma-separated lists that can be stored in config files.
        """
        ...

    def restore_from_state(self, data: Dict[str, Any]) -> None:
        """Restore state from previously persisted data.

        Args:
            data: Dict loaded from config, may be empty or partial.
        """
        ...

    @classmethod
    def state_prefix(cls) -> str:
        """Return the config key prefix for this state class.

        Returns:
            Prefix string (e.g., "audio" -> keys stored as "audio.selected_ids")
        """
        ...


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

    @property
    def config_path(self) -> Path:
        """Return the config file path for external use."""
        return self._config_path

    def scope(self, prefix: str, *, separator: str = ".") -> "ScopedPreferences":
        """Return a scoped view that automatically prefixes keys."""

        return ScopedPreferences(self, prefix, separator=separator)

    # ------------------------------------------------------------------
    # State persistence helpers

    def save_state(self, state_obj: StatePersistence) -> bool:
        """Persist a StatePersistence object's state to config.

        Args:
            state_obj: Object implementing StatePersistence protocol.

        Returns:
            True if save succeeded.
        """
        prefix = state_obj.state_prefix()
        state_data = state_obj.get_persistable_state()
        if not state_data:
            return True

        # Prefix all keys
        prefixed = {f"{prefix}.{k}": v for k, v in state_data.items()}
        return self.write_sync(prefixed)

    async def save_state_async(self, state_obj: StatePersistence) -> bool:
        """Async version of save_state."""
        prefix = state_obj.state_prefix()
        state_data = state_obj.get_persistable_state()
        if not state_data:
            return True

        prefixed = {f"{prefix}.{k}": v for k, v in state_data.items()}
        return await self.write_async(prefixed)

    def restore_state(self, state_obj: StatePersistence) -> None:
        """Restore a StatePersistence object's state from config.

        Args:
            state_obj: Object implementing StatePersistence protocol.
        """
        prefix = state_obj.state_prefix()
        scoped = self.scope(prefix)
        state_data = scoped.snapshot()
        if state_data:
            state_obj.restore_from_state(state_data)

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
            except Exception:  # pragma: no cover - defensive
                pass

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
    "StatePersistence",
]
