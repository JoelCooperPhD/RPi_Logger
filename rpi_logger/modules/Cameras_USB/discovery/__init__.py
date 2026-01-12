from .usb_scanner import (
    USBVideoDevice,
    # Note: scan_usb_cameras, get_device_by_path, get_device_by_stable_id are
    # deprecated - the core DeviceSystem handles discovery, modules receive
    # device info via assign_device command
)
from .audio_matcher import (
    match_audio_to_camera,
    list_all_audio_devices,
)
from .prober import (
    probe_camera_modes,
    verify_camera_accessible,
)
from .platform_scanner import (
    VideoDevice,
    AudioDevice,
    get_scanner,
)
from .camera_knowledge import (
    CameraKnowledge,
    CameraProfile,
    RESOLUTION_LIMITS,
)

__all__ = [
    "USBVideoDevice",
    "match_audio_to_camera",
    "list_all_audio_devices",
    "probe_camera_modes",
    "verify_camera_accessible",
    "VideoDevice",
    "AudioDevice",
    "get_scanner",
    "CameraKnowledge",
    "CameraProfile",
    "RESOLUTION_LIMITS",
]
