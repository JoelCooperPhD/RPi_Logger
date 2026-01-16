"""
Windows camera discovery backend.

Discovers cameras on Windows using OpenCV enumeration with WMI for device
names and VID:PID extraction. Uses VID:PID matching to find audio siblings
(built-in microphones on USB webcams).

Copyright (C) 2024-2025 Red Scientific

Licensed under the Apache License, Version 2.0
"""

import csv
import io
import os
import re
import subprocess
import sys
from typing import Optional

from rpi_logger.core.logging_utils import get_module_logger

from .base import AudioSiblingInfo, DiscoveredUSBCamera

logger = get_module_logger("WindowsCameraBackend")

# Windows-specific subprocess flag to hide console window
_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# Disable MSMF hardware transforms on Windows to fix slow camera initialization.
# Must be set BEFORE importing cv2. See: https://github.com/opencv/opencv/issues/17687
if sys.platform == "win32":
    os.environ.setdefault("OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS", "0")

# Try to import OpenCV
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logger.warning("cv2 not available - camera discovery disabled")


# Try to import sounddevice for audio sibling detection
try:
    import sounddevice as sd
    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    SOUNDDEVICE_AVAILABLE = False
    logger.debug("sounddevice not available - audio sibling detection disabled")


class WindowsCameraBackend:
    """Windows camera discovery using OpenCV with WMI enrichment.

    This backend uses OpenCV enumeration for camera discovery, enriched
    with WMI (Windows Management Instrumentation) to get:
    - Actual device names instead of generic "USB Camera N"
    - VID:PID identifiers for audio sibling matching
    """

    def discover_cameras(self, max_devices: int = 4) -> list[DiscoveredUSBCamera]:
        """Discover cameras on Windows using OpenCV enumeration with WMI enrichment."""
        if not CV2_AVAILABLE:
            logger.debug("OpenCV not available, skipping camera discovery")
            return []

        cameras: list[DiscoveredUSBCamera] = []

        # Get WMI device info for better names and VID:PID
        wmi_video_devices = self._get_wmi_video_devices()
        wmi_audio_devices = self._get_wmi_audio_devices() if SOUNDDEVICE_AVAILABLE else []

        # Track which WMI devices have been matched to avoid duplicates
        used_wmi_indices: set[int] = set()

        for index in range(max_devices):
            # Use DirectShow backend to avoid MSMF/Orbbec issues
            cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
            if cap and cap.isOpened():
                cap.release()

                # Correlate OpenCV index to WMI device
                wmi_info = self._correlate_opencv_to_wmi(
                    index, wmi_video_devices, used_wmi_indices
                )
                vid_pid = wmi_info.get("vid_pid", "") if wmi_info else ""
                friendly_name = (
                    wmi_info.get("name", f"USB Camera {index}")
                    if wmi_info
                    else f"USB Camera {index}"
                )

                # Find audio sibling by VID:PID first
                audio_sibling = None
                if vid_pid and SOUNDDEVICE_AVAILABLE:
                    audio_sibling = self._find_audio_sibling_by_vid_pid(
                        vid_pid, wmi_audio_devices
                    )

                # Fallback: try name-based matching if VID:PID failed
                if not audio_sibling and SOUNDDEVICE_AVAILABLE:
                    audio_sibling = self._find_audio_sibling_by_name(
                        friendly_name, wmi_audio_devices
                    )

                cameras.append(DiscoveredUSBCamera(
                    device_id=f"usb:{index}",
                    stable_id=vid_pid or str(index),
                    dev_path=str(index),
                    friendly_name=friendly_name,
                    hw_model=friendly_name,
                    location_hint=vid_pid or None,
                    usb_bus_path=vid_pid or None,
                    audio_sibling=audio_sibling,
                    camera_index=index,
                ))

            else:
                if cap:
                    cap.release()
                break

        return cameras

    def _get_wmi_video_devices(self) -> list[dict]:
        """Query for USB video devices with VID:PID.

        Uses PowerShell Get-PnpDevice (preferred) with wmic fallback for older Windows.
        Returns list of dicts with 'name', 'vid_pid', and 'device_id' keys.
        """
        # Try PowerShell first (works on Windows 10+, wmic is deprecated)
        devices = self._query_video_devices_powershell()
        if devices:
            return devices

        # Fall back to wmic for older Windows
        devices = self._query_video_devices_wmic()
        return devices

    def _query_video_devices_powershell(self) -> list[dict]:
        """Query video devices using PowerShell Get-PnpDevice."""
        try:
            # Query Camera and Image classes (covers all webcam types)
            result = subprocess.run(
                [
                    "powershell", "-NoProfile", "-Command",
                    "Get-PnpDevice -Class Camera,Image -Status OK 2>$null | "
                    "Select-Object InstanceId,FriendlyName | "
                    "ConvertTo-Csv -NoTypeInformation"
                ],
                capture_output=True, text=True, timeout=10, creationflags=_SUBPROCESS_FLAGS
            )
            if result.returncode == 0 and result.stdout.strip():
                devices = self._parse_powershell_csv(result.stdout)
                if devices:
                    return devices
        except FileNotFoundError:
            pass  # PowerShell not available, will try wmic fallback
        except subprocess.TimeoutExpired:
            logger.warning("PowerShell video device query timed out")
        except Exception:
            pass  # Silent fallback to wmic
        return []

    def _query_video_devices_wmic(self) -> list[dict]:
        """Query video devices using wmic (fallback for older Windows)."""
        try:
            # Use PNPClass instead of Service for broader coverage
            result = subprocess.run(
                [
                    "wmic", "path", "Win32_PnPEntity", "where",
                    "(PNPClass='Camera' OR PNPClass='Image')",
                    "get", "DeviceID,Caption", "/format:csv"
                ],
                capture_output=True, text=True, timeout=10, creationflags=_SUBPROCESS_FLAGS
            )
            if result.returncode == 0:
                devices = self._parse_wmi_csv(result.stdout)
                if devices:
                    return devices
        except FileNotFoundError:
            pass  # wmic not available
        except subprocess.TimeoutExpired:
            logger.warning("wmic video device query timed out")
        except Exception:
            pass
        return []

    def _get_wmi_audio_devices(self) -> list[dict]:
        """Query for USB audio devices with VID:PID.

        Uses PowerShell Get-PnpDevice (preferred) with wmic fallback for older Windows.
        Returns list of dicts with 'name', 'vid_pid', 'device_id', and 'sounddevice_index' keys.
        """
        # Try PowerShell first
        devices = self._query_audio_devices_powershell()
        if not devices:
            # Fall back to wmic
            devices = self._query_audio_devices_wmic()

        # Correlate with sounddevice to get indices
        if devices and SOUNDDEVICE_AVAILABLE:
            self._correlate_audio_with_sounddevice(devices)

        return devices

    def _query_audio_devices_powershell(self) -> list[dict]:
        """Query USB audio devices using PowerShell Get-PnpDevice."""
        try:
            # Query MEDIA class devices with USB VID in InstanceId
            result = subprocess.run(
                [
                    "powershell", "-NoProfile", "-Command",
                    "Get-PnpDevice -Class MEDIA -Status OK 2>$null | "
                    "Where-Object { $_.InstanceId -like '*VID_*' } | "
                    "Select-Object InstanceId,FriendlyName | "
                    "ConvertTo-Csv -NoTypeInformation"
                ],
                capture_output=True, text=True, timeout=10, creationflags=_SUBPROCESS_FLAGS
            )
            if result.returncode == 0 and result.stdout.strip():
                devices = self._parse_powershell_csv(result.stdout)
                if devices:
                    return devices
        except FileNotFoundError:
            pass  # PowerShell not available, will try wmic fallback
        except subprocess.TimeoutExpired:
            logger.warning("PowerShell audio device query timed out")
        except Exception:
            pass  # Silent fallback to wmic
        return []

    def _query_audio_devices_wmic(self) -> list[dict]:
        """Query USB audio devices using wmic (fallback for older Windows)."""
        try:
            # Use PNPClass='MEDIA' and filter for USB devices
            result = subprocess.run(
                [
                    "wmic", "path", "Win32_PnPEntity", "where",
                    "PNPClass='MEDIA'",
                    "get", "DeviceID,Caption", "/format:csv"
                ],
                capture_output=True, text=True, timeout=10, creationflags=_SUBPROCESS_FLAGS
            )
            if result.returncode == 0:
                # _parse_wmi_csv already filters for USB devices (requires VID:PID)
                devices = self._parse_wmi_csv(result.stdout)
                if devices:
                    return devices
        except FileNotFoundError:
            pass  # wmic not available
        except subprocess.TimeoutExpired:
            logger.warning("wmic audio device query timed out")
        except Exception:
            pass
        return []

    def _correlate_audio_with_sounddevice(self, devices: list[dict]) -> None:
        """Correlate PnP audio devices with sounddevice indices."""
        if not SOUNDDEVICE_AVAILABLE:
            return

        try:
            sd_devices = sd.query_devices()
            input_devices = [
                (i, d) for i, d in enumerate(sd_devices)
                if d.get("max_input_channels", 0) > 0
            ]

            # Try to match devices to sounddevice by name
            for dev in devices:
                dev_name_lower = dev["name"].lower()
                for sd_idx, sd_dev in input_devices:
                    sd_name = sd_dev.get("name", "").lower()
                    # Check if names share keywords (4+ chars)
                    if any(kw in sd_name for kw in dev_name_lower.split() if len(kw) > 3):
                        dev["sounddevice_index"] = sd_idx
                        dev["channels"] = sd_dev.get("max_input_channels", 2)
                        dev["sample_rate"] = sd_dev.get("default_samplerate", 48000.0)
                        break
        except Exception:
            pass  # sounddevice correlation is best-effort

    def _parse_wmi_csv(self, csv_output: str) -> list[dict]:
        """Parse WMI CSV output to extract device info.

        Uses Python's csv module to properly handle quoted fields
        that may contain commas.
        """
        devices = []

        # WMI CSV sometimes has blank lines - clean them up
        lines = csv_output.strip().split("\n")
        clean_output = "\n".join(line for line in lines if line.strip())

        if not clean_output:
            return devices

        try:
            reader = csv.DictReader(io.StringIO(clean_output))
            for row in reader:
                # WMI CSV columns: Node, Caption, DeviceID
                caption = row.get("Caption", "").strip()
                device_id = row.get("DeviceID", "").strip()

                if not device_id:
                    continue

                vid_pid = self._extract_vid_pid(device_id)
                if vid_pid:  # Only include USB devices with valid VID:PID
                    devices.append({
                        "name": caption,
                        "vid_pid": vid_pid,
                        "device_id": device_id
                    })
        except csv.Error as e:
            logger.warning("CSV parsing error: %s", e)
        except Exception:
            pass  # WMI CSV parsing best-effort

        return devices

    def _parse_powershell_csv(self, csv_output: str) -> list[dict]:
        """Parse PowerShell CSV output to extract device info.

        PowerShell ConvertTo-Csv produces simpler output than wmic:
        "InstanceId","FriendlyName"
        "USB\\VID_046D&PID_0819&MI_00\\...","USB Video Device"
        """
        devices = []

        # Clean up blank lines
        lines = csv_output.strip().split("\n")
        clean_output = "\n".join(line for line in lines if line.strip())

        if not clean_output:
            return devices

        try:
            reader = csv.DictReader(io.StringIO(clean_output))
            for row in reader:
                instance_id = row.get("InstanceId", "").strip()
                friendly_name = row.get("FriendlyName", "").strip()

                if not instance_id:
                    continue

                vid_pid = self._extract_vid_pid(instance_id)
                if vid_pid:  # Only include USB devices with valid VID:PID
                    devices.append({
                        "name": friendly_name,
                        "vid_pid": vid_pid,
                        "device_id": instance_id
                    })
        except csv.Error as e:
            logger.warning("PowerShell CSV parsing error: %s", e)
        except Exception:
            pass  # PowerShell CSV parsing best-effort

        return devices

    def _extract_vid_pid(self, device_id: str) -> str:
        """Extract VID:PID from Windows device ID.

        Format: USB\\VID_046D&PID_0825\\... -> 046d:0825
        """
        match = re.search(r"VID_([0-9A-Fa-f]{4})&PID_([0-9A-Fa-f]{4})", device_id)
        if match:
            return f"{match.group(1).lower()}:{match.group(2).lower()}"
        return ""

    def _find_audio_sibling_by_vid_pid(
        self, vid_pid: str, wmi_audio_devices: list[dict]
    ) -> Optional[AudioSiblingInfo]:
        """Find audio device with matching VID:PID.

        USB webcams with built-in microphones share the same VID:PID
        between their video and audio interfaces.
        """
        for audio_dev in wmi_audio_devices:
            if audio_dev.get("vid_pid") == vid_pid and "sounddevice_index" in audio_dev:
                return AudioSiblingInfo(
                    sounddevice_index=audio_dev["sounddevice_index"],
                    alsa_card=None,  # Not applicable on Windows
                    channels=audio_dev.get("channels", 2),
                    sample_rate=audio_dev.get("sample_rate", 48000.0),
                    name=audio_dev.get("name", ""),
                )
        return None

    def _extract_keywords(self, name: str) -> list[str]:
        """Extract meaningful keywords from device name for matching.

        Extracts brand names, model numbers, and significant words
        that can be used to correlate devices.
        """
        if not name:
            return []

        name_lower = name.lower()
        keywords = []

        # Common webcam brand patterns
        brands = [
            "logitech", "microsoft", "razer", "creative", "elgato",
            "obs", "droidcam", "iriun", "epoccam", "aukey", "anker",
            "papalook", "nexigo", "emeet", "hikvision", "wyze"
        ]
        for brand in brands:
            if brand in name_lower:
                keywords.append(brand)

        # Model numbers (e.g., C920, C930, BRIO, HD1080)
        model_patterns = re.findall(r'[a-z]?\d{3,4}[a-z]?', name_lower)
        keywords.extend(model_patterns)

        # Significant words (4+ chars, excluding common generic terms)
        common = {
            "camera", "webcam", "video", "usb", "hd", "pro", "device",
            "integrated", "capture", "imaging", "stream", "built"
        }
        words = re.findall(r'\b\w{4,}\b', name_lower)
        keywords.extend(w for w in words if w not in common and w not in keywords)

        return keywords

    def _correlate_opencv_to_wmi(
        self,
        opencv_index: int,
        wmi_video_devices: list[dict],
        used_wmi_indices: set[int]
    ) -> Optional[dict]:
        """Correlate an OpenCV camera index to a WMI device.

        Uses name-based matching rather than assuming index order,
        since OpenCV and WMI enumerate devices differently.

        Args:
            opencv_index: The OpenCV camera index
            wmi_video_devices: List of WMI video device info dicts
            used_wmi_indices: Set of WMI indices already matched

        Returns:
            Matching WMI device dict, or None if no match found
        """
        if not wmi_video_devices:
            return None

        # If only one WMI device and one camera, they must match
        unused = [i for i in range(len(wmi_video_devices)) if i not in used_wmi_indices]
        if len(unused) == 1:
            idx = unused[0]
            used_wmi_indices.add(idx)
            return wmi_video_devices[idx]

        # If index matches and hasn't been used, use positional match as fallback
        if opencv_index < len(wmi_video_devices) and opencv_index not in used_wmi_indices:
            used_wmi_indices.add(opencv_index)
            return wmi_video_devices[opencv_index]

        return None

    def _find_audio_sibling_by_name(
        self,
        camera_name: str,
        wmi_audio_devices: list[dict]
    ) -> Optional[AudioSiblingInfo]:
        """Find audio device by name similarity when VID:PID matching fails.

        This is a fallback strategy that looks for audio devices with names
        that share keywords with the camera name (e.g., brand, model).

        Args:
            camera_name: The camera's friendly name
            wmi_audio_devices: List of WMI audio device dicts with sounddevice info

        Returns:
            AudioSiblingInfo if a match is found, None otherwise
        """
        if not camera_name or not SOUNDDEVICE_AVAILABLE:
            return None

        camera_keywords = self._extract_keywords(camera_name)
        if not camera_keywords:
            return None

        best_match = None
        best_score = 0

        for wmi_dev in wmi_audio_devices:
            if "sounddevice_index" not in wmi_dev:
                continue

            audio_name = wmi_dev.get("name", "")
            audio_name_lower = audio_name.lower()

            # Calculate match score based on shared keywords
            score = sum(1 for kw in camera_keywords if kw in audio_name_lower)

            # Boost score for matching brand names
            brands = ["logitech", "microsoft", "razer", "creative", "elgato"]
            for brand in brands:
                if brand in audio_name_lower and brand in camera_name.lower():
                    score += 2

            if score > best_score:
                best_score = score
                best_match = wmi_dev

        # Require at least score of 2 to avoid false positives
        if best_match and best_score >= 2:
            return AudioSiblingInfo(
                sounddevice_index=best_match["sounddevice_index"],
                alsa_card=None,
                channels=best_match.get("channels", 2),
                sample_rate=best_match.get("sample_rate", 48000.0),
                name=best_match.get("name", ""),
            )

        # Last resort: if there's exactly one USB audio device with sounddevice index,
        # and we have exactly one camera, assume they're paired
        candidates = [d for d in wmi_audio_devices if "sounddevice_index" in d]
        if len(candidates) == 1:
            candidate = candidates[0]
            return AudioSiblingInfo(
                sounddevice_index=candidate["sounddevice_index"],
                alsa_card=None,
                channels=candidate.get("channels", 2),
                sample_rate=candidate.get("sample_rate", 48000.0),
                name=candidate.get("name", ""),
            )

        return None


__all__ = ["WindowsCameraBackend"]
