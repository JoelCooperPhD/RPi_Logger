"""
USB Serial Transport

Transport implementation for USB serial communication with VOG devices.
Wraps pyserial with an async interface compatible with BaseTransport.
"""

import asyncio
import threading
from typing import Optional

import serial

from .base_transport import BaseTransport
from rpi_logger.core.logging_utils import get_module_logger

# Default timeout values
# Note: Read timeout should be short enough to not block the event loop,
# but we use a line buffer to accumulate partial reads
DEFAULT_READ_TIMEOUT = 0.1
DEFAULT_WRITE_TIMEOUT = 1.0

# Maximum buffer size to prevent memory exhaustion from malformed devices
MAX_READ_BUFFER_SIZE = 65536  # 64KB


class USBTransport(BaseTransport):
    """
    USB Serial transport for VOG devices.

    Provides async read/write operations over a serial connection.
    """

    def __init__(
        self,
        port: str,
        baudrate: int = 57600,
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
        self._lock = threading.Lock()  # Serialize access to serial port
        self._read_buffer = b''  # Buffer for accumulating partial reads
        self.logger = get_module_logger("USBTransport")

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
            self.logger.warning(f"Already connected to {self.port}")
            return True

        try:
            # Run serial open in thread pool to avoid blocking
            self._serial = await asyncio.to_thread(
                serial.Serial,
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.read_timeout,
                write_timeout=self.write_timeout
            )

            # Clear any stale data in buffers
            await asyncio.to_thread(self._serial.reset_input_buffer)
            await asyncio.to_thread(self._serial.reset_output_buffer)

            self._connected = True
            self.logger.info(f"Connected to {self.port} at {self.baudrate} baud")
            return True

        except serial.SerialException as e:
            self.logger.error(f"Failed to connect to {self.port}: {e}")
            self._serial = None
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Close the serial connection."""
        if self._serial:
            try:
                await asyncio.to_thread(self._serial.close)
                self.logger.info(f"Disconnected from {self.port}")
            except Exception as e:
                self.logger.error(f"Error disconnecting from {self.port}: {e}")
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
            self.logger.error(f"Cannot write to {self.port}: not connected")
            return False

        def _write_with_lock():
            """Write data while holding the lock."""
            with self._lock:
                self._serial.write(data)
                self._serial.flush()

        try:
            await asyncio.to_thread(_write_with_lock)
            self.logger.debug(f"Wrote to {self.port}: {data}")
            return True
        except serial.SerialException as e:
            self.logger.error(f"Write error on {self.port}: {e}")
            return False

    async def read_line(self) -> Optional[str]:
        """
        Read a line from the serial port.

        Uses internal buffering to handle partial reads properly.
        Lock is only held briefly during buffer access, not during the read.

        Returns:
            The line read (decoded as UTF-8), or None if no data/timeout
        """
        if not self.is_connected:
            return None

        def _read_with_buffer():
            """Read data and manage line buffer."""
            # Read any available data (brief lock for serial access)
            with self._lock:
                waiting = self._serial.in_waiting
                if waiting > 0:
                    new_data = self._serial.read(waiting)
                else:
                    new_data = b''

            # Update buffer (brief lock for buffer access)
            with self._lock:
                if new_data:
                    self._read_buffer += new_data

                # Prevent buffer overflow from malformed devices
                if len(self._read_buffer) > MAX_READ_BUFFER_SIZE:
                    # Keep most recent data, drop oldest
                    self._read_buffer = self._read_buffer[-MAX_READ_BUFFER_SIZE:]

                # Check if we have a complete line in the buffer
                newline_pos = self._read_buffer.find(b'\n')
                if newline_pos >= 0:
                    # Extract the line (including newline)
                    line = self._read_buffer[:newline_pos + 1]
                    self._read_buffer = self._read_buffer[newline_pos + 1:]
                    return line
                return None

        try:
            line_bytes = await asyncio.to_thread(_read_with_buffer)
            if line_bytes:
                line = line_bytes.decode('utf-8', errors='replace').strip()
                if line:  # Only log non-empty lines
                    self.logger.debug(f"Read from {self.port}: {line}")
                return line if line else None
            return None

        except serial.SerialException as e:
            self.logger.error(f"Read error on {self.port}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error reading from {self.port}: {e}")
            return None
