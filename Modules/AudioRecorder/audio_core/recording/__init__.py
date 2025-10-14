#!/usr/bin/env python3
"""
Recording subsystem for audio module.

This package handles all recording-related functionality:
- WAV file encoding
- Audio buffer management
- File I/O
"""

from .manager import AudioRecordingManager

__all__ = ['AudioRecordingManager']
