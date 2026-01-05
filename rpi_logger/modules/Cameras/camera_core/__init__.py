"""
Camera core - USB camera capture, encoding, and state management.

This package contains the core USB camera functionality that runs directly
in the module process (no subprocess).
"""
# Import shared types from base module
from rpi_logger.modules.base.camera_types import (
    CameraId,
    CameraDescriptor,
    CameraCapabilities,
    CameraRuntimeState,
    CapabilityMode,
    CapabilitySource,
    ControlInfo,
    ControlType,
    RuntimeStatus,
    ModeRequest,
    ModeSelection,
    SelectedConfigs,
    CaptureHandle,
    CaptureFrame,
    # Serialization
    serialize_camera_state,
    deserialize_camera_state,
    serialize_camera_id,
    deserialize_camera_id,
    serialize_capabilities,
    deserialize_capabilities,
    serialize_control,
    deserialize_control,
)
# Import shared encoder from base module
from rpi_logger.modules.base.camera_encoder import Encoder
# Import USB-specific implementations
from rpi_logger.modules.Cameras.camera_core.capture import USBCapture, open_capture
from rpi_logger.modules.Cameras.camera_core.capabilities import build_capabilities

__all__ = [
    # State
    "CameraId",
    "CameraDescriptor",
    "CameraCapabilities",
    "CameraRuntimeState",
    "CapabilityMode",
    "CapabilitySource",
    "ControlInfo",
    "ControlType",
    "RuntimeStatus",
    "ModeRequest",
    "ModeSelection",
    "SelectedConfigs",
    # Serialization
    "serialize_camera_state",
    "deserialize_camera_state",
    "serialize_camera_id",
    "deserialize_camera_id",
    "serialize_capabilities",
    "deserialize_capabilities",
    "serialize_control",
    "deserialize_control",
    # Capture
    "CaptureHandle",
    "CaptureFrame",
    "USBCapture",
    "open_capture",
    # Encoding
    "Encoder",
    # Capabilities
    "build_capabilities",
]
