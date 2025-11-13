
import asyncio
import logging
from typing import Optional

from pupil_labs.realtime_api.discovery import discover_devices
from pupil_labs.realtime_api.device import Device
from pupil_labs.realtime_api.models import ConnectionType, SensorName, Status

logger = logging.getLogger(__name__)


class DeviceManager:

    def __init__(self):
        self.device: Optional[Device] = None
        self.device_ip: Optional[str] = None
        self.device_port: Optional[int] = None
        self.device_status: Optional[Status] = None
        self.audio_stream_param: str = "audio=scene"

    async def connect(self) -> bool:
        logger.info("Searching for eye tracker device...")

        try:
            async for device_info in discover_devices(timeout_seconds=5.0):
                logger.info(f"Found device: {device_info.name}")

                self.device_ip = device_info.addresses[0]
                self.device_port = device_info.port

                self.device = Device.from_discovered_device(device_info)

                await self.refresh_status()
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

        urls: dict[str, Optional[str]] = {}
        status = self.device_status
        if status is not None:
            urls["video"] = self._sensor_url_from_status(status, SensorName.WORLD)
            urls["gaze"] = self._sensor_url_from_status(status, SensorName.GAZE)
            urls["imu"] = self._sensor_url_from_status(status, SensorName.IMU)
            urls["events"] = self._sensor_url_from_status(status, SensorName.EYE_EVENTS)
            urls["audio"] = self._sensor_url_from_status(status, SensorName.AUDIO)

        defaults = self._default_stream_urls()
        for key, value in defaults.items():
            urls.setdefault(key, value)

        return {k: v for k, v in urls.items() if v is not None}

    async def refresh_status(self) -> Optional[Status]:
        if self.device is None:
            return None

        try:
            status = await self.device.get_status()
        except Exception as exc:
            logger.debug("Device status refresh failed: %s", exc)
            return self.device_status

        self.device_status = status
        return status

    async def get_status(self, force_refresh: bool = False) -> Optional[Status]:
        if force_refresh or self.device_status is None:
            return await self.refresh_status()
        return self.device_status

    def _sensor_url_from_status(self, status: Status, sensor_name: SensorName) -> Optional[str]:
        for sensor in status.matching_sensors(sensor_name, ConnectionType.DIRECT):
            if sensor.url:
                return sensor.url
        return None

    def _default_stream_urls(self) -> dict[str, Optional[str]]:
        base_port = 8086  # RTSP port is typically different from HTTP port
        base = f"rtsp://{self.device_ip}:{base_port}"

        urls: dict[str, Optional[str]] = {
            "video": f"{base}/?camera=world",
            "gaze": f"{base}/?camera=gaze",
            "imu": f"{base}/live/imu",
            "events": f"{base}/live/events",
        }

        audio_param = (self.audio_stream_param or "").strip()
        if audio_param:
            urls["audio"] = f"{base}/?{audio_param}"
        else:
            urls["audio"] = None

        return urls

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
                self.device_status = None
