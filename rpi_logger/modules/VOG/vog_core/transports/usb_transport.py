"""USB Serial Transport for VOG devices. Wraps pyserial with async interface."""

import asyncio
import threading
from typing import Optional

import serial

from rpi_logger.core.devices.transports import BaseTransport
from rpi_logger.core.logging_utils import get_module_logger

# Timeouts (read: short to not block loop, write: standard)
DEFAULT_READ_TIMEOUT = 0.1
DEFAULT_WRITE_TIMEOUT = 1.0
MAX_READ_BUFFER_SIZE = 65536  # 64KB max buffer to prevent memory exhaustion


class USBTransport(BaseTransport):
    """USB Serial transport for VOG devices with async read/write."""

    def __init__(self, port: str, baudrate: int = 57600,
                 read_timeout: float = DEFAULT_READ_TIMEOUT,
                 write_timeout: float = DEFAULT_WRITE_TIMEOUT):
        """Initialize USB transport with port, baudrate, and timeouts."""
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.read_timeout = read_timeout
        self.write_timeout = write_timeout
        self._serial: Optional[serial.Serial] = None
        self._lock = threading.Lock()
        self._read_buffer = b''
        self.logger = get_module_logger("USBTransport")

    @property
    def is_connected(self) -> bool:
        """Check if the serial port is connected and open."""
        return self._serial is not None and self._serial.is_open

    async def connect(self) -> bool:
        """Open serial connection. Returns True if successful."""
        if self.is_connected:
            self.logger.warning("Already connected to %s", self.port)
            return True
        try:
            self._serial = await asyncio.to_thread(
                serial.Serial, port=self.port, baudrate=self.baudrate,
                timeout=self.read_timeout, write_timeout=self.write_timeout)
            await asyncio.to_thread(self._serial.reset_input_buffer)
            await asyncio.to_thread(self._serial.reset_output_buffer)
            self._connected = True
            self.logger.info("Connected to %s at %d baud", self.port, self.baudrate)
            return True
        except serial.SerialException as e:
            self.logger.error("Failed to connect to %s: %s", self.port, e)
            self._serial = None
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Close the serial connection."""
        if not self._serial:
            return

        def _close_with_lock():
            """Close serial port while holding lock to prevent read/write races."""
            with self._lock:
                if self._serial and self._serial.is_open:
                    self._serial.close()
                # Clear any buffered data
                self._read_buffer = b''

        try:
            await asyncio.to_thread(_close_with_lock)
            self.logger.info("Disconnected from %s", self.port)
        except Exception as e:
            self.logger.error("Error disconnecting from %s: %s", self.port, e)
        finally:
            self._serial = None
            self._connected = False

    async def write(self, data: bytes) -> bool:
        """Write data to serial port. Returns True if successful."""
        if not self.is_connected:
            self.logger.error("Cannot write to %s: not connected", self.port)
            return False
        def _write_with_lock():
            with self._lock:
                self._serial.write(data)
                self._serial.flush()
        try:
            await asyncio.to_thread(_write_with_lock)
            self.logger.debug("Wrote to %s: %s", self.port, data)
            return True
        except serial.SerialException as e:
            self.logger.error("Write error on %s: %s", self.port, e)
            return False

    async def read_line(self) -> Optional[str]:
        """Read line from serial port using internal buffering. Returns decoded line or None."""
        if not self.is_connected:
            return None
        def _read_with_buffer():
            with self._lock:
                waiting = self._serial.in_waiting
                if waiting > 0:
                    self._read_buffer += self._serial.read(waiting)
                if len(self._read_buffer) > MAX_READ_BUFFER_SIZE:
                    dropped = len(self._read_buffer) - MAX_READ_BUFFER_SIZE
                    self.logger.warning("Read buffer overflow on %s, dropping %d bytes",
                                      self.port, dropped)
                    self._read_buffer = self._read_buffer[-MAX_READ_BUFFER_SIZE:]
                newline_pos = self._read_buffer.find(b'\n')
                if newline_pos >= 0:
                    line = self._read_buffer[:newline_pos + 1]
                    self._read_buffer = self._read_buffer[newline_pos + 1:]
                    return line
                return None
        try:
            line_bytes = await asyncio.to_thread(_read_with_buffer)
            if line_bytes:
                line = line_bytes.decode('utf-8', errors='replace').strip()
                if line:
                    self.logger.debug("Read from %s: %s", self.port, line)
                return line if line else None
            return None
        except serial.SerialException as e:
            self.logger.error("Read error on %s: %s", self.port, e)
            return None
        except Exception as e:
            self.logger.error("Unexpected error reading from %s: %s", self.port, e)
            return None
