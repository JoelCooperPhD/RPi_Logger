"""Model component for the stub (codex) module."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import shutil
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set

from rpi_logger.cli.common import ensure_directory, log_module_shutdown, log_module_startup, setup_module_logging
from rpi_logger.core.config_manager import get_config_manager
from rpi_logger.core.commands import StatusMessage, StatusType
from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.core.paths import USER_MODULE_CONFIG_DIR
from .preferences import ModulePreferences, PreferenceChange
from .constants import DISPLAY_NAME, MODULE_ID, PLACEHOLDER_GEOMETRY


logger = get_module_logger(__name__)


class ModuleState(Enum):
    """High-level lifecycle phases for the stub module."""

    INITIALIZING = "initializing"
    IDLE = "idle"
    RECORDING = "recording"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass(slots=True)
class RuntimeMetrics:
    ready_ms: float = 0.0
    runtime_ms: float = 0.0
    shutdown_ms: float = 0.0
    shutdown_trigger_ms: float = 0.0
    window_ms: float = 0.0


class StubCodexModel:
    """Holds module state and orchestrates environment preparation."""

    def __init__(
        self,
        args,
        module_dir: Path,
        *,
        display_name: str = DISPLAY_NAME,
        module_id: str = MODULE_ID,
        config_path: Optional[Path] = None,
        config_filename: str = "config.txt",
    ) -> None:
        self.args = args
        self.module_dir = module_dir
        self.display_name = display_name
        self.module_id = module_id
        self.shutdown_event = asyncio.Event()
        self.shutdown_reason: Optional[str] = None
        self.window_duration_ms: float = 0.0
        self.metrics = RuntimeMetrics()
        self._startup_timestamp = time.perf_counter()
        self.session_name: Optional[str] = None
        self.log_file: Optional[Path] = None
        self.logs_dir = module_dir / "logs"
        self._template_config_path = Path(config_path) if config_path else module_dir / config_filename
        self._using_fallback_config = False
        self.config_path = self._prepare_config_path()
        self.preferences = ModulePreferences(
            self.config_path,
            on_change=self._handle_preferences_changed,
        )
        self.config_data: Dict[str, Any] = self.preferences.snapshot()
        self.saved_window_geometry: Optional[str] = None
        self.saved_preview_resolution: Optional[str] = None
        self.saved_preview_width: Optional[int] = None
        self.saved_preview_height: Optional[int] = None
        self._pending_window_geometry: Optional[str] = None
        self._state: ModuleState = ModuleState.INITIALIZING
        self._recording: bool = False
        self._trial_number: Optional[int] = None
        self._session_dir: Optional[Path] = None
        self._error_message: Optional[str] = None
        self._observers: List[Callable[[str, Any], None]] = []

        config_snapshot = self.config_data
        self.saved_window_geometry = config_snapshot.get("window_geometry")

        resolution, width, height, _ = self._resolve_preview_preferences(config_snapshot)
        self.saved_preview_resolution = resolution
        self.saved_preview_width = width
        self.saved_preview_height = height
        self._apply_preview_preferences_to_args(resolution, width, height)

    @property
    def startup_timestamp(self) -> float:
        return self._startup_timestamp

    async def prepare_environment(self, logger) -> None:
        """Ensure filesystem layout and logging artefacts exist with minimal blocking."""

        output_dir = Path(self.args.output_dir)
        output_task = asyncio.create_task(asyncio.to_thread(ensure_directory, output_dir))

        config_manager = get_config_manager()
        config: Dict[str, Any] = {}
        config_exists = await asyncio.to_thread(self.config_path.exists)

        if config_exists:
            with contextlib.suppress(Exception):
                await asyncio.to_thread(self.config_path.chmod, 0o666)
            config = await config_manager.read_config_async(self.config_path)
        else:
            # Bootstrap minimal defaults so later updates succeed.
            bootstrap = {
                "display_name": self.display_name,
                "enabled": False,
                "window_geometry": PLACEHOLDER_GEOMETRY,
                "preview_width": 640,
                "preview_height": 480,
                "preview_fps": "unlimited",
                "save_width": 640,
                "save_height": 480,
                "save_fps": "unlimited",
                "save_format": "jpeg",
                "save_quality": 90,
            }
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(
                self.config_path.write_text,
                "\n".join(f"{key} = {value}" for key, value in bootstrap.items()) + "\n",
                "utf-8",
            )
            config = dict(bootstrap)
            config_exists = True

        config_updates: Dict[str, Any] = {}
        if config.get("display_name") != self.display_name:
            config_updates["display_name"] = self.display_name

        geometry = config.get("window_geometry")
        if not geometry:
            geometry = PLACEHOLDER_GEOMETRY
            config_updates["window_geometry"] = geometry

        preview_resolution, preview_width, preview_height, preview_updates = self._resolve_preview_preferences(config)
        if preview_updates:
            config_updates.update(preview_updates)

        if config_updates and config_exists:
            success = await config_manager.write_config_async(self.config_path, config_updates)
            if success:
                config.update(config_updates)
            else:
                logger.warning(
                    "Failed to persist config updates %s to %s",
                    list(config_updates.keys()),
                    self.config_path,
                )

        self.preferences.reload()
        self.config_data = self.preferences.snapshot()
        self.saved_window_geometry = self.config_data.get("window_geometry") or PLACEHOLDER_GEOMETRY
        (
            self.saved_preview_resolution,
            self.saved_preview_width,
            self.saved_preview_height,
            _,
        ) = self._resolve_preview_preferences(self.config_data)
        self._apply_preview_preferences_to_args(
            self.saved_preview_resolution,
            self.saved_preview_width,
            self.saved_preview_height,
        )

        self.args.output_dir = await output_task

        session_name, log_file, _ = setup_module_logging(
            self.args,
            module_name=self.module_id,
            module_dir=self.module_dir,
            default_prefix=self.module_id,
        )
        self.session_name = session_name
        self.log_file = log_file

        with contextlib.suppress(Exception):
            await asyncio.to_thread(self.logs_dir.chmod, 0o777)
            await asyncio.to_thread(log_file.chmod, 0o666)

        log_module_startup(
            logger,
            session_name,
            log_file,
            self.args,
            module_name=self.display_name,
        )
        if self._using_fallback_config:
            logger.info(
                "Using writable config store %s (template %s unavailable for writes)",
                self.config_path,
                self._template_config_path,
            )

    def mark_ready(self) -> float:
        ready_elapsed_ms = (time.perf_counter() - self._startup_timestamp) * 1000.0
        self.metrics.ready_ms = ready_elapsed_ms
        StatusMessage.send(
            StatusType.INITIALIZED,
            {"message": f"{self.display_name} ready", "ready_ms": round(ready_elapsed_ms, 1)},
        )
        self.state = ModuleState.IDLE
        return ready_elapsed_ms

    def request_shutdown(self, reason: str) -> None:
        if self.shutdown_event.is_set():
            return
        self.shutdown_reason = reason
        self.mark_shutdown_phase()
        self.state = ModuleState.STOPPED
        self.shutdown_event.set()

    def record_window_duration(self, duration_ms: float) -> None:
        self.window_duration_ms = max(0.0, duration_ms)

    def finalize_metrics(self) -> None:
        total_runtime_ms = (time.perf_counter() - self._startup_timestamp) * 1000.0
        self.metrics.runtime_ms = total_runtime_ms
        trigger_ms = self.metrics.shutdown_trigger_ms
        if trigger_ms > 0.0 and total_runtime_ms >= trigger_ms:
            self.metrics.shutdown_ms = max(0.0, total_runtime_ms - trigger_ms)
        elif self.metrics.shutdown_ms == 0.0 and self.shutdown_reason:
            shutdown_elapsed = total_runtime_ms - self.metrics.ready_ms
            self.metrics.shutdown_ms = max(0.0, shutdown_elapsed)
        self.metrics.window_ms = self.window_duration_ms

    def mark_shutdown_phase(self) -> None:
        shutdown_elapsed_ms = (time.perf_counter() - self._startup_timestamp) * 1000.0
        self.metrics.shutdown_trigger_ms = shutdown_elapsed_ms

    def emit_shutdown_logs(self, logger) -> None:
        log_module_shutdown(logger, self.display_name)

    def send_runtime_report(self) -> None:
        StatusMessage.send(
            StatusType.STATUS_REPORT,
            {
                "event": "shutdown_timing",
                "display_name": self.display_name,
                "runtime_ms": round(self.metrics.runtime_ms, 1),
                "shutdown_ms": round(self.metrics.shutdown_ms, 1),
                "window_ms": round(self.metrics.window_ms, 1),
            },
        )

    # Observable state helpers -------------------------------------------------

    def subscribe(self, observer: Callable[[str, Any], None]) -> None:
        self._observers.append(observer)

    def _notify(self, prop: str, value: Any) -> None:
        for observer in list(self._observers):
            try:
                observer(prop, value)
            except Exception:
                continue

    def _handle_preferences_changed(self, change: PreferenceChange) -> None:
        """Refresh cached config data when ModulePreferences writes succeed."""
        self.config_data = self.preferences.snapshot()
        geometry = self.config_data.get("window_geometry")
        if geometry:
            self.saved_window_geometry = geometry
        (
            self.saved_preview_resolution,
            self.saved_preview_width,
            self.saved_preview_height,
            _,
        ) = self._resolve_preview_preferences(self.config_data)
        self._notify("preferences", change)

    @property
    def state(self) -> ModuleState:
        return self._state

    @state.setter
    def state(self, value: ModuleState) -> None:
        if self._state is value:
            return
        self._state = value
        self._notify("state", value)

    @property
    def recording(self) -> bool:
        return self._recording

    @recording.setter
    def recording(self, active: bool) -> None:
        if self._recording == active:
            return
        self._recording = active
        if active:
            self.state = ModuleState.RECORDING
        elif self._state is ModuleState.RECORDING:
            self.state = ModuleState.IDLE
        self._notify("recording", active)

    @property
    def trial_number(self) -> Optional[int]:
        return self._trial_number

    @trial_number.setter
    def trial_number(self, value: Optional[int]) -> None:
        if self._trial_number == value:
            return
        self._trial_number = value
        self._notify("trial_number", value)

    @property
    def session_dir(self) -> Optional[Path]:
        return self._session_dir

    @session_dir.setter
    def session_dir(self, path: Optional[Path]) -> None:
        if self._session_dir == path:
            return
        self._session_dir = path
        self._notify("session_dir", path)

    @property
    def error_message(self) -> Optional[str]:
        return self._error_message

    @error_message.setter
    def error_message(self, message: Optional[str]) -> None:
        if self._error_message == message:
            return
        self._error_message = message
        if message:
            self.state = ModuleState.ERROR
        self._notify("error_message", message)

    def get_status_snapshot(self) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "recording": self.recording,
            "trial_number": self.trial_number,
            "session_dir": str(self.session_dir) if self.session_dir else None,
            "error": self.error_message,
        }

    def get_preference(self, key: str, default: Optional[Any] = None) -> Any:
        return self.config_data.get(key, default)

    def get_preference_bool(
        self,
        key: str,
        default: bool = False,
        *,
        fallback_keys: Optional[Iterable[str]] = None,
    ) -> bool:
        candidates = [key]
        if fallback_keys:
            candidates.extend(fallback_keys)
        for candidate in candidates:
            if candidate in self.config_data:
                value = str(self.config_data[candidate]).strip().lower()
                return value in {"true", "1", "yes", "on"}
        return default

    def preferences_scope(self, namespace: str, *, separator: str = "."):
        return self.preferences.scope(namespace, separator=separator)

    # Internal helpers -------------------------------------------------------

    def _prepare_config_path(self) -> Path:
        template = self._template_config_path
        if self._path_is_writable(template):
            return template

        fallback_dir = USER_MODULE_CONFIG_DIR / self.module_id
        fallback_dir.mkdir(parents=True, exist_ok=True)
        fallback_path = fallback_dir / template.name
        if not fallback_path.exists():
            try:
                if template.exists():
                    shutil.copy2(template, fallback_path)
                else:
                    fallback_path.touch()
            except Exception as exc:
                logger.warning("Failed to seed fallback config %s: %s", fallback_path, exc)
        self._using_fallback_config = True
        return fallback_path

    @staticmethod
    def _path_is_writable(path: Path) -> bool:
        if path.exists():
            return os.access(path, os.W_OK)
        parent = path.parent
        return parent.exists() and os.access(parent, os.W_OK)

    # Window geometry helpers -------------------------------------------------

    def apply_initial_window_geometry(self) -> None:
        if getattr(self.args, "window_geometry", None):
            return
        if self.saved_window_geometry:
            setattr(self.args, "window_geometry", self.saved_window_geometry)

    def set_window_geometry(self, geometry: Optional[str]) -> bool:
        if not geometry:
            return False

        geometry = str(geometry).strip()
        if not geometry:
            return False

        if geometry == self.saved_window_geometry and self._pending_window_geometry is None:
            return False

        if geometry == self._pending_window_geometry:
            return False

        self._pending_window_geometry = geometry
        return True

    async def persist_window_geometry(self) -> None:
        if not self._pending_window_geometry:
            return
        if self._pending_window_geometry == self.saved_window_geometry:
            self._pending_window_geometry = None
            return

        geometry_str = self._pending_window_geometry

        # Send geometry to parent process for per-instance persistence.
        # This is critical for multi-instance modules (DRT, VOG) where each
        # device instance needs its own saved window position.
        self._send_geometry_changed_status(geometry_str)

        update = {"window_geometry": geometry_str}
        success = await self.preferences.write_async(update)
        if success:
            self.saved_window_geometry = geometry_str
            self.config_data["window_geometry"] = self.saved_window_geometry
            self._pending_window_geometry = None

    def _send_geometry_changed_status(self, geometry_str: str) -> None:
        """Send geometry_changed StatusMessage to parent process.

        For multi-instance modules, includes instance_id so the parent can
        save geometry per-instance in instance_geometry_store.

        Sends raw Tk coordinates - no normalization needed since the entire
        pipeline now uses raw Tk coords consistently.
        """
        # Parse geometry string (format: WIDTHxHEIGHT+X+Y or WIDTHxHEIGHT-X-Y)
        match = re.match(r"^(\d+)x(\d+)([-+]\d+)([-+]\d+)$", geometry_str)
        if not match:
            self.logger.debug("Could not parse geometry for status: %s", geometry_str)
            return

        width = int(match.group(1))
        height = int(match.group(2))
        x = int(match.group(3))
        y = int(match.group(4))

        payload = {
            "width": width,
            "height": height,
            "x": x,
            "y": y,
        }

        # Include instance_id for multi-instance module support
        instance_id = getattr(self.args, "instance_id", None)
        if instance_id:
            payload["instance_id"] = instance_id

        StatusMessage.send("geometry_changed", payload)
        self.logger.debug(
            "Sent geometry_changed to parent: %dx%d+%d+%d (instance: %s)",
            width, height, x, y, instance_id or "none"
        )

    def has_pending_window_geometry(self) -> bool:
        return bool(self._pending_window_geometry)

    # Preview preference helpers ---------------------------------------------

    async def persist_preview_size(self, selection: Any) -> None:
        if selection is None:
            return

        resolution, width, height = self._normalize_preview_selection(selection)
        if not resolution:
            return

        current_resolution = self.saved_preview_resolution or ""
        if resolution == current_resolution:
            width_match = width is None or width == self.saved_preview_width
            height_match = height is None or height == self.saved_preview_height
            if width_match and height_match:
                return

        updates: Dict[str, Any] = {"preview_resolution": resolution}
        if width is not None and height is not None:
            updates["preview_width"] = width
            updates["preview_height"] = height

        success = await self.preferences.write_async(updates)
        if not success:
            logger.warning("Failed to persist preview selection: %s", updates)
            return

        self.saved_preview_resolution = resolution
        self.saved_preview_width = width
        self.saved_preview_height = height
        self.config_data.update({k: v for k, v in updates.items()})
        self._apply_preview_preferences_to_args(resolution, width, height)

    def _apply_preview_preferences_to_args(
        self,
        resolution: Optional[str],
        width: Optional[int],
        height: Optional[int],
    ) -> None:
        if not hasattr(self.args, "preview_width") or not hasattr(self.args, "preview_height"):
            return

        if resolution == "auto":
            setattr(self.args, "preview_width", None)
            setattr(self.args, "preview_height", None)
        elif width is not None and height is not None:
            setattr(self.args, "preview_width", width)
            setattr(self.args, "preview_height", height)

    def _resolve_preview_preferences(
        self,
        config: Dict[str, Any],
    ) -> tuple[Optional[str], Optional[int], Optional[int], Dict[str, Any]]:
        resolution_raw = config.get("preview_resolution")
        resolution_source = str(resolution_raw).strip() if resolution_raw is not None else ""
        resolution_lower = resolution_source.lower()

        width_raw = config.get("preview_width")
        height_raw = config.get("preview_height")
        width_value = self._parse_int(width_raw)
        height_value = self._parse_int(height_raw)

        final_resolution = resolution_lower
        final_width = width_value
        final_height = height_value

        if not final_resolution:
            if width_value is not None and height_value is not None:
                final_resolution = f"{width_value}x{height_value}"
            else:
                final_resolution = "auto"

        if final_resolution == "auto":
            final_width = None
            final_height = None
        else:
            parsed_width, parsed_height = self._parse_resolution_string(final_resolution)
            if parsed_width is not None and parsed_height is not None:
                final_width = parsed_width
                final_height = parsed_height
                final_resolution = f"{parsed_width}x{parsed_height}"
            elif width_value is not None and height_value is not None:
                final_resolution = f"{width_value}x{height_value}"
                final_width = width_value
                final_height = height_value
            else:
                final_resolution = "auto"
                final_width = None
                final_height = None

        updates: Dict[str, Any] = {}
        if final_resolution and final_resolution != resolution_source:
            updates["preview_resolution"] = final_resolution
        if final_width is not None and final_width != width_value:
            updates["preview_width"] = final_width
        if final_height is not None and final_height != height_value:
            updates["preview_height"] = final_height

        return final_resolution or None, final_width, final_height, updates

    def _normalize_preview_selection(self, selection: Any) -> tuple[Optional[str], Optional[int], Optional[int]]:
        if isinstance(selection, str):
            key = selection.strip().lower()
            if not key:
                return None, None, None
            if key == "auto":
                return "auto", None, None
            width, height = self._parse_resolution_string(key)
            if width is not None and height is not None:
                return f"{width}x{height}", width, height
            return None, None, None

        if isinstance(selection, (tuple, list)) and len(selection) >= 2:
            width = self._parse_int(selection[0])
            height = self._parse_int(selection[1])
            if width is not None and height is not None:
                return f"{width}x{height}", width, height

        return None, None, None

    @staticmethod
    def _parse_int(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_resolution_string(value: str) -> tuple[Optional[int], Optional[int]]:
        if not value:
            return None, None
        normalized = value.lower().replace(" ", "")
        if "x" not in normalized:
            return None, None
        width_str, height_str = normalized.split("x", 1)
        width = StubCodexModel._parse_int(width_str)
        height = StubCodexModel._parse_int(height_str)
        return width, height

    def get_config_snapshot(self) -> Dict[str, Any]:
        return dict(self.config_data)

    async def persist_preferences(
        self,
        updates: Dict[str, Any],
        *,
        remove_keys: Optional[Set[str]] = None,
    ) -> bool:
        return await self.preferences.write_async(updates, remove_keys=remove_keys)

    def persist_preferences_sync(
        self,
        updates: Dict[str, Any],
        *,
        remove_keys: Optional[Set[str]] = None,
    ) -> bool:
        return self.preferences.write_sync(updates, remove_keys=remove_keys)
