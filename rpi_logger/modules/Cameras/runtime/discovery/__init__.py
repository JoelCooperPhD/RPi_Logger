"""Capability utilities for Cameras.

Device discovery is centralized in the main logger via usb_camera_scanner.py
and csi_scanner.py. This module only contains capability-building utilities
used by backends after a device is assigned.
"""

from .capabilities import build_capabilities, normalize_modes, select_default_preview, select_default_record

__all__ = [
    "build_capabilities",
    "normalize_modes",
    "select_default_preview",
    "select_default_record",
]
