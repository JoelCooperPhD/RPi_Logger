"""Shared camera storage utilities.

Provides disk space monitoring and camera settings cache persistence
for both USB and CSI camera modules.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, TYPE_CHECKING

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger

if TYPE_CHECKING:
    from rpi_logger.modules.base.camera_validator import CapabilityValidator
from rpi_logger.modules.base.camera_types import (
    CameraId,
    CameraRuntimeState,
    deserialize_camera_state,
    serialize_camera_state,
)


# ---------------------------------------------------------------------------
# Disk Space Guard


@dataclass(slots=True)
class DiskStatus:
    ok: bool
    free_gb: float
    threshold_gb: float


class DiskGuard:
    """Periodic free-space checker."""

    def __init__(
        self,
        *,
        threshold_gb: float = 1.0,
        check_interval_ms: int = 5_000,
        logger: LoggerLike = None,
    ) -> None:
        self._threshold = max(0.0, threshold_gb)
        self._interval = max(1, check_interval_ms) / 1000.0
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._last_status: Optional[DiskStatus] = None

    async def ensure_ok(self, path: Path) -> DiskStatus:
        status = await asyncio.to_thread(self._check, path)
        self._last_status = status
        if not status.ok:
            self._logger.warning(
                "Disk guard blocking recording: free=%.2f GB threshold=%.2f GB",
                status.free_gb,
                status.threshold_gb,
            )
        return status

    async def start_monitoring(self, path: Path) -> None:
        if self._task:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop(path), name="DiskGuard")

    async def stop(self) -> None:
        if not self._task:
            return
        self._stop_event.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    def last_status(self) -> Optional[DiskStatus]:
        return self._last_status

    def check(self, path: Path) -> bool:
        """Synchronous check if disk space is sufficient.

        Returns True if free space >= threshold, False otherwise.
        """
        status = self._check(path)
        self._last_status = status
        if not status.ok:
            self._logger.warning(
                "Disk guard blocking recording: free=%.2f GB threshold=%.2f GB",
                status.free_gb,
                status.threshold_gb,
            )
        return status.ok

    async def _loop(self, path: Path) -> None:
        try:
            while not self._stop_event.is_set():
                self._last_status = await asyncio.to_thread(self._check, path)
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            return

    def _check(self, path: Path) -> DiskStatus:
        try:
            usage = shutil.disk_usage(path)
            free_gb = usage.free / (1024**3)
        except Exception:
            free_gb = 0.0
        ok = free_gb >= self._threshold
        return DiskStatus(ok=ok, free_gb=free_gb, threshold_gb=self._threshold)


# ---------------------------------------------------------------------------
# Known Cameras Cache


CACHE_SCHEMA_VERSION = 2


class KnownCamerasCache:
    """Async persistence for known camera descriptors/capabilities/configs."""

    def __init__(self, cache_path: Path, *, logger: LoggerLike = None) -> None:
        self._path = Path(cache_path)
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._lock = asyncio.Lock()
        self._entries: Dict[str, dict] = {}
        self._loaded = False

    # ------------------------------------------------------------------
    # Public API

    async def load(self) -> None:
        if self._loaded:
            return
        async with self._lock:
            if self._loaded:
                return
            data = await self._read_file()
            # Clean up legacy entries with unstable IDs
            cleaned, removed = self._cleanup_legacy_entries(data)
            self._entries = cleaned
            self._loaded = True
            if removed:
                self._logger.info(
                    "Removed %d legacy cache entries with unstable IDs: %s",
                    len(removed), removed
                )
                # Persist the cleanup
                await self._write_file(self._entries)
            self._logger.debug("Known cameras cache loaded (%d entries)", len(self._entries))

    async def save(self) -> None:
        async with self._lock:
            await self._write_file(self._entries)

    async def get(self, camera_id: CameraId) -> Optional[CameraRuntimeState]:
        await self.load()
        payload = self._entries.get(camera_id.key)
        if not payload:
            return None
        state = deserialize_camera_state(payload.get("state"))
        return state

    async def update(self, state: CameraRuntimeState) -> None:
        await self.load()
        async with self._lock:
            entry = {
                "updated_at": time.time(),
                "state": serialize_camera_state(state),
            }
            self._entries[state.descriptor.camera_id.key] = entry
            await self._write_file(self._entries)
            self._logger.debug("Updated cache for %s", state.descriptor.camera_id.key)

    async def remove(self, camera_id: CameraId) -> None:
        await self.load()
        async with self._lock:
            if camera_id.key in self._entries:
                self._entries.pop(camera_id.key, None)
                await self._write_file(self._entries)
                self._logger.debug("Removed cache entry for %s", camera_id.key)

    async def list_ids(self) -> Iterable[str]:
        await self.load()
        return list(self._entries.keys())

    async def snapshot(self) -> Dict[str, dict]:
        await self.load()
        return dict(self._entries)

    # ------------------------------------------------------------------
    # Per-camera settings

    async def get_settings(
        self,
        camera_key: str,
        *,
        validator: Optional["CapabilityValidator"] = None,
    ) -> Optional[Dict[str, Any]]:
        """Get stored settings for a camera.

        If no settings exist but legacy selected_configs do, migrates them
        to the new settings format automatically.

        Args:
            camera_key: The camera identifier key.
            validator: Optional CapabilityValidator to validate settings against
                      camera capabilities before returning.

        Returns:
            Settings dict, optionally validated against capabilities.
        """
        await self.load()
        entry = self._entries.get(camera_key)
        if not entry:
            return None

        settings: Optional[Dict[str, Any]] = None

        # Return existing settings if present
        if "settings" in entry:
            settings = entry.get("settings")
        else:
            # Migrate from legacy selected_configs if present
            state = entry.get("state")
            if state and isinstance(state, dict):
                selected_configs = state.get("selected_configs")
                if selected_configs:
                    migrated = self._migrate_selected_configs(selected_configs)
                    if migrated:
                        self._logger.info(
                            "Migrated selected_configs to settings for %s", camera_key
                        )
                        # Store migrated settings (don't await inside get, schedule write)
                        entry["settings"] = migrated
                        asyncio.create_task(self._save_migration(camera_key, migrated))
                        settings = migrated

        # Validate settings against capabilities if validator provided
        if settings and validator:
            validated = validator.validate_settings(settings)
            if validated != settings:
                self._logger.debug(
                    "Validated settings for %s: %s -> %s", camera_key, settings, validated
                )
            return validated

        return settings

    def _migrate_selected_configs(self, selected_configs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert legacy selected_configs format to settings format."""
        try:
            settings: Dict[str, Any] = {}

            # Extract preview settings
            preview = selected_configs.get("preview", {})
            if preview:
                mode = preview.get("mode", {})
                size = mode.get("size")
                if size and len(size) == 2:
                    settings["preview_resolution"] = f"{size[0]}x{size[1]}"
                target_fps = preview.get("target_fps")
                if target_fps is not None:
                    settings["preview_fps"] = str(target_fps)

            # Extract record settings
            record = selected_configs.get("record", {})
            if record:
                mode = record.get("mode", {})
                size = mode.get("size")
                if size and len(size) == 2:
                    settings["record_resolution"] = f"{size[0]}x{size[1]}"
                target_fps = record.get("target_fps")
                if target_fps is not None:
                    settings["record_fps"] = str(target_fps)
                overlay = record.get("overlay")
                if overlay is not None:
                    settings["overlay"] = "true" if overlay else "false"

            return settings if settings else None
        except Exception:
            return None

    async def _save_migration(self, camera_key: str, settings: Dict[str, Any]) -> None:
        """Persist migrated settings to disk."""
        async with self._lock:
            if camera_key in self._entries:
                self._entries[camera_key]["settings"] = settings
                self._entries[camera_key]["updated_at"] = time.time()
                await self._write_file(self._entries)

    def _cleanup_legacy_entries(self, entries: Dict[str, dict]) -> tuple[Dict[str, dict], list[str]]:
        """Remove entries with legacy/unstable camera IDs.

        Legacy entries include:
        - usb:/dev/video* - Uses unstable device path instead of USB bus path
        - picam:<sensor_model> - Uses sensor model instead of sensor index

        These entries were created by older code and will never match current
        camera assignments, so they just waste space.

        Returns:
            Tuple of (cleaned_entries, removed_keys)
        """
        cleaned: Dict[str, dict] = {}
        removed: list[str] = []

        for key, payload in entries.items():
            if self._is_legacy_key(key):
                removed.append(key)
            else:
                cleaned[key] = payload

        return cleaned, removed

    @staticmethod
    def _is_legacy_key(key: str) -> bool:
        """Check if a cache key uses a legacy/unstable ID format."""
        # Legacy USB format: usb:/dev/video* (device paths are not stable)
        if key.startswith("usb:/dev/"):
            return True

        # Legacy picam format: picam:<sensor_model> instead of picam:<index>
        # Current format uses numeric indices like "picam:0", "picam:1"
        if key.startswith("picam:"):
            stable_id = key[6:]  # Remove "picam:" prefix
            # If stable_id is not a digit, it's a legacy sensor model name
            if stable_id and not stable_id.isdigit():
                return True

        return False

    async def set_settings(
        self,
        camera_key: str,
        settings: Dict[str, Any],
        *,
        validator: Optional["CapabilityValidator"] = None,
    ) -> None:
        """Store settings for a camera.

        Args:
            camera_key: The camera identifier key.
            settings: Settings dict to store.
            validator: Optional CapabilityValidator to validate settings against
                      camera capabilities before storing.
        """
        await self.load()

        # Validate settings against capabilities if validator provided
        if validator:
            validated = validator.validate_settings(settings)
            if validated != settings:
                self._logger.debug(
                    "Validated settings before save for %s: %s -> %s",
                    camera_key, settings, validated
                )
            settings = validated

        async with self._lock:
            if camera_key not in self._entries:
                self._entries[camera_key] = {"updated_at": time.time()}
            self._entries[camera_key]["settings"] = dict(settings)
            self._entries[camera_key]["updated_at"] = time.time()
            await self._write_file(self._entries)
            self._logger.debug("Saved settings for %s: %s", camera_key, settings)

    async def get_all_settings(self) -> Dict[str, Dict[str, Any]]:
        """Get settings for all cameras."""
        await self.load()
        result = {}
        for key, entry in self._entries.items():
            if "settings" in entry:
                result[key] = entry["settings"]
        return result

    # ------------------------------------------------------------------
    # IO helpers

    async def _read_file(self) -> Dict[str, dict]:
        if not self._path.exists():
            return {}
        try:
            text = await asyncio.to_thread(self._path.read_text, "utf-8")
            parsed = json.loads(text)
        except Exception:
            self._logger.warning("Known cameras cache unreadable; starting fresh")
            return {}

        if not isinstance(parsed, dict):
            return {}
        schema_version = int(parsed.get("schema", 0) or 0)
        if schema_version not in (1, 2):
            self._logger.info("Known cameras cache schema mismatch; ignoring old data")
            return {}

        entries = parsed.get("entries") or {}
        if not isinstance(entries, dict):
            return {}
        # Validate each entry structure - allow entries with state and/or settings
        valid: Dict[str, dict] = {}
        for key, payload in entries.items():
            if not isinstance(payload, dict):
                continue
            # Accept entries that have state or settings (or both)
            if "state" not in payload and "settings" not in payload:
                continue
            valid[key] = payload
        return valid

    async def _write_file(self, entries: Dict[str, dict]) -> None:
        payload = {"schema": CACHE_SCHEMA_VERSION, "entries": entries}
        text = json.dumps(payload, indent=2, sort_keys=True)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(self._path.write_text, text, "utf-8")
        except Exception:
            self._logger.warning("Failed to write known cameras cache %s", self._path, exc_info=True)


__all__ = ["DiskGuard", "DiskStatus", "KnownCamerasCache", "CACHE_SCHEMA_VERSION"]
