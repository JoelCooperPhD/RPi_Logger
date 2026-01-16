"""
macOS camera discovery backend.

Discovers cameras on macOS using AVFoundation for device enumeration and
OpenCV for capture verification. AVFoundation provides actual device names
like "FaceTime HD Camera" instead of generic "USB Camera 0".

Uses IOKit for USB VID:PID extraction to match webcam video interfaces
with their audio siblings (built-in microphones).

Requires PyObjC (pyobjc-framework-AVFoundation) for AVFoundation access.
Falls back to generic names if PyObjC is not available.

Copyright (C) 2024-2025 Red Scientific

Licensed under the Apache License, Version 2.0
"""

from typing import Optional

from rpi_logger.core.logging_utils import get_module_logger

from .base import AudioSiblingInfo, DiscoveredUSBCamera

logger = get_module_logger("MacOSCameraBackend")

# Try to import IOKit utilities for VID:PID extraction and built-in matching
try:
    from .iokit_utils import (
        find_audio_device_with_vid_pid,
        find_builtin_audio_sibling,
        get_vid_pid_for_camera_name,
    )
    IOKIT_AVAILABLE = True
except ImportError:
    IOKIT_AVAILABLE = False

# Try to import OpenCV
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logger.warning("cv2 not available - camera discovery disabled")


