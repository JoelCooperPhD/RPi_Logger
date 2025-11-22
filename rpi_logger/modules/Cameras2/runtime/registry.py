"""Registry state machine for Cameras2."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any, Dict, Iterable, Optional

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.Cameras2.runtime import CameraDescriptor, CameraId, CameraRuntimeState, RuntimeStatus, SelectedConfigs
from rpi_logger.modules.Cameras2.runtime.tasks import TaskManager
from rpi_logger.modules.Cameras2.storage import KnownCamerasCache


class Registry:
    """Track cameras, backends, and lifecycle transitions."""

    def __init__(
        self,
        *,
        cache: Optional[KnownCamerasCache] = None,
        logger: LoggerLike = None,
    ) -> None:
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._states: Dict[str, CameraRuntimeState] = {}
        self._backend_handles: Dict[str, Any] = {}
        self._task_manager = TaskManager(logger=self._logger)
        self._lock = asyncio.Lock()
        self._cache = cache

    # ------------------------------------------------------------------
    # Discovery and state updates

    async def apply_discovery(self, descriptors: Iterable[CameraDescriptor]) -> Dict[str, CameraRuntimeState]:
        """Merge discovered descriptors into registry state."""

        async with self._lock:
            current_keys = set(self._states.keys())
            seen_keys = set()
            for desc in descriptors:
                key = desc.camera_id.key
                seen_keys.add(key)
                if key in self._states:
                    # Update descriptor fields
                    self._states[key].descriptor = desc
                    continue
                cached_state = await self._load_cached_state(desc.camera_id)
                state = cached_state or CameraRuntimeState(descriptor=desc)
                if cached_state:
                    state.descriptor = desc
                self._states[key] = state
                self._logger.info("Camera discovered: %s", key)

            # Handle removals
            removed = current_keys - seen_keys
            for key in removed:
                await self._handle_unplug_locked(key)

            return dict(self._states)

    async def _load_cached_state(self, camera_id: CameraId) -> Optional[CameraRuntimeState]:
        if not self._cache:
            return None
        state = await self._cache.get(camera_id)
        if state:
            self._logger.debug("Loaded cached state for %s", camera_id.key)
        return state

    # ------------------------------------------------------------------
    # Backend attachment and status changes

    async def attach_backend(
        self,
        camera_id: CameraId,
        handle: Any,
        capabilities: Any,
        *,
        selected_configs: Optional[SelectedConfigs] = None,
    ) -> None:
        async with self._lock:
            state = self._states.get(camera_id.key)
            if not state:
                return
            state.capabilities = capabilities
            if selected_configs:
                state.selected_configs = selected_configs
            state.status = RuntimeStatus.SELECTED
            self._backend_handles[camera_id.key] = handle
            await self._persist_state(state)
            self._logger.info("Backend attached: %s", camera_id.key)

    async def update_selected_configs(self, camera_id: CameraId, selected: SelectedConfigs) -> None:
        async with self._lock:
            state = self._states.get(camera_id.key)
            if not state:
                return
            state.selected_configs = selected
            await self._persist_state(state)

    async def handle_unplug(self, camera_id: CameraId) -> None:
        async with self._lock:
            await self._handle_unplug_locked(camera_id.key)

    async def _handle_unplug_locked(self, key: str) -> None:
        if key in self._backend_handles:
            handle = self._backend_handles.pop(key)
            stop = getattr(handle, "stop", None)
            if stop:
                with contextlib.suppress(Exception):
                    await stop()

        await self._task_manager.cancel(f"preview:{key}")
        await self._task_manager.cancel(f"record:{key}")
        if key in self._states:
            self._logger.info("Camera removed: %s", key)
            self._states.pop(key, None)

    # ------------------------------------------------------------------
    # Snapshot and persistence

    def snapshot(self) -> Dict[str, CameraRuntimeState]:
        return dict(self._states)

    def get_state(self, camera_id: CameraId) -> Optional[CameraRuntimeState]:
        return self._states.get(camera_id.key)

    async def _persist_state(self, state: CameraRuntimeState) -> None:
        if not self._cache:
            return
        await self._cache.update(state)


__all__ = ["Registry"]
