import asyncio
import logging
from dataclasses import dataclass
from typing import Optional, Callable, Dict, Set
import serial
import serial.tools.list_ports
from enum import Enum

logger = logging.getLogger(__name__)


class DeviceState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class USBDeviceConfig:
    vid: int
    pid: int
    baudrate: int = 9600
    timeout: float = 1.0
    write_timeout: float = 1.0
    device_name: str = "USB Device"

    def matches_port(self, port_info) -> bool:
        return port_info.vid == self.vid and port_info.pid == self.pid


class USBSerialDevice:
    def __init__(self, port: str, config: USBDeviceConfig):
        self.port = port
        self.config = config
        self.state = DeviceState.DISCONNECTED
        self._serial: Optional[serial.Serial] = None
        self._read_task: Optional[asyncio.Task] = None
        self._running = False

    async def connect(self) -> bool:
        if self.state == DeviceState.CONNECTED:
            return True

        try:
            self.state = DeviceState.CONNECTING
            logger.info(f"Connecting to {self.config.device_name} on {self.port}")

            self._serial = await asyncio.to_thread(
                serial.Serial,
                port=self.port,
                baudrate=self.config.baudrate,
                timeout=self.config.timeout,
                write_timeout=self.config.write_timeout
            )

            self.state = DeviceState.CONNECTED
            logger.info(f"Connected to {self.config.device_name} on {self.port}")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to {self.port}: {e}")
            self.state = DeviceState.ERROR
            return False

    async def disconnect(self):
        if self._serial and self._serial.is_open:
            try:
                await asyncio.to_thread(self._serial.close)
                logger.info(f"Disconnected from {self.port}")
            except Exception as e:
                logger.error(f"Error disconnecting from {self.port}: {e}")

        self._serial = None
        self.state = DeviceState.DISCONNECTED

    async def write(self, data: bytes) -> bool:
        if not self._serial or not self._serial.is_open:
            logger.warning(f"Cannot write to {self.port}: not connected")
            return False

        try:
            await asyncio.to_thread(self._serial.write, data)
            return True
        except Exception as e:
            logger.error(f"Error writing to {self.port}: {e}")
            self.state = DeviceState.ERROR
            return False

    async def read(self, size: int = 1) -> Optional[bytes]:
        if not self._serial or not self._serial.is_open:
            return None

        try:
            data = await asyncio.to_thread(self._serial.read, size)
            return data if data else None
        except Exception as e:
            logger.error(f"Error reading from {self.port}: {e}")
            self.state = DeviceState.ERROR
            return None

    async def read_line(self) -> Optional[str]:
        if not self._serial or not self._serial.is_open:
            return None

        try:
            line = await asyncio.to_thread(self._serial.readline)
            return line.decode('utf-8', errors='ignore').strip() if line else None
        except Exception as e:
            logger.error(f"Error reading line from {self.port}: {e}")
            self.state = DeviceState.ERROR
            return None

    @property
    def is_connected(self) -> bool:
        return self.state == DeviceState.CONNECTED and self._serial and self._serial.is_open


class USBDeviceMonitor:
    def __init__(self, config: USBDeviceConfig,
                 on_connect: Optional[Callable[[USBSerialDevice], None]] = None,
                 on_disconnect: Optional[Callable[[str], None]] = None):
        self.config = config
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect

        self._devices: Dict[str, USBSerialDevice] = {}
        self._known_ports: Set[str] = set()
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._scan_interval = 1.0

    async def start(self):
        if self._running:
            return

        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info(f"Started USB device monitor for {self.config.device_name}")

    async def stop(self):
        self._running = False

        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        for device in list(self._devices.values()):
            await device.disconnect()

        self._devices.clear()
        self._known_ports.clear()
        logger.info(f"Stopped USB device monitor for {self.config.device_name}")

    async def _monitor_loop(self):
        try:
            while self._running:
                await self._scan_devices()
                await asyncio.sleep(self._scan_interval)
        except asyncio.CancelledError:
            pass

    async def _scan_devices(self):
        try:
            ports = await asyncio.to_thread(serial.tools.list_ports.comports)
            current_ports = set()

            for port_info in ports:
                if self.config.matches_port(port_info):
                    port_name = port_info.device
                    current_ports.add(port_name)

                    if port_name not in self._known_ports:
                        await self._handle_new_device(port_name)

            disconnected_ports = self._known_ports - current_ports
            for port_name in disconnected_ports:
                await self._handle_disconnected_device(port_name)

        except Exception as e:
            logger.error(f"Error scanning USB devices: {e}")

    async def _handle_new_device(self, port: str):
        logger.info(f"New {self.config.device_name} detected on {port}")
        self._known_ports.add(port)

        device = USBSerialDevice(port, self.config)
        connected = await device.connect()

        if connected:
            self._devices[port] = device
            if self.on_connect:
                try:
                    if asyncio.iscoroutinefunction(self.on_connect):
                        await self.on_connect(device)
                    else:
                        self.on_connect(device)
                except Exception as e:
                    logger.error(f"Error in on_connect callback: {e}")

    async def _handle_disconnected_device(self, port: str):
        logger.info(f"{self.config.device_name} disconnected from {port}")
        self._known_ports.discard(port)

        if port in self._devices:
            device = self._devices.pop(port)
            await device.disconnect()

            if self.on_disconnect:
                try:
                    if asyncio.iscoroutinefunction(self.on_disconnect):
                        await self.on_disconnect(port)
                    else:
                        self.on_disconnect(port)
                except Exception as e:
                    logger.error(f"Error in on_disconnect callback: {e}")

    def get_devices(self) -> Dict[str, USBSerialDevice]:
        return self._devices.copy()

    def get_device(self, port: str) -> Optional[USBSerialDevice]:
        return self._devices.get(port)

    @property
    def device_count(self) -> int:
        return len(self._devices)
