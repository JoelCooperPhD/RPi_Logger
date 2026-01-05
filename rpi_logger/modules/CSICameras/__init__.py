"""CSI Cameras module for Raspberry Pi cameras.

This module handles CSI (Camera Serial Interface) cameras connected to
Raspberry Pi boards via the dedicated camera connector. It uses Picamera2
for camera control and capture.
"""

from rpi_logger.modules.CSICameras.main_csicameras import main

__all__ = ["main"]
