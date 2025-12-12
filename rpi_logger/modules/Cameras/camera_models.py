"""
Camera Model Database.

A shipped database of known camera models and their capabilities.
When a camera is recognized, we skip probing and use stored capabilities.
Unknown cameras fall back to runtime probing with default settings.
"""

from __future__ import annotations

import copy
import fnmatch
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.Cameras.camera_core.state import (
    CameraCapabilities,
    CapabilityMode,
    CapabilitySource,
    ControlInfo,
    deserialize_control,
    serialize_control,
)

if TYPE_CHECKING:
    from rpi_logger.modules.Cameras.camera_core.state import CameraDescriptor

# Schema version for camera_models.json
SCHEMA_VERSION = 1

# Default file location (shipped with module)
DEFAULT_MODELS_PATH = Path(__file__).parent / "camera_models.json"


def extract_model_name(desc: "CameraDescriptor") -> str:
    """
    Extract the camera model name from a descriptor.

    For USB cameras: Uses friendly_name, strips "USB:" prefix and [port] suffix
    For Picam: Uses hw_model directly (sensor name like "imx296")

    Args:
        desc: Camera descriptor containing identification info

    Returns:
        Clean model name for database lookup, or empty string if undetermined.
    """
    backend = desc.camera_id.backend

    if backend == "picam":
        # Picam: hw_model is the sensor name (e.g., "imx296")
        return desc.hw_model or ""

    # USB: friendly_name contains the device name from sysfs
    raw = desc.camera_id.friendly_name or desc.hw_model or ""

    # Strip common prefixes added by our scanners
    for prefix in ("USB:", "RPi:"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):].strip()

    # Strip [port] suffix (e.g., "[usb1-2]", "[1-2]")
    if "[" in raw:
        raw = raw.split("[")[0].strip()

    return raw


def copy_capabilities(caps: CameraCapabilities) -> CameraCapabilities:
    """
    Create a deep copy of capabilities.

    This ensures we never mutate shared capability objects from the database.
    """
    return CameraCapabilities(
        modes=list(caps.modes),  # CapabilityMode is frozen, shallow copy is fine
        default_preview_mode=caps.default_preview_mode,
        default_record_mode=caps.default_record_mode,
        timestamp_ms=caps.timestamp_ms,
        source=caps.source,
        limits=dict(caps.limits),
        color_formats=list(caps.color_formats),
        controls=dict(caps.controls) if caps.controls else {},
    )


@dataclass
class CameraModel:
    """A known camera model with its capabilities."""

    key: str  # Normalized identifier (e.g., "arducam_usb_camera")
    name: str  # Human-readable name
    backend: str  # "usb" or "picam"
    match_patterns: List[str]  # Glob patterns to match raw names
    capabilities: CameraCapabilities
    tested: Optional[str] = None  # ISO date when tested
    notes: Optional[str] = None  # Developer notes
    sensor_info: Optional[Dict[str, Any]] = None  # Detailed sensor/hardware info


@dataclass
class ModelLookupResult:
    """Result of a model database lookup."""

    model: Optional[CameraModel]
    capabilities: CameraCapabilities
    source: CapabilitySource  # DATABASE or PROBE
    model_key: Optional[str] = None


