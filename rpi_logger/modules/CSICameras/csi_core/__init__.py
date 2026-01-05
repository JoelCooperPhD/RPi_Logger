"""CSI camera core functionality.

This package provides the capture abstraction and backends for
Raspberry Pi CSI cameras using Picamera2.
"""

# Re-export shared types from base
from rpi_logger.modules.base.camera_types import (
    # Enums
    CapabilitySource,
    RuntimeStatus,
    ControlType,
    # Data classes
    CameraId,
    CameraDescriptor,
    ControlInfo,
    CapabilityMode,
    CameraCapabilities,
    ModeRequest,
    ModeSelection,
    SelectedConfigs,
    CameraRuntimeState,
    # Capture abstraction
    CaptureFrame,
    CaptureHandle,
    # Serialization
    serialize_camera_state,
    deserialize_camera_state,
    serialize_camera_id,
    deserialize_camera_id,
    serialize_capabilities,
    deserialize_capabilities,
)

# Re-export encoder from base
from rpi_logger.modules.base.camera_encoder import Encoder

# Re-export capabilities from base
from rpi_logger.modules.base.camera_capabilities import (
    build_capabilities,
    normalize_modes,
    select_default_preview,
    select_default_record,
)

# CSI-specific capture
from rpi_logger.modules.CSICameras.csi_core.capture import PicamCapture

# CSI-specific preview utilities
from rpi_logger.modules.CSICameras.csi_core.preview import yuv420_to_bgr

__all__ = [
    # Enums
    "CapabilitySource",
    "RuntimeStatus",
    "ControlType",
    # Data classes
    "CameraId",
    "CameraDescriptor",
    "ControlInfo",
    "CapabilityMode",
    "CameraCapabilities",
    "ModeRequest",
    "ModeSelection",
    "SelectedConfigs",
    "CameraRuntimeState",
    # Capture
    "CaptureFrame",
    "CaptureHandle",
    "PicamCapture",
    # Encoding
    "Encoder",
    # Capabilities
    "build_capabilities",
    "normalize_modes",
    "select_default_preview",
    "select_default_record",
    # Serialization
    "serialize_camera_state",
    "deserialize_camera_state",
    "serialize_camera_id",
    "deserialize_camera_id",
    "serialize_capabilities",
    "deserialize_capabilities",
    # Preview
    "yuv420_to_bgr",
]
