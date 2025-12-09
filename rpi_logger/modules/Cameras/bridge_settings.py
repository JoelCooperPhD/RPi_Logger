"""Settings coordination controller for Cameras runtime."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger

if TYPE_CHECKING:
    from rpi_logger.modules.Cameras.app.view import CamerasView
    from rpi_logger.modules.Cameras.bridge_preview import PreviewController
    from rpi_logger.modules.Cameras.config import CamerasConfig
    from rpi_logger.modules.Cameras.runtime.coordinator.manager import WorkerManager
    from rpi_logger.modules.Cameras.runtime.task_registry import TaskRegistry
    from rpi_logger.modules.Cameras.storage import KnownCamerasCache


class SettingsController:
    """
    Coordinates per-camera settings application.

    Responsibilities:
    - Persisting settings to cache
    - Applying settings changes (preview restart or worker respawn)
    - Loading and pushing settings to the view
    - Managing settings-related async tasks
    """

    def __init__(
        self,
        *,
        cache: "KnownCamerasCache",
        config: "CamerasConfig",
        view: "CamerasView",
        tasks: "TaskRegistry",
        preview: "PreviewController",
        respawn_worker: Callable[[str], Any],
        worker_manager: "WorkerManager",
        logger: LoggerLike = None,
    ) -> None:
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._cache = cache
        self._config = config
        self._view = view
        self._tasks = tasks
        self._preview = preview
        self._respawn_worker = respawn_worker
        self._worker_manager = worker_manager

    def handle_apply_config(self, camera_id: str, settings: Dict[str, Any]) -> None:
        """Handle configuration changes from UI - persist and apply settings."""
        self._logger.info("[CONFIG] Applying settings for %s: %s", camera_id, settings)
        # Cancel existing settings task if any, then apply new settings
        self._tasks.register_keyed("settings", camera_id, asyncio.create_task(
            self._cancel_and_apply_settings(camera_id, settings),
            name=f"settings_{camera_id}"
        ))

    async def _cancel_and_apply_settings(self, camera_id: str, settings: Dict[str, Any]) -> None:
        """Cancel existing settings task and apply new settings."""
        await self._tasks.cancel_keyed("settings", camera_id)
        await self.apply_settings(camera_id, settings)

    async def apply_settings(self, camera_id: str, settings: Dict[str, Any]) -> None:
        """Persist per-camera settings and restart preview/worker as needed."""
        try:
            # Get old settings to detect record setting changes
            old_settings = await self._cache.get_settings(camera_id) or {}

            # Save to cache
            await self._cache.set_settings(camera_id, settings)
            self._logger.debug("[CONFIG] Settings saved for %s", camera_id)

            # Check if record settings changed (requires worker respawn)
            record_settings_changed = (
                old_settings.get("record_resolution") != settings.get("record_resolution") or
                old_settings.get("record_fps") != settings.get("record_fps")
            )

            if record_settings_changed:
                self._logger.info("[CONFIG] Record settings changed for %s - respawning worker", camera_id)
                await self._respawn_worker(camera_id)
            else:
                # Only preview settings changed - just restart preview
                await self._preview.restart_preview(camera_id)
        except asyncio.CancelledError:
            raise  # Don't catch cancellation
        except (OSError, ValueError, KeyError) as e:
            self._logger.warning("[CONFIG] Failed to apply settings for %s: %s", camera_id, e)
        except Exception as e:
            self._logger.warning("[CONFIG] Unexpected error applying settings for %s: %s", camera_id, e, exc_info=True)

    def push_config_to_view(self, camera_id: str) -> None:
        """Push config values to settings window for a camera (loads from cache if available)."""
        # Schedule async load from cache - track task for graceful shutdown
        self._tasks.register_keyed("settings", camera_id, asyncio.create_task(
            self._cancel_and_load_settings(camera_id),
            name=f"load_settings_{camera_id}"
        ))

    async def _cancel_and_load_settings(self, camera_id: str) -> None:
        """Cancel existing settings task and load settings."""
        await self._tasks.cancel_keyed("settings", camera_id)
        await self.load_and_push_settings(camera_id)

    async def load_and_push_settings(self, camera_id: str) -> None:
        """Load per-camera settings from cache, falling back to global config."""
        # Try to load saved per-camera settings first
        saved_settings = await self._cache.get_settings(camera_id)

        if saved_settings:
            self._logger.debug("[CONFIG] Loaded saved settings for %s: %s", camera_id, saved_settings)
            settings = dict(saved_settings)
        else:
            # Fall back to global config defaults
            preview_cfg = self._config.preview
            record_cfg = self._config.record

            preview_res = preview_cfg.resolution
            record_res = record_cfg.resolution
            preview_fps = preview_cfg.fps_cap
            record_fps = record_cfg.fps_cap

            settings = {
                "preview_resolution": f"{preview_res[0]}x{preview_res[1]}" if preview_res else "",
                "preview_fps": str(int(preview_fps)) if preview_fps and float(preview_fps).is_integer() else str(preview_fps) if preview_fps else "5",
                "record_resolution": f"{record_res[0]}x{record_res[1]}" if record_res else "",
                "record_fps": str(int(record_fps)) if record_fps and float(record_fps).is_integer() else str(record_fps) if record_fps else "15",
                "overlay": "true" if record_cfg.overlay else "false",
            }
            self._logger.debug("[CONFIG] Using global config for %s: %s", camera_id, settings)

        self._view.update_camera_settings(camera_id, settings)

    def set_control(self, camera_id: str, control_name: str, value: Any) -> bool:
        """Send a control change to a camera worker. Returns True if sent."""
        # Find the worker key for this camera
        worker_key = self._find_worker_key(camera_id)
        if not worker_key:
            self._logger.warning("[CONFIG] No worker found for camera %s", camera_id)
            return False

        self._logger.debug("[CONFIG] Setting control %s = %s for %s", control_name, value, camera_id)
        return self._worker_manager.set_control(worker_key, control_name, value)

    def _find_worker_key(self, camera_id: str) -> Optional[str]:
        """Find the worker key for a camera ID."""
        # Worker keys are typically formatted as "backend:stable_id"
        # camera_id might be formatted similarly, or we need to search
        # Check if the worker_manager has a worker with this key or a matching camera_id
        for key in self._worker_manager._workers:
            handle = self._worker_manager._workers[key]
            if handle.camera_id == camera_id or key == camera_id:
                return key
        return None


__all__ = ["SettingsController"]