class CameraModelDatabase:
    """
    Database of known camera models and their capabilities.

    This is a shipped asset that grows as the developer tests cameras.
    Unknown cameras fall back to runtime probing.
    """

    def __init__(
        self,
        models_path: Optional[Path] = None,
        *,
        auto_save: bool = True,
        logger: LoggerLike = None,
    ) -> None:
        """
        Initialize the camera model database.

        Args:
            models_path: Path to camera_models.json. Defaults to module directory.
            auto_save: If True, automatically save when new models are added.
            logger: Optional logger instance.
        """
        self._path = Path(models_path) if models_path else DEFAULT_MODELS_PATH
        self._auto_save = auto_save
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._models: Dict[str, CameraModel] = {}
        self._loaded = False

    def load(self) -> None:
        """Load the model database from disk."""
        if self._loaded:
            return

        if not self._path.exists():
            self._logger.info("No camera_models.json found, starting fresh")
            self._loaded = True
            return

        try:
            text = self._path.read_text(encoding="utf-8")
            data = json.loads(text)
            self._parse_models(data)
            self._logger.info(
                "Loaded %d camera models from %s", len(self._models), self._path
            )
        except Exception as e:
            self._logger.warning("Failed to load camera_models.json: %s", e)

        self._loaded = True

    def save(self) -> None:
        """Save the model database to disk."""
        data = self._serialize()
        text = json.dumps(data, indent=2, sort_keys=False)
        try:
            self._path.write_text(text, encoding="utf-8")
            self._logger.info("Saved %d camera models to %s", len(self._models), self._path)
        except Exception as e:
            self._logger.error("Failed to save camera_models.json: %s", e)

    def lookup(self, raw_name: str, backend: str) -> Optional[CameraModel]:
        """
        Look up a camera model by its raw name.

        Args:
            raw_name: The raw camera name from sysfs or Picamera2.
            backend: "usb" or "picam".

        Returns:
            CameraModel if found, None otherwise.
        """
        self.load()

        for model in self._models.values():
            if model.backend != backend:
                continue
            for pattern in model.match_patterns:
                if fnmatch.fnmatch(raw_name, pattern):
                    self._logger.debug(
                        "Matched camera '%s' to model '%s'", raw_name, model.key
                    )
                    return model

        self._logger.debug("No model match for camera '%s' (%s)", raw_name, backend)
        return None

    def get(self, model_key: str) -> Optional[CameraModel]:
        """Get a model by its key."""
        self.load()
        return self._models.get(model_key)

    def add_model(
        self,
        raw_name: str,
        backend: str,
        capabilities: CameraCapabilities,
        *,
        notes: Optional[str] = None,
        force_update: bool = False,
    ) -> CameraModel:
        """
        Add a new camera model to the database, or update if force_update=True.

        Called when a new camera is probed for the first time, or when reprobing.

        Args:
            raw_name: The raw camera name.
            backend: "usb" or "picam".
            capabilities: Probed capabilities.
            notes: Optional developer notes.
            force_update: If True, update existing model with new capabilities.

        Returns:
            The newly created or updated CameraModel.
        """
        self.load()

        key = self._normalize_key(raw_name, backend)

        # Check if we already have this model
        existing = self._models.get(key)
        if existing and not force_update:
            self._logger.debug("Model '%s' already exists, skipping add", key)
            return existing

        if existing and force_update:
            # Update existing model with new capabilities
            model = CameraModel(
                key=existing.key,
                name=existing.name,
                backend=existing.backend,
                match_patterns=existing.match_patterns,
                capabilities=capabilities,  # New capabilities
                tested=time.strftime("%Y-%m-%d"),
                notes=existing.notes,
            )
            self._models[key] = model
            self._logger.info("Updated camera model: %s (%s)", model.name, key)

            if self._auto_save:
                self.save()

            return model

        # Create match pattern from raw name
        match_patterns = [self._create_match_pattern(raw_name)]

        model = CameraModel(
            key=key,
            name=self._extract_display_name(raw_name),
            backend=backend,
            match_patterns=match_patterns,
            capabilities=capabilities,
            tested=time.strftime("%Y-%m-%d"),
            notes=notes,
        )

        self._models[key] = model
        self._logger.info("Added new camera model: %s (%s)", model.name, key)

        if self._auto_save:
            self.save()

        return model

    def list_models(self) -> List[CameraModel]:
        """List all known camera models."""
        self.load()
        return list(self._models.values())

    # -------------------------------------------------------------------------
    # Key normalization

    @staticmethod
    def _normalize_key(raw_name: str, backend: str) -> str:
        """
        Normalize a camera name to a stable key.

        Examples:
            "Arducam USB Camera: Arducam USB" → "arducam_usb_camera"
            "UVC Camera (046d:0819)" → "uvc_046d_0819"
            "imx296" → "imx296"
        """
        key = raw_name.lower()

        # Extract VID:PID if present (most stable identifier)
        vid_pid_match = re.search(r"\(([0-9a-f]{4}):([0-9a-f]{4})\)", key)
        if vid_pid_match:
            return f"uvc_{vid_pid_match.group(1)}_{vid_pid_match.group(2)}"

        # Remove common suffixes and noise
        key = re.sub(r":\s*[\w\s]+$", "", key)  # Remove ": Arducam USB" suffix
        key = re.sub(r"\s*\[.*?\]", "", key)  # Remove [port] annotations
        key = re.sub(r"\s*\(.*?\)", "", key)  # Remove (info) annotations

        # Normalize to identifier
        key = re.sub(r"[^a-z0-9]+", "_", key)
        key = key.strip("_")

        # Collapse repeated underscores
        key = re.sub(r"_+", "_", key)

        return key

    @staticmethod
    def _create_match_pattern(raw_name: str) -> str:
        """Create a glob pattern to match this camera name."""
        # For names with VID:PID, match on that
        vid_pid_match = re.search(r"\([0-9a-fA-F]{4}:[0-9a-fA-F]{4}\)", raw_name)
        if vid_pid_match:
            return f"*{vid_pid_match.group(0)}*"

        # Otherwise use the full name with wildcard suffix
        # Strip port/index annotations first
        clean = re.sub(r"\s*\[.*?\]$", "", raw_name)
        return f"{clean}*" if clean else raw_name

    @staticmethod
    def _extract_display_name(raw_name: str) -> str:
        """Extract a clean display name from the raw name."""
        # Remove port annotations
        name = re.sub(r"\s*\[.*?\]$", "", raw_name)
        # Remove duplicate suffixes like "Arducam USB Camera: Arducam USB"
        if ":" in name:
            parts = name.split(":", 1)
            name = parts[0].strip()
        return name

    # -------------------------------------------------------------------------
    # Serialization

    def _parse_models(self, data: Dict[str, Any]) -> None:
        """Parse models from JSON data."""
        schema = data.get("schema", 1)
        if schema != SCHEMA_VERSION:
            self._logger.warning(
                "camera_models.json schema %d != expected %d", schema, SCHEMA_VERSION
            )

        models_data = data.get("models", {})
        for key, model_data in models_data.items():
            try:
                model = self._parse_model(key, model_data)
                if model:
                    self._models[key] = model
            except Exception as e:
                self._logger.warning("Failed to parse model '%s': %s", key, e)

    def _parse_model(self, key: str, data: Dict[str, Any]) -> Optional[CameraModel]:
        """Parse a single model from JSON data."""
        caps_data = data.get("capabilities", {})
        capabilities = self._parse_capabilities(caps_data)

        return CameraModel(
            key=key,
            name=data.get("name", key),
            backend=data.get("backend", "usb"),
            match_patterns=data.get("match_patterns", []),
            capabilities=capabilities,
            tested=data.get("tested"),
            notes=data.get("notes"),
            sensor_info=data.get("sensor_info"),
        )

    def _parse_capabilities(self, data: Dict[str, Any]) -> CameraCapabilities:
        """Parse capabilities from JSON data."""
        modes: List[CapabilityMode] = []
        for mode_data in data.get("modes", []):
            mode = self._parse_mode(mode_data)
            if mode:
                modes.append(mode)

        default_record = self._parse_mode(data.get("default_record"))
        default_preview = self._parse_mode(data.get("default_preview"))

        # Parse controls
        controls: Dict[str, ControlInfo] = {}
        for name, ctrl_data in (data.get("controls") or {}).items():
            ctrl = deserialize_control(ctrl_data)
            if ctrl:
                controls[name] = ctrl

        return CameraCapabilities(
            modes=modes,
            default_record_mode=default_record,
            default_preview_mode=default_preview,
            source=CapabilitySource.CACHE,
            timestamp_ms=time.time() * 1000,
            limits=dict(data.get("limits") or {}),
            color_formats=list(data.get("color_formats") or []),
            controls=controls,
        )

    @staticmethod
    def _parse_mode(data: Optional[Dict[str, Any]]) -> Optional[CapabilityMode]:
        """Parse a capability mode from JSON data."""
        if not data:
            return None
        size = data.get("size")
        if not size or len(size) != 2:
            return None
        return CapabilityMode(
            size=(int(size[0]), int(size[1])),
            fps=float(data.get("fps", 30.0)),
            pixel_format=data.get("pixel_format", "MJPEG"),
            controls=data.get("controls", {}),
        )

    def _serialize(self) -> Dict[str, Any]:
        """Serialize the database to JSON-friendly dict."""
        models_data = {}
        for key, model in sorted(self._models.items()):
            models_data[key] = self._serialize_model(model)

        return {
            "schema": SCHEMA_VERSION,
            "models": models_data,
        }

    def _serialize_model(self, model: CameraModel) -> Dict[str, Any]:
        """Serialize a single model to JSON-friendly dict."""
        data: Dict[str, Any] = {
            "name": model.name,
            "backend": model.backend,
            "match_patterns": model.match_patterns,
            "capabilities": self._serialize_capabilities(model.capabilities),
        }
        if model.tested:
            data["tested"] = model.tested
        if model.notes:
            data["notes"] = model.notes
        if model.sensor_info:
            data["sensor_info"] = model.sensor_info
        return data

    def _serialize_capabilities(self, caps: CameraCapabilities) -> Dict[str, Any]:
        """Serialize capabilities to JSON-friendly dict."""
        data: Dict[str, Any] = {
            "modes": [self._serialize_mode(m) for m in caps.modes],
        }
        if caps.default_record_mode:
            data["default_record"] = self._serialize_mode(caps.default_record_mode)
        if caps.default_preview_mode:
            data["default_preview"] = self._serialize_mode(caps.default_preview_mode)
        if caps.controls:
            data["controls"] = {name: serialize_control(ctrl) for name, ctrl in caps.controls.items()}
        if caps.limits:
            data["limits"] = dict(caps.limits)
        if caps.color_formats:
            data["color_formats"] = list(caps.color_formats)
        return data

    @staticmethod
    def _serialize_mode(mode: CapabilityMode) -> Dict[str, Any]:
        """Serialize a mode to JSON-friendly dict."""
        data: Dict[str, Any] = {
            "size": list(mode.size),
            "fps": mode.fps,
            "pixel_format": mode.pixel_format,
        }
        if mode.controls:
            data["controls"] = dict(mode.controls)
        return data


__all__ = [
    "CameraModelDatabase",
    "CameraModel",
    "ModelLookupResult",
    "DEFAULT_MODELS_PATH",
    "extract_model_name",
    "copy_capabilities",
]
