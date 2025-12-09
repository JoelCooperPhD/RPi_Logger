"""Serial UART transport for GPS receivers.

This module provides serial transport using serial_asyncio for efficient
non-blocking I/O with UART-based GPS receivers like the BerryGPS.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Optional
import logging

from .base_transport import BaseGPSTransport
from ..constants import DEFAULT_BAUD_RATE, DEFAULT_RECONNECT_DELAY

logger = logging.getLogger(__name__)

# Optional import - serial may not be available on all platforms
try:
    import serial  # type: ignore
    import serial_asyncio  # type: ignore
    SERIAL_AVAILABLE = True
except ImportError as exc:
    serial = None  # type: ignore
    serial_asyncio = None  # type: ignore
    SERIAL_AVAILABLE = False
    SERIAL_IMPORT_ERROR = exc
else:
    SERIAL_IMPORT_ERROR = None


class SerialGPSTransport(BaseGPSTransport):
    """Serial UART transport for GPS receivers.

    Uses serial_asyncio for efficient async I/O. This is well-suited for
    continuous NMEA streaming from GPS receivers.

    Example:
        transport = SerialGPSTransport("/dev/serial0", 9600)
        async with transport:
            while True:
                line = await transport.read_line()
                if line:
                    print(line)
    """

    def __init__(
        self,
        port: str,
        baudrate: int = DEFAULT_BAUD_RATE,
        reconnect_delay: float = DEFAULT_RECONNECT_DELAY,
    ):
        """Initialize the serial transport.

        Args:
            port: Serial port path (e.g., '/dev/serial0' or '/dev/ttyUSB0')
            baudrate: Serial baudrate (default 9600 for most GPS)
            reconnect_delay: Delay before reconnect attempts in seconds
        """
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.reconnect_delay = reconnect_delay

        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._last_error: Optional[str] = None

    @property
    def is_connected(self) -> bool:
        """Check if the serial connection is open."""
        return self._connected and self._reader is not None

    @property
    def last_error(self) -> Optional[str]:
        """Get the last error message, if any."""
        return self._last_error

    async def connect(self) -> bool:
        """Open the serial connection.

        Returns:
            True if connection was successful
        """
        if not SERIAL_AVAILABLE:
            self._last_error = f"Serial module not available: {SERIAL_IMPORT_ERROR}"
            logger.error(self._last_error)
            return False

        if self.is_connected:
            logger.debug("Already connected to %s", self.port)
            return True

        try:
            self._reader, self._writer = await serial_asyncio.open_serial_connection(
                url=self.port,
                baudrate=self.baudrate,
            )
            self._connected = True
            self._last_error = None
            logger.info("Connected to GPS on %s at %d baud", self.port, self.baudrate)
            return True

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            event_type = "serial_exception" if serial and isinstance(exc, serial.SerialException) else "serial_error"
            self._last_error = str(exc)
            logger.warning(
                "%s connecting to %s at %d baud: %s",
                event_type, self.port, self.baudrate, exc
            )
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Close the serial connection."""
        if self._writer is None:
            self._connected = False
            return

        writer = self._writer
        self._writer = None
        self._reader = None
        self._connected = False

        with contextlib.suppress(Exception):
            writer.close()

        if hasattr(writer, "wait_closed"):
            try:
                await asyncio.wait_for(writer.wait_closed(), timeout=1.0)
            except asyncio.TimeoutError:
                logger.debug("Timeout waiting for serial close on %s", self.port)
            except Exception:
                logger.debug("Error closing serial on %s", self.port)

        logger.info("Disconnected from GPS on %s", self.port)

    async def read_line(self, timeout: float = 1.0) -> Optional[str]:
        """Read a line (NMEA sentence) from the GPS.

        Args:
            timeout: Maximum time to wait for a complete line

        Returns:
            The line read (decoded, stripped), or None if timeout/error
        """
        if not self.is_connected or self._reader is None:
            return None

        try:
            line = await asyncio.wait_for(self._reader.readline(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("Read error on %s: %s", self.port, exc)
            return None

        if not line:
            # EOF - stream ended
            logger.warning("Serial stream ended on %s (EOF)", self.port)
            self._last_error = "Stream ended (EOF)"
            return None

        # Decode and strip (NMEA is ASCII)
        decoded = line.decode("ascii", errors="ignore").strip()
        return decoded if decoded else None

    async def read_sentences(self, timeout: float = 1.0):
        """Async generator that yields NMEA sentences.

        This is a convenience method for continuous reading.

        Args:
            timeout: Timeout for each read attempt

        Yields:
            NMEA sentences starting with '$'
        """
        while self.is_connected:
            line = await self.read_line(timeout=timeout)
            if line and line.startswith("$"):
                yield line
