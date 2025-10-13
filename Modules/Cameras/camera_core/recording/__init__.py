#!/usr/bin/env python3
"""
Recording subsystem for camera module.

This package handles all recording-related functionality:
- Hardware H.264 encoding
- CSV timing logs
- Frame overlays
- Video remuxing
"""

from .manager import CameraRecordingManager

__all__ = ['CameraRecordingManager']
