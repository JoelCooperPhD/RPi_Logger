"""Startup + persistence helpers for the audio module."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, Iterable, Optional, Sequence, TYPE_CHECKING

from ..domain import AudioSnapshot, AudioState
from .persistence import PersistedDevice, PersistedSelection

TaskSubmitter = Callable[[Awaitable[Any], str], asyncio.Task]


class AudioStartupManager:
    """Coordinates restoring and persisting audio device selections."""

    def __init__(
        self,
        context: Any,
        state: AudioState,
        task_submitter: Optional[TaskSubmitter],
        logger: logging.Logger,
    ) -> None:
        self._state = state
        self._task_submitter = task_submitter or self._fallback_submitter
        self._logger = logger.getChild("Startup")
        self._model = getattr(context, "model", None)
        snapshot = self._read_config_snapshot()
        raw_value = snapshot.get("selected_devices") if isinstance(snapshot, Dict) else None
        self._persisted_selection = PersistedSelection.from_raw(raw_value)
        self._selection_entries: list[PersistedDevice] = list(self._persisted_selection.entries)
        self._last_serialized = self._persisted_selection.serialized
        self._pending_payload: str | None = None
        self._persist_task: asyncio.Task | None = None
        self._bound = False
        self._restoration_complete = False

    def bind(self) -> None:
        if self._bound:
            return
        self._state.subscribe(self._handle_snapshot)
        self._bound = True

    async def restore_previous_selection(self, device_manager: "DeviceManager") -> int:
        try:
            if not self._persisted_selection.has_entries:
                return 0

            restored = 0
            claimed: set[int] = set()
            available = device_manager.state.devices

            for device_id in self._persisted_selection.device_ids:
                if device_id not in available or device_id in claimed:
                    continue
                await device_manager.toggle_device(device_id, True)
                if device_id in self._state.selected_devices:
                    restored += 1
                    claimed.add(device_id)

            if restored < len(self._persisted_selection.entries):
                lowercase_map = {
                    device_id: (info.name or "").strip().lower()
                    for device_id, info in available.items()
                }
                for name in self._persisted_selection.device_names:
                    normalized = name.strip().lower()
                    if not normalized:
                        continue
                    match_id = next(
                        (
                            device_id
                            for device_id, value in lowercase_map.items()
                            if value == normalized and device_id not in claimed
                        ),
                        None,
                    )
                    if match_id is None:
                        continue
                    await device_manager.toggle_device(match_id, True)
                    if match_id in self._state.selected_devices:
                        restored += 1
                        claimed.add(match_id)

            if restored:
                self._logger.info("Restored %d audio device(s) from config", restored)
            return restored
        finally:
            self._restoration_complete = True

    async def restore_new_devices(self, device_manager: "DeviceManager", device_ids: Iterable[int]) -> int:
        pending = self._pending_selection_entries()
        if not pending:
            return 0
        available = device_manager.state.devices
        if not available:
            return 0

        index_by_id, index_by_name = self._build_entry_indexes(pending)
        claimed: set[int] = set()
        restored = 0

        for device_id in device_ids:
            info = available.get(device_id)
            if not info or device_id in self._state.selected_devices:
                continue
            match_idx = self._claim_matching_index(index_by_id.get(device_id, []), claimed)
            if match_idx is None:
                normalized = self._normalize_name(info.name)
                if normalized:
                    match_idx = self._claim_matching_index(index_by_name.get(normalized, []), claimed)
            if match_idx is None:
                continue
            await device_manager.toggle_device(device_id, True)
            if device_id in self._state.selected_devices:
                restored += 1

        if restored:
            self._logger.info("Restored %d previously selected device(s)", restored)
        return restored

    async def flush(self) -> None:
        if self._pending_payload and not self._persist_task:
            await self._drain_pending_payloads()
        task = self._persist_task
        if not task:
            return
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------
    # Internal helpers

    def _handle_snapshot(self, snapshot: AudioSnapshot) -> None:
        selection = self._merge_snapshot_selection(snapshot)
        serialized = selection.serialized
        if serialized == self._last_serialized:
            return
        self._selection_entries = list(selection.entries)
        self._persisted_selection = selection
        self._last_serialized = serialized
        self._pending_payload = serialized
        if self._persist_task and not self._persist_task.done():
            return
        self._persist_task = self._task_submitter(
            self._drain_pending_payloads(),
            "persist_audio_selection",
        )

    async def _drain_pending_payloads(self) -> None:
        try:
            while self._pending_payload:
                payload = self._pending_payload
                self._pending_payload = None
                await self._persist_payload(payload)
        finally:
            self._persist_task = None

    async def _persist_payload(self, payload: str) -> None:
        if not payload:
            payload = "[]"
        model = self._model
        persist = getattr(model, "persist_preferences", None)
        if not callable(persist):
            return
        try:
            success = await persist({"selected_devices": payload})
            if not success:
                self._logger.warning("Failed to persist selected audio devices to config")
        except Exception:
            self._logger.warning("Error while persisting selected audio devices", exc_info=True)

    # ------------------------------------------------------------------
    # Selection bookkeeping helpers

    def _merge_snapshot_selection(self, snapshot: AudioSnapshot) -> PersistedSelection:
        snapshot_entries = self._entries_from_snapshot(snapshot)
        return self._merge_selection_entries(snapshot_entries, snapshot)

    def _entries_from_snapshot(self, snapshot: AudioSnapshot) -> tuple[PersistedDevice, ...]:
        entries = [
            PersistedDevice(device_id=device_id, name=info.name)
            for device_id, info in sorted(snapshot.selected_devices.items(), key=lambda item: item[0])
        ]
        return tuple(entries)

    def _merge_selection_entries(
        self,
        snapshot_entries: tuple[PersistedDevice, ...],
        snapshot: AudioSnapshot,
    ) -> PersistedSelection:
        base_entries: list[PersistedDevice]
        if self._selection_entries:
            base_entries = list(self._selection_entries)
        else:
            base_entries = list(self._persisted_selection.entries)

        available_ids = set(snapshot.devices.keys())
        available_names = self._build_available_name_set(snapshot)
        index_by_id, index_by_name = self._build_entry_indexes(snapshot_entries)
        consumed: set[int] = set()
        merged: list[PersistedDevice] = []

        for entry in base_entries:
            match_idx = self._match_entry(entry, index_by_id, index_by_name, consumed)
            if match_idx is not None:
                consumed.add(match_idx)
                merged.append(snapshot_entries[match_idx])
                continue
            should_remove = self._restoration_complete and self._entry_available(
                entry,
                available_ids,
                available_names,
            )
            if should_remove:
                continue
            merged.append(entry)

        for idx, entry in enumerate(snapshot_entries):
            if idx in consumed:
                continue
            merged.append(entry)

        return PersistedSelection.from_entries(merged)

    def _pending_selection_entries(self) -> tuple[PersistedDevice, ...]:
        source = self._selection_entries or list(self._persisted_selection.entries)
        if not source:
            return ()
        active_ids = set(self._state.selected_devices.keys())
        active_names = {
            normalized
            for normalized in (
                self._normalize_name(info.name)
                for info in self._state.selected_devices.values()
            )
            if normalized
        }
        pending: list[PersistedDevice] = []
        for entry in source:
            if entry.device_id is not None and entry.device_id in active_ids:
                continue
            normalized = self._normalize_name(entry.name)
            if normalized and normalized in active_names:
                continue
            pending.append(entry)
        return tuple(pending)

    def _build_entry_indexes(
        self,
        entries: Sequence[PersistedDevice],
    ) -> tuple[Dict[int, list[int]], Dict[str, list[int]]]:
        index_by_id: Dict[int, list[int]] = {}
        index_by_name: Dict[str, list[int]] = {}
        for idx, entry in enumerate(entries):
            if entry.device_id is not None:
                index_by_id.setdefault(entry.device_id, []).append(idx)
            normalized = self._normalize_name(entry.name)
            if normalized:
                index_by_name.setdefault(normalized, []).append(idx)
        return index_by_id, index_by_name

    def _match_entry(
        self,
        entry: PersistedDevice,
        index_by_id: Dict[int, list[int]],
        index_by_name: Dict[str, list[int]],
        consumed: set[int],
    ) -> int | None:
        if entry.device_id is not None:
            for idx in index_by_id.get(entry.device_id, []):
                if idx not in consumed:
                    return idx
        normalized = self._normalize_name(entry.name)
        if normalized:
            for idx in index_by_name.get(normalized, []):
                if idx not in consumed:
                    return idx
        return None

    def _entry_available(
        self,
        entry: PersistedDevice,
        available_ids: set[int],
        available_names: set[str],
    ) -> bool:
        if entry.device_id is not None and entry.device_id in available_ids:
            return True
        normalized = self._normalize_name(entry.name)
        if normalized and normalized in available_names:
            return True
        return False

    def _build_available_name_set(self, snapshot: AudioSnapshot) -> set[str]:
        names: set[str] = set()
        for info in snapshot.devices.values():
            normalized = self._normalize_name(info.name)
            if normalized:
                names.add(normalized)
        return names

    def _claim_matching_index(self, indices: Sequence[int] | None, claimed: set[int]) -> int | None:
        if not indices:
            return None
        for idx in indices:
            if idx in claimed:
                continue
            claimed.add(idx)
            return idx
        return None

    @staticmethod
    def _normalize_name(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        stripped = value.strip().lower()
        return stripped or None

    def _read_config_snapshot(self) -> Dict[str, Any]:
        model = self._model
        if model is None:
            return {}
        getter = getattr(model, "get_config_snapshot", None)
        if callable(getter):
            try:
                snapshot = getter()
                return dict(snapshot)
            except Exception:
                self._logger.debug("Config snapshot unavailable", exc_info=True)
        config_data = getattr(model, "config_data", None)
        if isinstance(config_data, Dict):
            return dict(config_data)
        return {}

    def _fallback_submitter(self, coro: Awaitable[Any], name: str) -> asyncio.Task:
        return asyncio.create_task(coro, name=name)


# Lazy import to avoid circular dependency at runtime
if TYPE_CHECKING:  # pragma: no cover
    from .device_manager import DeviceManager
