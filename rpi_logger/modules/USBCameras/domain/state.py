"""Model definitions and persistence helpers for the USB Cameras runtime."""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from rpi_logger.modules.base.overlay_defaults import get_camera_overlay_defaults
from rpi_logger.modules.base.preferences import ModulePreferences
from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger(__name__)


class USBCameraModel:
    """Holds runtime configuration, persistence helpers, and shared state."""

    PREVIEW_SIZE = (640, 480)
    UPDATE_INTERVAL = 0.2  # seconds
    MAX_NATIVE_SIZE = (1920, 1080)
    NATIVE_ASPECT = MAX_NATIVE_SIZE[1] / MAX_NATIVE_SIZE[0]
    STORAGE_QUEUE_DEFAULT = 8
    SESSION_RETENTION_DEFAULT = 5
    MIN_FREE_SPACE_MB_DEFAULT = 512

    def __init__(
        self,
        *,
        args,
        module_dir: Path,
        display_name: str,
        logger: logging.Logger,
        config_path: Optional[Path] = None,
        preferences: Optional[ModulePreferences] = None,
    ) -> None:
        self.args = args
        self.module_dir = module_dir
        self.display_name = display_name
        self.logger = logger
        self.config_path = config_path or (module_dir / "config.txt")
        self.preferences = preferences or ModulePreferences(self.config_path)
        # Mirror the Cameras overlay defaults so recorder overlays match exactly.
        self.overlay_config: Dict[str, Any] = get_camera_overlay_defaults()
        self.camera_aliases: dict[int, str] = {}
        self._camera_alias_slugs: dict[int, str] = {}

        self._status_message = "Initializing"
        self.config_data: Dict[str, Any] = self.preferences.snapshot()
        self.apply_saved_preferences()

        self.save_frame_interval = self._compute_save_interval()
        self.preview_frame_interval = self._compute_preview_interval()

        self.save_enabled = bool(getattr(self.args, "save_images", False))
        self.capture_preferences_enabled = bool(self.save_enabled)

        self.save_format = self._compute_save_format()
        self.save_quality = self._compute_save_quality()

        retention_arg = self._safe_int(
            getattr(self.args, "session_retention", self.SESSION_RETENTION_DEFAULT)
        )
        self.session_retention = max(0, retention_arg or self.SESSION_RETENTION_DEFAULT)

        free_space_arg = self._safe_int(
            getattr(self.args, "min_free_space_mb", self.MIN_FREE_SPACE_MB_DEFAULT)
        )
        self.min_free_space_mb = max(0, free_space_arg or self.MIN_FREE_SPACE_MB_DEFAULT)

        queue_size_arg = self._safe_int(
            getattr(self.args, "storage_queue_size", self.STORAGE_QUEUE_DEFAULT)
        )
        self.storage_queue_size = max(1, queue_size_arg or self.STORAGE_QUEUE_DEFAULT)

        self.save_dir: Optional[Path] = None
        self.session_dir: Optional[Path] = None
        if self.save_enabled:
            base_dir = self.resolve_save_dir()
            if base_dir:
                session_dir = self.prepare_session_directory_sync(base_dir)
                if session_dir is None:
                    self.logger.error("Initial recording session unavailable; saving disabled")
                    self.save_enabled = False
                else:
                    self.save_dir = base_dir
                    self.session_dir = session_dir
            else:
                self.logger.error("Unable to determine save directory; saving disabled")
                self.save_enabled = False

    # ------------------------------------------------------------------
    # Status helpers

    @property
    def status_message(self) -> str:
        return self._status_message

    def update_status(self, message: str, *, level: int = logging.INFO) -> None:
        if message == self._status_message:
            return
        self._status_message = message
        try:
            self.logger.log(level, "Status -> %s", message)
        except Exception:  # pragma: no cover - defensive
            self.logger.info("Status -> %s", message)

    # ------------------------------------------------------------------
    # Preference persistence

    def apply_saved_preferences(self) -> None:
        aliases = {}
        for key, value in self.config_data.items():
            if not key.startswith("camera_") or not key.endswith("_alias"):
                continue
            alias = str(value).strip()
            if not alias:
                continue
            index_part = key[len("camera_") : -len("_alias")]
            try:
                index = int(index_part) - 1
            except ValueError:
                continue
            aliases[index] = alias

        self.camera_aliases = aliases
        self._camera_alias_slugs = self._build_alias_slugs(self.camera_aliases)

    # ------------------------------------------------------------------
    # Input helpers

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        try:
            return int(value)
        except Exception:
            return None

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        try:
            return float(value)
        except Exception:
            return None

    def _compute_save_interval(self) -> float:
        fps = self._safe_float(getattr(self.args, "save_fps", None))
        if fps is None:
            return 0.0
        if fps <= 0:
            return 0.0
        return 1.0 / fps

    def _compute_preview_interval(self) -> float:
        fps = self._safe_float(getattr(self.args, "preview_fps", None))
        if fps and fps > 0:
            return 1.0 / fps
        interval = self._safe_float(getattr(self.args, "preview_interval", None))
        if interval is None or interval < 0:
            return self.UPDATE_INTERVAL
        return interval or 0.0

    def _compute_save_format(self) -> str:
        fmt = str(getattr(self.args, "save_format", "jpeg")).strip().lower()
        if fmt not in {"jpeg", "png", "webp"}:
            return "jpeg"
        return fmt

    def _compute_save_quality(self) -> int:
        value = self._safe_int(getattr(self.args, "save_quality", 90))
        if value is None:
            return 90
        return max(1, min(100, value))

    # ------------------------------------------------------------------
    # Camera alias helpers

    def set_camera_alias(self, index: int, alias: str) -> None:
        self.camera_aliases[index] = alias
        self._camera_alias_slugs = self._build_alias_slugs(self.camera_aliases)

    def get_camera_alias(self, index: int) -> str:
        return self.camera_aliases.get(index, self._default_camera_alias(index))

    def get_camera_alias_slug(self, index: int) -> str:
        if not self._camera_alias_slugs:
            self._camera_alias_slugs = self._build_alias_slugs(self.camera_aliases)
        return self._camera_alias_slugs.get(index, self._default_camera_slug(index))

    def _build_alias_slugs(self, aliases: dict[int, str]) -> dict[int, str]:
        seen: dict[str, int] = {}
        slugs: dict[int, str] = {}
        for idx, alias in aliases.items():
            candidate = self._slugify_alias(alias)
            if not candidate:
                candidate = self._default_camera_slug(idx)
            normalized = candidate.lower()
            occurrence = seen.get(normalized, 0)
            seen[normalized] = occurrence + 1
            slug = candidate if occurrence == 0 else f"{candidate}_{occurrence + 1}"
            slugs[idx] = slug
        return slugs

    @staticmethod
    def _slugify_alias(alias: str) -> str:
        if not isinstance(alias, str):
            return ""
        return re.sub(r"[^A-Za-z0-9]+", "_", alias).strip("_")

    @staticmethod
    def _default_camera_alias(index: int) -> str:
        return f"Camera {index + 1}"

    @staticmethod
    def _default_camera_slug(index: int) -> str:
        return f"Camera_{index + 1}"

    # ------------------------------------------------------------------
    # Directory helpers

    def resolve_save_dir(self) -> Path:
        explicit = getattr(self.args, "save_dir", None)
        if explicit:
            return Path(explicit)

        output_root = getattr(self.args, "output_dir", None)
        if output_root:
            base = Path(output_root)
        else:
            base = Path.cwd() / "usb_cameras"
        return base / "captures"

    def prepare_session_directory_sync(self, base_dir: Path) -> Optional[Path]:
        try:
            base_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.error("Unable to prepare base save directory %s: %s", base_dir, exc)
            return None

        if not self._has_min_free_space(base_dir):
            self.logger.error(
                "Insufficient free space (need %d MB) for recordings in %s",
                self.min_free_space_mb,
                base_dir,
            )
            return None

        try:
            self._prune_old_sessions_sync(base_dir)
            return self._create_session_dir_sync(base_dir)
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.error("Failed to create session directory under %s: %s", base_dir, exc)
            return None

    async def prepare_session_directory(self, base_dir: Path) -> Optional[Path]:
        return await asyncio.to_thread(self.prepare_session_directory_sync, base_dir)

    def ensure_camera_dir_sync(self, camera_index: int, session_dir: Path) -> Path:
        camera_dir_name = self.get_camera_alias_slug(camera_index)
        camera_dir = session_dir / camera_dir_name
        camera_dir.mkdir(parents=True, exist_ok=True)
        return camera_dir

    def _create_session_dir_sync(self, base_dir: Path) -> Path:
        timestamp = datetime.utcnow().strftime("session_%Y%m%d_%H%M%S")
        for attempt in range(50):
            suffix = f"_{attempt:02d}" if attempt else ""
            candidate = base_dir / f"{timestamp}{suffix}"
            if not candidate.exists():
                candidate.mkdir(parents=False, exist_ok=False)
                return candidate
        raise RuntimeError("Unable to allocate unique session directory")

    def _prune_old_sessions_sync(self, base_dir: Path) -> None:
        if self.session_retention <= 0:
            return
        try:
            entries = [
                path
                for path in base_dir.iterdir()
                if path.is_dir() and path.name.startswith("session_")
            ]
        except FileNotFoundError:
            return
        entries.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        for obsolete in entries[self.session_retention :]:
            try:
                shutil.rmtree(obsolete)
                self.logger.info("Pruned old session %s", obsolete)
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.warning("Unable to prune session %s: %s", obsolete, exc)

    def _has_min_free_space(self, path: Path) -> bool:
        if self.min_free_space_mb <= 0:
            return True
        try:
            usage = shutil.disk_usage(path)
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.debug("Disk usage probe failed for %s: %s", path, exc)
            return True
        return usage.free >= self.min_free_space_mb * 1024 * 1024

    # ------------------------------------------------------------------
    # Geometry helpers

    @staticmethod
    def _ensure_even_dimensions(width: int, height: int) -> tuple[int, int]:
        width = max(2, width - (width % 2))
        height = max(2, height - (height % 2))
        return width, height

    @staticmethod
    def normalize_size(value: Any) -> Optional[tuple[int, int]]:
        if value is None:
            return None
        if isinstance(value, tuple) and len(value) == 2:
            try:
                return int(value[0]), int(value[1])
            except Exception:
                return None
        try:
            parts = str(value).lower().replace("x", " ").replace(",", " ").split()
            if len(parts) != 2:
                return None
            width = int(float(parts[0]))
            height = int(float(parts[1]))
            return width, height
        except Exception:
            return None

    def clamp_resolution(
        self,
        width: int,
        height: int,
        native: Optional[tuple[int, int]],
    ) -> tuple[int, int]:
        max_width, max_height = native if native else self.MAX_NATIVE_SIZE
        width = min(max_width, max(64, width))
        height = min(max_height, max(64, height))
        return self._ensure_even_dimensions(width, height)

    def enforce_native_aspect(self, width: int, height: int) -> tuple[int, int]:
        if width <= 0 or height <= 0:
            return self.MAX_NATIVE_SIZE
        actual_aspect = height / width
        target_aspect = self.NATIVE_ASPECT
        if abs(actual_aspect - target_aspect) < 0.01:
            return self._ensure_even_dimensions(width, height)
        adjusted_height = int(round(width * target_aspect))
        return self._ensure_even_dimensions(width, adjusted_height)


__all__ = ["USBCameraModel"]
