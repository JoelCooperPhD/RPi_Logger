"""Helpers for persisting/restoring audio device selections."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

from ..domain import AudioDeviceInfo


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


# ---------------------------------------------------------------------------
# Serialization helpers


def serialize_selected_devices(devices: Dict[int, AudioDeviceInfo]) -> str:
    if not devices:
        return "[]"
    entries = [
        PersistedDevice(device_id=device_id, name=info.name)
        for device_id, info in sorted(devices.items(), key=lambda item: item[0])
    ]
    return _serialize_entries(entries)


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


__all__ = [
    "PersistedDevice",
    "PersistedSelection",
    "serialize_selected_devices",
]
