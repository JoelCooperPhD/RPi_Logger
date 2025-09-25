#!/usr/bin/env python3
"""
Device Manager for Gaze Tracker
Handles connection to and management of eye tracker device.
"""

import logging
from typing import Optional
from pupil_labs.realtime_api.discovery import discover_devices
from pupil_labs.realtime_api.device import Device

logger = logging.getLogger(__name__)


class DeviceManager:
    """Manages connection to eye tracker device"""

    def __init__(self):
        self.device: Optional[Device] = None
        self.device_ip: Optional[str] = None
        self.device_port: Optional[int] = None

    async def connect(self) -> bool:
        """Connect to eye tracker using async discovery"""
        logger.info("Searching for eye tracker device...")

        try:
            # Discover devices
            async for device_info in discover_devices(timeout_seconds=5.0):
                logger.info(f"Found device: {device_info.name}")

                # Store connection info
                self.device_ip = device_info.addresses[0]
                self.device_port = device_info.port

                # Create device for control operations
                self.device = Device.from_discovered_device(device_info)

                logger.info(f"Connected to device at {self.device_ip}:{self.device_port}")
                return True

            logger.error("No devices found")
            return False

        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False

    def get_rtsp_urls(self) -> tuple[str, str]:
        """Get RTSP URLs for video and gaze streaming"""
        if not self.device_ip:
            raise RuntimeError("No device connected")

        base_port = 8086  # RTSP port is typically different from HTTP port
        video_url = f"rtsp://{self.device_ip}:{base_port}/?camera=world"
        gaze_url = f"rtsp://{self.device_ip}:{base_port}/?camera=gaze"

        return video_url, gaze_url

    @property
    def is_connected(self) -> bool:
        """Check if device is connected"""
        return self.device is not None and self.device_ip is not None

    async def cleanup(self):
        """Clean up device connection"""
        if self.device:
            try:
                await self.device.close()
            except:
                pass
            finally:
                self.device = None
                self.device_ip = None
                self.device_port = None