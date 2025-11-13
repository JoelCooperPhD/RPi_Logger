"""Startup + persistence helpers for the audio module."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, Optional, TYPE_CHECKING

from ..domain import AudioSnapshot, AudioState
from .persistence import PersistedSelection, serialize_selected_devices

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
        serialized = serialize_selected_devices(snapshot.selected_devices)
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


# Lazy import to avoid circular dependency at runtime
if TYPE_CHECKING:  # pragma: no cover
    from .device_manager import DeviceManager
