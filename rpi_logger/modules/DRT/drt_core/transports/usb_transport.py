"""
USB Serial Transport

Transport implementation for USB serial communication with DRT devices.
Wraps pyserial with an async interface compatible with BaseTransport.
"""

import asyncio
from typing import Optional
import logging

import serial

from .base_transport import BaseTransport
from ..protocols import DEFAULT_READ_TIMEOUT, DEFAULT_WRITE_TIMEOUT

logger = logging.getLogger(__name__)


class USBTransport(BaseTransport):
    """
    USB Serial transport for DRT devices.

    Provides async read/write operations over a serial connection.
    """

    def __init__(
        self,
        port: str,
        baudrate: int = 921600,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        write_timeout: float = DEFAULT_WRITE_TIMEOUT
    ):
        """
        Initialize the USB transport.

        Args:
            port: Serial port path (e.g., '/dev/ttyUSB0' or 'COM3')
            baudrate: Serial baudrate
            read_timeout: Read operation timeout in seconds
            write_timeout: Write operation timeout in seconds
        """
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.read_timeout = read_timeout
        self.write_timeout = write_timeout
        self._serial: Optional[serial.Serial] = None

    @property
    def is_connected(self) -> bool:
        """Check if the serial port is connected and open."""
        return self._serial is not None and self._serial.is_open

    async def connect(self) -> bool:
        """
        Open the serial connection.

        Returns:
            True if connection was successful
        """
        if self.is_connected:
            logger.warning("Already connected to %s", self.port)
            return True

        try:
            self._serial = await asyncio.to_thread(
                serial.Serial,
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.read_timeout,
                write_timeout=self.write_timeout
            )
            await asyncio.to_thread(self._serial.reset_input_buffer)
            await asyncio.to_thread(self._serial.reset_output_buffer)

            self._connected = True
            logger.info("Connected to %s at %d baud", self.port, self.baudrate)
            return True

        except serial.SerialException as e:
            logger.error("Failed to connect to %s: %s", self.port, e)
            self._serial = None
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Close the serial connection."""
        if self._serial:
            try:
                await asyncio.to_thread(self._serial.close)
                logger.info("Disconnected from %s", self.port)
            except Exception as e:
                logger.error("Error disconnecting from %s: %s", self.port, e)
            finally:
                self._serial = None
                self._connected = False

    async def write(self, data: bytes) -> bool:
        """
        Write data to the serial port.

        Args:
            data: Bytes to write

        Returns:
            True if write was successful
        """
        if not self.is_connected:
            logger.error("Cannot write to %s: not connected", self.port)
            return False

        try:
            await asyncio.to_thread(self._serial.write, data)
            await asyncio.to_thread(self._serial.flush)
            logger.debug("Wrote to %s: %s", self.port, data)
            return True
        except serial.SerialException as e:
            logger.error("Write error on %s: %s", self.port, e)
            return False

    async def read_line(self) -> Optional[str]:
        """
        Read a line from the serial port.

        Returns:
            The line read (decoded as UTF-8), or None if no data/timeout
        """
        if not self.is_connected:
            return None

        try:
            # Check if data is available
            if not await asyncio.to_thread(lambda: self._serial.in_waiting > 0):
                # Small sleep to prevent busy-waiting
                await asyncio.sleep(0.01)
                return None

            line_bytes = await asyncio.to_thread(self._serial.readline)
            if line_bytes:
                line = line_bytes.decode('utf-8', errors='replace').strip()
                logger.debug("Read from %s: %s", self.port, line)
                return line
            return None

        except serial.SerialException as e:
            logger.error("Read error on %s: %s", self.port, e)
            return None
        except Exception as e:
            logger.error("Unexpected error reading from %s: %s", self.port, e)
            return None

    async def read_bytes(self, size: int) -> Optional[bytes]:
        """
        Read a specific number of bytes from the serial port.

        Args:
            size: Number of bytes to read

        Returns:
            Bytes read, or None if error/timeout
        """
        if not self.is_connected:
            return None

        try:
            data = await asyncio.to_thread(self._serial.read, size)
            return data if data else None
        except serial.SerialException as e:
            logger.error("Read error on %s: %s", self.port, e)
            return None

    @property
    def bytes_available(self) -> int:
        """Return the number of bytes available to read."""
        if not self.is_connected:
            return 0
        try:
            return self._serial.in_waiting
        except serial.SerialException:
            return 0
