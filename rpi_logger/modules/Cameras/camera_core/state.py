"""Runtime data models and helpers for Cameras."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

SCHEMA_VERSION = 1


class CapabilitySource(Enum):
    """Where a capability set originated."""

    PROBE = "probe"
    CACHE = "cache"


class RuntimeStatus(Enum):
    """High-level lifecycle state for a camera entry."""

    DISCOVERED = "discovered"
    SELECTED = "selected"
    PREVIEWING = "previewing"
    RECORDING = "recording"
    ERROR = "error"


class ControlType(Enum):
    """Type classification for camera controls."""

    INTEGER = "int"
    FLOAT = "float"
    BOOLEAN = "bool"
    ENUM = "enum"
    TUPLE = "tuple"
    UNKNOWN = "unknown"


@dataclass(slots=True, frozen=True)
class CameraId:
    """Stable identifier for a camera device."""

    backend: str  # usb | picam
    stable_id: str  # serial or connector+sensor id
    friendly_name: Optional[str] = None
    dev_path: Optional[str] = None  # e.g., /dev/video0 for USB

    @property
    def key(self) -> str:
        """Return a canonical string key for dict usage."""

        return f"{self.backend}:{self.stable_id}"


@dataclass(slots=True)
class CameraDescriptor:
    """Observed hardware descriptor for a camera."""

    camera_id: CameraId
    hw_model: Optional[str] = None
    location_hint: Optional[str] = None
    seen_at: Optional[float] = None  # monotonic timestamp (ms)


@dataclass(slots=True, frozen=True)
class ControlInfo:
    """Metadata for a single camera control."""

    name: str
    control_type: ControlType
    current_value: Any = None
    min_value: Optional[Any] = None
    max_value: Optional[Any] = None
    default_value: Optional[Any] = None
    step: Optional[float] = None
    options: Optional[List[Any]] = None  # For enum types
    read_only: bool = False
    backend_id: Optional[Any] = None  # cv2.CAP_PROP_* or picam key


@dataclass(slots=True, frozen=True)
class CapabilityMode:
    """Normalized capability entry."""

    size: Tuple[int, int]
    fps: float
    pixel_format: str
    controls: Dict[str, Any] = field(default_factory=dict)

    @property
    def width(self) -> int:
        return self.size[0]

    @property
    def height(self) -> int:
        return self.size[1]

    def signature(self) -> Tuple[int, int, float, str]:
        """Unique signature used for dedupe/lookup."""

        return (self.width, self.height, float(self.fps), self.pixel_format.lower())


@dataclass(slots=True)
class CameraCapabilities:
    """Collection of capability modes plus defaults and provenance."""

    modes: List[CapabilityMode] = field(default_factory=list)
    default_preview_mode: Optional[CapabilityMode] = None
    default_record_mode: Optional[CapabilityMode] = None
    timestamp_ms: float = 0.0
    source: CapabilitySource = CapabilitySource.PROBE
    limits: Dict[str, Any] = field(default_factory=dict)
    color_formats: List[str] = field(default_factory=list)
    controls: Dict[str, ControlInfo] = field(default_factory=dict)  # Camera-level controls

    def dedupe(self) -> None:
        """Remove duplicate modes while preserving order (first wins)."""

        seen: set[Tuple[int, int, float, str]] = set()
        unique: list[CapabilityMode] = []
        for mode in self.modes:
            sig = mode.signature()
            if sig in seen:
                continue
            seen.add(sig)
            unique.append(mode)
        self.modes = unique

    def find_matching(self, target: CapabilityMode) -> Optional[CapabilityMode]:
        sig = target.signature()
        for mode in self.modes:
            if mode.signature() == sig:
                return mode
        return None


@dataclass(slots=True, frozen=True)
class ModeRequest:
    """User or policy requested mode attributes."""

    size: Optional[Tuple[int, int]] = None
    fps: Optional[float] = None
    keep_every: Optional[int] = None
    pixel_format: Optional[str] = None
    overlay: bool = True
    color_convert: bool = True


@dataclass(slots=True)
class ModeSelection:
    """Resolved mode selection including runtime flags."""

    mode: CapabilityMode
    target_fps: Optional[float] = None
    keep_every: Optional[int] = None
    overlay: bool = True
    color_convert: bool = True


@dataclass(slots=True)
class SelectedConfigs:
    """Preview + record selections for a camera."""

    preview: ModeSelection
    record: ModeSelection
    storage_profile: Optional[str] = None


@dataclass(slots=True)
class CameraRuntimeState:
    """Current runtime view of a camera."""

    descriptor: CameraDescriptor
    capabilities: Optional[CameraCapabilities] = None
    selected_configs: Optional[SelectedConfigs] = None
    status: RuntimeStatus = RuntimeStatus.DISCOVERED
    tasks: Dict[str, Any] = field(default_factory=dict)  # task handles/ids
    metrics: Dict[str, Any] = field(default_factory=dict)
    last_error: Optional[str] = None


# ---------------------------------------------------------------------------
# Serialization helpers (used by known_cameras cache)


def serialize_camera_state(state: CameraRuntimeState) -> Dict[str, Any]:
    """Serialize runtime state to a JSON-friendly dict."""

    payload: Dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "descriptor": serialize_descriptor(state.descriptor),
        "status": state.status.value,
    }
    if state.capabilities:
        payload["capabilities"] = serialize_capabilities(state.capabilities)
    if state.selected_configs:
        payload["selected_configs"] = serialize_selected_configs(state.selected_configs)
    if state.last_error:
        payload["last_error"] = state.last_error
    return payload


def deserialize_camera_state(data: Dict[str, Any]) -> Optional[CameraRuntimeState]:
    """Inverse of :func:`serialize_camera_state` with validation."""

    if not isinstance(data, dict):
        return None
    descriptor_data = data.get("descriptor")
    descriptor = deserialize_descriptor(descriptor_data)
    if not descriptor:
        return None

    capabilities = deserialize_capabilities(data.get("capabilities"))
    selected = deserialize_selected_configs(data.get("selected_configs"))
    if capabilities and selected:
        _align_selected_modes(capabilities, selected)

    status_raw = data.get("status", RuntimeStatus.DISCOVERED.value)
    status = _safe_status(status_raw)

    state = CameraRuntimeState(
        descriptor=descriptor,
        capabilities=capabilities,
        selected_configs=selected,
        status=status,
        last_error=data.get("last_error"),
    )
    return state


def serialize_descriptor(descriptor: CameraDescriptor) -> Dict[str, Any]:
    return {
        "camera_id": serialize_camera_id(descriptor.camera_id),
        "hw_model": descriptor.hw_model,
        "location_hint": descriptor.location_hint,
        "seen_at": descriptor.seen_at,
    }


def deserialize_descriptor(data: Any) -> Optional[CameraDescriptor]:
    if not isinstance(data, dict):
        return None
    camera_id = deserialize_camera_id(data.get("camera_id"))
    if not camera_id:
        return None
    return CameraDescriptor(
        camera_id=camera_id,
        hw_model=data.get("hw_model"),
        location_hint=data.get("location_hint"),
        seen_at=data.get("seen_at"),
    )


def serialize_camera_id(camera_id: CameraId) -> Dict[str, Any]:
    return asdict(camera_id)


def deserialize_camera_id(data: Any) -> Optional[CameraId]:
    if not isinstance(data, dict):
        return None
    try:
        return CameraId(
            backend=str(data["backend"]),
            stable_id=str(data["stable_id"]),
            friendly_name=data.get("friendly_name"),
            dev_path=data.get("dev_path"),
        )
    except Exception:
        return None


def serialize_capabilities(capabilities: CameraCapabilities) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "modes": [serialize_mode(mode) for mode in capabilities.modes],
        "default_preview_mode": serialize_mode(capabilities.default_preview_mode) if capabilities.default_preview_mode else None,
        "default_record_mode": serialize_mode(capabilities.default_record_mode) if capabilities.default_record_mode else None,
        "timestamp_ms": capabilities.timestamp_ms,
        "source": capabilities.source.value,
        "limits": dict(capabilities.limits),
        "color_formats": list(capabilities.color_formats),
    }
    if capabilities.controls:
        data["controls"] = {name: serialize_control(ctrl) for name, ctrl in capabilities.controls.items()}
    return data


def deserialize_capabilities(data: Any) -> Optional[CameraCapabilities]:
    if not isinstance(data, dict):
        return None
    modes_raw = data.get("modes") or []
    modes: list[CapabilityMode] = []
    for raw in modes_raw:
        mode = deserialize_mode(raw)
        if mode:
            if not _contains_mode(modes, mode):
                modes.append(mode)

    # Deserialize controls
    controls: Dict[str, ControlInfo] = {}
    for name, ctrl_data in (data.get("controls") or {}).items():
        ctrl = deserialize_control(ctrl_data)
        if ctrl:
            controls[name] = ctrl

    capabilities = CameraCapabilities(
        modes=modes,
        default_preview_mode=deserialize_mode(data.get("default_preview_mode")),
        default_record_mode=deserialize_mode(data.get("default_record_mode")),
        timestamp_ms=float(data.get("timestamp_ms") or 0.0),
        source=_safe_capability_source(data.get("source")),
        limits=dict(data.get("limits") or {}),
        color_formats=list(data.get("color_formats") or []),
        controls=controls,
    )
    capabilities.dedupe()
    return capabilities


def serialize_mode(mode: Optional[CapabilityMode]) -> Optional[Dict[str, Any]]:
    if not mode:
        return None
    return {
        "size": list(mode.size),
        "fps": mode.fps,
        "pixel_format": mode.pixel_format,
        "controls": dict(mode.controls),
    }


def deserialize_mode(data: Any) -> Optional[CapabilityMode]:
    if not data or not isinstance(data, dict):
        return None
    size_raw = data.get("size")
    try:
        width, height = _parse_resolution(size_raw)
        fps = float(data.get("fps"))
        pixel_format = str(data.get("pixel_format"))
    except Exception:
        return None
    controls = data.get("controls") or {}
    if not isinstance(controls, dict):
        controls = {}
    return CapabilityMode(size=(width, height), fps=fps, pixel_format=pixel_format, controls=controls)


def serialize_control(ctrl: ControlInfo) -> Dict[str, Any]:
    """Serialize a ControlInfo to JSON-friendly dict."""
    data: Dict[str, Any] = {
        "name": ctrl.name,
        "type": ctrl.control_type.value,
    }
    if ctrl.current_value is not None:
        data["current"] = ctrl.current_value
    if ctrl.min_value is not None:
        data["min"] = ctrl.min_value
    if ctrl.max_value is not None:
        data["max"] = ctrl.max_value
    if ctrl.default_value is not None:
        data["default"] = ctrl.default_value
    if ctrl.step is not None:
        data["step"] = ctrl.step
    if ctrl.options is not None:
        data["options"] = ctrl.options
    if ctrl.read_only:
        data["read_only"] = True
    if ctrl.backend_id is not None:
        data["backend_id"] = ctrl.backend_id
    return data


def deserialize_control(data: Any) -> Optional[ControlInfo]:
    """Deserialize a ControlInfo from JSON data."""
    if not data or not isinstance(data, dict):
        return None
    try:
        name = data.get("name", "")
        type_str = data.get("type", "unknown")
        try:
            control_type = ControlType(type_str)
        except ValueError:
            control_type = ControlType.UNKNOWN
        return ControlInfo(
            name=name,
            control_type=control_type,
            current_value=data.get("current"),
            min_value=data.get("min"),
            max_value=data.get("max"),
            default_value=data.get("default"),
            step=data.get("step"),
            options=data.get("options"),
            read_only=bool(data.get("read_only", False)),
            backend_id=data.get("backend_id"),
        )
    except Exception:
        return None


def serialize_selected_configs(configs: SelectedConfigs) -> Dict[str, Any]:
    return {
        "preview": serialize_mode_selection(configs.preview),
        "record": serialize_mode_selection(configs.record),
        "storage_profile": configs.storage_profile,
    }


def deserialize_selected_configs(data: Any) -> Optional[SelectedConfigs]:
    if not data or not isinstance(data, dict):
        return None
    preview = deserialize_mode_selection(data.get("preview"))
    record = deserialize_mode_selection(data.get("record"))
    if not preview or not record:
        return None
    return SelectedConfigs(preview=preview, record=record, storage_profile=data.get("storage_profile"))


def serialize_mode_selection(selection: ModeSelection) -> Dict[str, Any]:
    return {
        "mode": serialize_mode(selection.mode),
        "target_fps": selection.target_fps,
        "keep_every": selection.keep_every,
        "overlay": selection.overlay,
        "color_convert": selection.color_convert,
    }


def deserialize_mode_selection(data: Any) -> Optional[ModeSelection]:
    if not data or not isinstance(data, dict):
        return None
    mode = deserialize_mode(data.get("mode"))
    if not mode:
        return None
    return ModeSelection(
        mode=mode,
        target_fps=data.get("target_fps"),
        keep_every=data.get("keep_every"),
        overlay=bool(data.get("overlay", True)),
        color_convert=bool(data.get("color_convert", True)),
    )


# ---------------------------------------------------------------------------
# Internal helpers


def _contains_mode(collection: Sequence[CapabilityMode], candidate: CapabilityMode) -> bool:
    sig = candidate.signature()
    for item in collection:
        if item.signature() == sig:
            return True
    return False


def _parse_resolution(raw: Any) -> Tuple[int, int]:
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        return int(raw[0]), int(raw[1])
    if isinstance(raw, str) and "x" in raw:
        width, height = raw.lower().split("x", 1)
        return int(width), int(height)
    raise ValueError("Invalid resolution format")


def _safe_status(raw: Any) -> RuntimeStatus:
    try:
        return RuntimeStatus(str(raw))
    except Exception:
        return RuntimeStatus.DISCOVERED


def _safe_capability_source(raw: Any) -> CapabilitySource:
    try:
        return CapabilitySource(str(raw))
    except Exception:
        return CapabilitySource.PROBE


def _align_selected_modes(capabilities: CameraCapabilities, selected: SelectedConfigs) -> None:
    """Ensure selected modes reference objects contained in capabilities."""

    preview_match = capabilities.find_matching(selected.preview.mode)
    if preview_match:
        selected.preview.mode = preview_match
    else:
        capabilities.modes.append(selected.preview.mode)

    record_match = capabilities.find_matching(selected.record.mode)
    if record_match:
        selected.record.mode = record_match
    else:
        capabilities.modes.append(selected.record.mode)
    capabilities.dedupe()
