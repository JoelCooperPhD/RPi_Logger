"""Startup + persistence helpers for the audio module."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Iterable, Optional, TYPE_CHECKING

from .state import AudioDeviceInfo, AudioSnapshot, AudioState

TaskSubmitter = Callable[[Awaitable[Any], str], asyncio.Task]


@dataclass(slots=True)
class PersistedDevice:
    """Representation of a device entry stored in config.txt."""

    device_id: int | None = None
    name: str | None = None

    def key(self) -> tuple[int | None, str]:
        return self.device_id, (self.name or "").strip().lower()


@dataclass(slots=True)
class PersistedSelection:
    """Parsed view of the stored device selection."""

    entries: tuple[PersistedDevice, ...]
    serialized: str

    @property
    def has_entries(self) -> bool:
        return bool(self.entries)

    @property
    def device_ids(self) -> tuple[int, ...]:
        return tuple(entry.device_id for entry in self.entries if entry.device_id is not None)

    @property
    def device_names(self) -> tuple[str, ...]:
        names: list[str] = []
        for entry in self.entries:
            if entry.name:
                cleaned = entry.name.strip()
                if cleaned:
                    names.append(cleaned)
        return tuple(names)

    @classmethod
    def from_raw(cls, raw: Any) -> "PersistedSelection":
        entries = _normalize_entries(_parse_raw_selection(raw))
        serialized = _serialize_entries(entries)
        return cls(entries=entries, serialized=serialized)


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
        self._last_serialized = self._persisted_selection.serialized
        self._pending_payload: str | None = None
        self._persist_task: asyncio.Task | None = None
        self._bound = False

    def bind(self) -> None:
        if self._bound:
            return
        self._state.subscribe(self._handle_snapshot)
        self._bound = True

    async def restore_previous_selection(self, device_manager: "DeviceManager") -> int:
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
        serialized = _serialize_selected_devices(snapshot.selected_devices)
        if serialized == self._last_serialized:
            return
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


# ---------------------------------------------------------------------------
# Serialization helpers


def _parse_raw_selection(raw: Any) -> list[PersistedDevice]:
    entries: list[PersistedDevice] = []
    if raw is None:
        return entries

    value = raw
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return entries
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError:
            for chunk in stripped.replace(";", ",").split(","):
                token = chunk.strip()
                if not token:
                    continue
                device_id = _coerce_int(token)
                if device_id is not None:
                    entries.append(PersistedDevice(device_id=device_id))
                else:
                    entries.append(PersistedDevice(name=token))
            return entries

    if isinstance(value, dict):
        value = [value]

    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                device_id = _coerce_int(item.get("id"))
                name = _clean_name(item.get("name"))
                if device_id is None and not name:
                    continue
                entries.append(PersistedDevice(device_id=device_id, name=name))
            elif isinstance(item, (int, float)):
                device_id = _coerce_int(item)
                if device_id is not None:
                    entries.append(PersistedDevice(device_id=device_id))
            elif isinstance(item, str):
                token = item.strip()
                if not token:
                    continue
                device_id = _coerce_int(token)
                if device_id is not None:
                    entries.append(PersistedDevice(device_id=device_id))
                else:
                    entries.append(PersistedDevice(name=token))
    else:
        device_id = _coerce_int(value)
        if device_id is not None:
            entries.append(PersistedDevice(device_id=device_id))
        else:
            name = _clean_name(value)
            if name:
                entries.append(PersistedDevice(name=name))

    return entries


def _normalize_entries(entries: Iterable[PersistedDevice]) -> tuple[PersistedDevice, ...]:
    unique: Dict[tuple[int | None, str], PersistedDevice] = {}
    for entry in entries:
        name = _clean_name(entry.name)
        key = (entry.device_id, name or "")
        if key in unique:
            continue
        unique[key] = PersistedDevice(device_id=entry.device_id, name=name)

    def sort_key(item: PersistedDevice) -> tuple[int, int, str]:
        has_id = item.device_id is not None
        id_value = item.device_id if item.device_id is not None else -1
        name_key = (item.name or "").lower()
        return (0 if has_id else 1, id_value, name_key)

    ordered = sorted(unique.values(), key=sort_key)
    return tuple(ordered)


def _serialize_entries(entries: Iterable[PersistedDevice]) -> str:
    payload: list[Dict[str, Any]] = []
    for entry in entries:
        record: Dict[str, Any] = {}
        if entry.device_id is not None:
            record["id"] = entry.device_id
        if entry.name:
            record["name"] = entry.name
        if record:
            payload.append(record)
    return json.dumps(payload, separators=(",", ":")) if payload else "[]"


def _serialize_selected_devices(devices: Dict[int, AudioDeviceInfo]) -> str:
    if not devices:
        return "[]"
    entries = [
        PersistedDevice(device_id=device_id, name=info.name)
        for device_id, info in sorted(devices.items(), key=lambda item: item[0])
    ]
    return _serialize_entries(entries)


def _coerce_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number


def _clean_name(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


# Lazy import to avoid circular dependency at runtime
if TYPE_CHECKING:  # pragma: no cover
    from .app import DeviceManager
