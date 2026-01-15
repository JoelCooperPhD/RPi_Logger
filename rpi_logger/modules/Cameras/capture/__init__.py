"""Capture module - video and audio acquisition."""

from .frame import CapturedFrame, AudioChunk
from .ring_buffer import FrameRingBuffer, AudioRingBuffer
from .camera import USBCamera
from .audio import AudioCapture

__all__ = [
    "CapturedFrame",
    "AudioChunk",
    "FrameRingBuffer",
    "AudioRingBuffer",
    "USBCamera",
    "AudioCapture",
]
