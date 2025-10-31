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
            logger.warning(f"USB monitor for {self.config.device_name} already running")
            return

        self._running = True
        logger.info(f"Starting USB device monitor for {self.config.device_name}")
        logger.info(f"  Target VID: {self.config.vid} (0x{self.config.vid:04X})")
        logger.info(f"  Target PID: {self.config.pid} (0x{self.config.pid:04X})")
        logger.info(f"  Scan interval: {self._scan_interval}s")

        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info(f"Started USB device monitor for {self.config.device_name} - task created: {self._monitor_task}")

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
        logger.info(f"USB monitor loop started for {self.config.device_name}")
        scan_count = 0
        try:
            while self._running:
                scan_count += 1
                logger.debug(f"USB scan #{scan_count} for {self.config.device_name}")
                await self._scan_devices()
                await asyncio.sleep(self._scan_interval)
        except asyncio.CancelledError:
            logger.info(f"USB monitor loop cancelled for {self.config.device_name} (scans completed: {scan_count})")
            pass
        except Exception as e:
            logger.error(f"USB monitor loop error for {self.config.device_name}: {e}", exc_info=True)
        finally:
            logger.info(f"USB monitor loop exited for {self.config.device_name}")

    async def _scan_devices(self):
        try:
            ports = await asyncio.to_thread(serial.tools.list_ports.comports)
            current_ports = set()

            logger.debug(f"Scanning {len(ports)} serial ports")

            for port_info in ports:
                vid_str = f"0x{port_info.vid:04X}" if port_info.vid else "None"
                pid_str = f"0x{port_info.pid:04X}" if port_info.pid else "None"

                if self.config.matches_port(port_info):
                    port_name = port_info.device
                    current_ports.add(port_name)
                    logger.info(f"Found matching {self.config.device_name}: {port_name} (VID={vid_str}, PID={pid_str})")

                    if port_name not in self._known_ports:
                        await self._handle_new_device(port_name)
                else:
                    if port_info.vid and port_info.pid:
                        logger.debug(f"Port {port_info.device} does not match (VID={vid_str}, PID={pid_str})")

            disconnected_ports = self._known_ports - current_ports
            for port_name in disconnected_ports:
                await self._handle_disconnected_device(port_name)

        except Exception as e:
            logger.error(f"Error scanning USB devices: {e}", exc_info=True)

    async def _handle_new_device(self, port: str):
        logger.info(f"New {self.config.device_name} detected on {port}")
        self._known_ports.add(port)

        device = USBSerialDevice(port, self.config)
        logger.info(f"Attempting to connect to {port}...")
        connected = await device.connect()

        if connected:
            logger.info(f"Successfully connected to {port}")
            self._devices[port] = device
            if self.on_connect:
                try:
                    logger.info(f"Calling on_connect callback for {port}")
                    if asyncio.iscoroutinefunction(self.on_connect):
                        logger.info(f"on_connect is async, awaiting...")
                        await self.on_connect(device)
                    else:
                        logger.info(f"on_connect is sync, calling directly...")
                        self.on_connect(device)
                    logger.info(f"on_connect callback completed for {port}")
                except Exception as e:
                    logger.error(f"Error in on_connect callback: {e}", exc_info=True)
            else:
                logger.warning(f"No on_connect callback registered")
        else:
            logger.error(f"Failed to connect to {port}")

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
