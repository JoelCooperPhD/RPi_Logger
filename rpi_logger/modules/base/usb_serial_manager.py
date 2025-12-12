import asyncio
from dataclasses import dataclass
from typing import Optional, Callable, Dict, Set
import serial
import serial.tools.list_ports
from enum import Enum

from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger(__name__)


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
            logger.info("Connecting to %s on %s", self.config.device_name, self.port)

            self._serial = await asyncio.to_thread(
                serial.Serial,
                port=self.port,
                baudrate=self.config.baudrate,
                timeout=self.config.timeout,
                write_timeout=self.config.write_timeout
            )

            # Clear any stale data in buffers
            await asyncio.to_thread(self._serial.reset_input_buffer)
            await asyncio.to_thread(self._serial.reset_output_buffer)

            self.state = DeviceState.CONNECTED
            logger.info("Connected to %s on %s", self.config.device_name, self.port)
            return True

        except Exception as e:
            logger.error("Failed to connect to %s: %s", self.port, e)
            self.state = DeviceState.ERROR
            return False

    async def disconnect(self):
        if self._serial and self._serial.is_open:
            try:
                await asyncio.to_thread(self._serial.close)
                logger.debug("Disconnected from %s", self.port)
            except Exception as e:
                logger.error("Error disconnecting from %s: %s", self.port, e)

        self._serial = None
        self.state = DeviceState.DISCONNECTED

    async def write(self, data: bytes) -> bool:
        if not self._serial or not self._serial.is_open:
            logger.warning("Cannot write to %s: not connected", self.port)
            return False

        try:
            await asyncio.to_thread(self._serial.write, data)
            await asyncio.to_thread(self._serial.flush)
            return True
        except Exception as e:
            logger.error("Error writing to %s: %s", self.port, e)
            self.state = DeviceState.ERROR
            return False

    async def read(self, size: int = 1) -> Optional[bytes]:
        if not self._serial or not self._serial.is_open:
            return None

        try:
            data = await asyncio.to_thread(self._serial.read, size)
            return data if data else None
        except Exception as e:
            logger.error("Error reading from %s: %s", self.port, e)
            self.state = DeviceState.ERROR
            return None

    async def read_line(self) -> Optional[str]:
        if not self._serial or not self._serial.is_open:
            return None

        try:
            line = await asyncio.to_thread(self._serial.readline)
            return line.decode('utf-8', errors='ignore').strip() if line else None
        except Exception as e:
            logger.error("Error reading line from %s: %s", self.port, e)
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
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    async def start(self):
        if self._running:
            logger.warning("USB monitor for %s already running", self.config.device_name)
            return

        self._running = True
        self._loop = asyncio.get_running_loop()
        logger.info(
            "Starting USB device monitor for %s (VID=0x%04X, PID=0x%04X)",
            self.config.device_name, self.config.vid, self.config.pid
        )

        await self._scan_devices()

        if self._devices:
            logger.info("Initial scan complete: %d device(s) connected", len(self._devices))
        else:
            logger.debug("Initial scan complete: no devices found, will continue monitoring")

        self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def stop(self, timeout: float = 5.0):
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        target_loop = self._loop

        if target_loop and current_loop is not target_loop:
            if target_loop.is_running():
                future = asyncio.run_coroutine_threadsafe(self._stop_internal(), target_loop)
                try:
                    await asyncio.wait_for(asyncio.wrap_future(future), timeout=timeout)
                    return
                except (asyncio.TimeoutError, RuntimeError) as exc:
                    logger.warning(
                        "USB monitor stop timed out on original loop (%s); forcing cleanup on current loop",
                        exc,
                    )
            else:
                logger.debug(
                    "USB monitor loop already stopped for %s; forcing cleanup on current loop",
                    self.config.device_name,
                )

            await self._force_stop_from_current_loop()
            return

        await self._stop_internal()

    async def _stop_internal(self):
        self._running = False

        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None

        await self._disconnect_all_devices()

        self._loop = None
        logger.debug("Stopped USB device monitor for %s", self.config.device_name)

    async def _force_stop_from_current_loop(self):
        self._running = False

        monitor_task = self._monitor_task
        if monitor_task:
            if monitor_task.done():
                try:
                    monitor_task.result()
                except asyncio.CancelledError:
                    pass
                except Exception as exc:  # pragma: no cover - defensive
                    logger.debug(
                        "USB monitor task for %s completed with error during forced stop: %s",
                        self.config.device_name,
                        exc,
                    )
            else:
                logger.debug(
                    "USB monitor task still pending for %s but loop unavailable; marking as cancelled",
                    self.config.device_name,
                )
            self._monitor_task = None

        await self._disconnect_all_devices()

        self._loop = None
        logger.debug(
            "Force-stopped USB device monitor for %s (original loop unavailable)",
            self.config.device_name,
        )

    async def _disconnect_all_devices(self):
        for device in list(self._devices.values()):
            try:
                await device.disconnect()
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "Error disconnecting %s during USB monitor stop: %s",
                    getattr(device, "port", "unknown"),
                    exc,
                    exc_info=True,
                )

        self._devices.clear()
        self._known_ports.clear()

    async def _monitor_loop(self):
        logger.debug("USB monitor loop started for %s", self.config.device_name)
        try:
            while self._running:
                await self._scan_devices()
                await asyncio.sleep(self._scan_interval)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("USB monitor loop error for %s: %s", self.config.device_name, e, exc_info=True)

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
            logger.error("Error scanning USB devices: %s", e, exc_info=True)

    async def _handle_new_device(self, port: str):
        logger.info("New %s detected on %s", self.config.device_name, port)
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
                    logger.error("Error in on_connect callback: %s", e, exc_info=True)
        else:
            logger.error("Failed to connect to %s", port)

    async def _handle_disconnected_device(self, port: str):
        logger.info("%s disconnected from %s", self.config.device_name, port)
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
                    logger.error("Error in on_disconnect callback: %s", e)

    def get_devices(self) -> Dict[str, USBSerialDevice]:
        return self._devices.copy()

    def get_device(self, port: str) -> Optional[USBSerialDevice]:
        return self._devices.get(port)

    @property
    def device_count(self) -> int:
        return len(self._devices)