class MacOSCameraBackend:
    """macOS camera discovery using AVFoundation and OpenCV.

    This backend uses AVFoundation (via PyObjC) to get actual device names
    and unique identifiers, then verifies camera accessibility with OpenCV.

    AVFoundation provides:
    - localizedName(): Human-readable name (e.g., "FaceTime HD Camera")
    - uniqueID(): Persistent identifier that survives reboots
    - modelID(): Hardware model identifier

    The enumeration order from AVFoundation matches OpenCV's camera indices,
    allowing us to correlate the rich device info with OpenCV capture.
    """

    def discover_cameras(self, max_devices: int = 16) -> list[DiscoveredUSBCamera]:
        """Discover cameras on macOS using AVFoundation + OpenCV.

        Also attempts to find audio siblings (built-in microphones) for each
        camera by matching USB VID:PID using IOKit.
        """
        if not CV2_AVAILABLE:
            logger.debug("OpenCV not available, skipping camera discovery")
            return []

        cameras: list[DiscoveredUSBCamera] = []

        # Try to get device info from AVFoundation for better names
        av_devices = self._get_avfoundation_devices()

        for index in range(max_devices):
            cap = cv2.VideoCapture(index)
            if cap and cap.isOpened():
                cap.release()

                # Use AVFoundation info if available, otherwise generic names
                if av_devices and index < len(av_devices):
                    name, _, model_id = av_devices[index]  # unique_id not used
                    friendly_name = name
                    hw_model = model_id or name
                else:
                    friendly_name = f"USB Camera {index}"
                    hw_model = "USB Camera"

                # Try to find audio sibling using IOKit VID:PID matching
                audio_sibling = None
                vid_pid = None
                if IOKIT_AVAILABLE:
                    audio_sibling, vid_pid = self._find_audio_sibling(friendly_name)

                # Create human-readable stable_id from camera name + VID:PID
                # e.g., "facetime_hd_camera" or "logitech_c920_046d_0825"
                stable_id = self._create_stable_id(friendly_name, vid_pid, index)

                cameras.append(DiscoveredUSBCamera(
                    device_id=f"usb:{index}",
                    stable_id=stable_id,
                    dev_path=str(index),
                    friendly_name=friendly_name,
                    hw_model=hw_model,
                    location_hint=vid_pid,
                    usb_bus_path=vid_pid,
                    audio_sibling=audio_sibling,
                    camera_index=index,
                ))

            else:
                if cap:
                    cap.release()
                break

        return cameras

    def _get_avfoundation_devices(self) -> Optional[list[tuple[str, str, str]]]:
        """Get camera info from AVFoundation (macOS only).

        AVFoundation provides actual device names, unique IDs, and model info
        that OpenCV cannot access directly.

        Returns:
            List of (name, unique_id, model_id) tuples in enumeration order,
            or None if AVFoundation/PyObjC is not available.
        """
        try:
            from AVFoundation import AVCaptureDevice, AVMediaTypeVideo

            devices = AVCaptureDevice.devicesWithMediaType_(AVMediaTypeVideo)
            result = []
            for device in devices:
                name = device.localizedName() or "Unknown Camera"
                unique_id = device.uniqueID() or ""
                model_id = device.modelID() or ""
                result.append((name, unique_id, model_id))

            return result if result else None

        except ImportError:
            return None
        except Exception as e:
            logger.warning("Failed to enumerate AVFoundation devices: %s", e)
            return None

    def _find_audio_sibling(
        self, camera_name: str
    ) -> tuple[Optional[AudioSiblingInfo], Optional[str]]:
        """Find an audio sibling for a camera.

        Tries multiple strategies:
        1. VID:PID matching for USB webcams (most reliable for external cameras)
        2. Name-based matching for built-in cameras (FaceTime, iSight)

        Args:
            camera_name: Camera name from AVFoundation (e.g., "FaceTime HD Camera")

        Returns:
            Tuple of (AudioSiblingInfo, vid_pid_string) if found,
            or (None, None) if no audio sibling found.
        """
        if not IOKIT_AVAILABLE:
            return None, None

        try:
            # Strategy 1: VID:PID matching for USB webcams
            vid_pid = get_vid_pid_for_camera_name(camera_name)
            if vid_pid:
                audio_info = find_audio_device_with_vid_pid(vid_pid)
                if audio_info:
                    audio_sibling = AudioSiblingInfo(
                        sounddevice_index=audio_info["sounddevice_index"],
                        alsa_card=None,  # Not applicable on macOS
                        channels=audio_info.get("channels", 2),
                        sample_rate=audio_info.get("sample_rate", 48000.0),
                        name=audio_info.get("name", ""),
                    )
                    return audio_sibling, vid_pid

            # Strategy 2: Built-in camera matching (FaceTime, iSight)
            # On Apple Silicon, built-in cameras aren't USB devices
            builtin_audio = find_builtin_audio_sibling(camera_name)
            if builtin_audio:
                audio_sibling = AudioSiblingInfo(
                    sounddevice_index=builtin_audio["sounddevice_index"],
                    alsa_card=None,
                    channels=builtin_audio.get("channels", 1),
                    sample_rate=builtin_audio.get("sample_rate", 48000.0),
                    name=builtin_audio.get("name", ""),
                )
                return audio_sibling, vid_pid

            return None, vid_pid

        except Exception as e:
            logger.warning("Audio sibling detection failed for '%s': %s", camera_name, e)
            return None, None

    def _create_stable_id(
        self, friendly_name: str, vid_pid: Optional[str], index: int
    ) -> str:
        """Create a human-readable stable ID for folder naming.

        Creates IDs like:
        - "facetime_hd_camera" (built-in camera)
        - "logitech_c920_046d_0825" (USB webcam with VID:PID)
        - "usb_camera_0" (fallback)

        Args:
            friendly_name: Camera name from AVFoundation
            vid_pid: VID:PID string if available (e.g., "046d:0825")
            index: Camera index as fallback

        Returns:
            Sanitized string suitable for directory names.
        """
        # Sanitize the friendly name
        safe_name = friendly_name.lower()
        # Replace special characters with underscores
        for char in " -():,./'\"":
            safe_name = safe_name.replace(char, "_")
        # Remove consecutive underscores
        while "__" in safe_name:
            safe_name = safe_name.replace("__", "_")
        safe_name = safe_name.strip("_")

        # Append VID:PID if available (for USB cameras)
        if vid_pid:
            safe_vid_pid = vid_pid.replace(":", "_")
            return f"{safe_name}_{safe_vid_pid}"

        # For built-in cameras without VID:PID, just use the name
        if safe_name:
            return safe_name

        # Fallback
        return f"camera_{index}"


__all__ = ["MacOSCameraBackend"]
