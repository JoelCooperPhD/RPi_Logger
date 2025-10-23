
import asyncio
import logging
from typing import Optional
from pupil_labs.realtime_api.discovery import discover_devices
from pupil_labs.realtime_api.device import Device

logger = logging.getLogger(__name__)


class DeviceManager:

    def __init__(self):
        self.device: Optional[Device] = None
        self.device_ip: Optional[str] = None
        self.device_port: Optional[int] = None

    async def connect(self) -> bool:
        logger.info("Searching for eye tracker device...")

        try:
            async for device_info in discover_devices(timeout_seconds=5.0):
                logger.info(f"Found device: {device_info.name}")

                self.device_ip = device_info.addresses[0]
                self.device_port = device_info.port

                self.device = Device.from_discovered_device(device_info)

                logger.info(f"Connected to device at {self.device_ip}:{self.device_port}")
                return True

            logger.error("No devices found")
            return False

        except asyncio.CancelledError:
            logger.debug("Device discovery cancelled")
            return False
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False

    def get_stream_urls(self) -> dict[str, str]:
        if not self.device_ip:
            raise RuntimeError("No device connected")

        base_port = 8086  # RTSP port is typically different from HTTP port
        base = f"rtsp://{self.device_ip}:{base_port}"

        return {
            "video": f"{base}/?camera=world",
            "gaze": f"{base}/?camera=gaze",
            "imu": f"{base}/live/imu",
            "events": f"{base}/live/events",
        }

    @property
    def is_connected(self) -> bool:
        return self.device is not None and self.device_ip is not None

    async def cleanup(self):
        if self.device:
            try:
                await self.device.close()
            except:
                pass
            finally:
                self.device = None
                self.device_ip = None
                self.device_port = None
