"""Serial UART transport using serial_asyncio for non-blocking GPS I/O."""

from __future__ import annotations

import asyncio
from typing import Optional

from rpi_logger.core.logging_utils import get_module_logger
# Import directly from base_transport to avoid triggering XBee imports
from rpi_logger.core.devices.transports.base_transport import BaseReadOnlyTransport as BaseGPSTransport
from ..constants import DEFAULT_BAUD_RATE, DEFAULT_RECONNECT_DELAY

logger = get_module_logger(__name__)

try:
    import serial  # type: ignore
    import serial_asyncio  # type: ignore
    SERIAL_AVAILABLE = True
    SERIAL_IMPORT_ERROR = None
except ImportError as exc:
    serial = None  # type: ignore
    serial_asyncio = None  # type: ignore
    SERIAL_AVAILABLE = False
    SERIAL_IMPORT_ERROR = exc


class SerialGPSTransport(BaseGPSTransport):
    """Serial UART transport for GPS receivers using serial_asyncio."""

    def __init__(
        self,
        port: str,
        baudrate: int = DEFAULT_BAUD_RATE,
        reconnect_delay: float = DEFAULT_RECONNECT_DELAY,
    ):
        """Initialize with port, baudrate, and reconnect delay."""
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
        """Open serial connection. Returns True if successful."""
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
        """Close serial connection with verification."""
        if self._writer is None:
            self._connected = False
            return

        writer = self._writer
        self._writer = None
        self._reader = None
        self._connected = False

        try:
            writer.close()
        except OSError as e:
            logger.debug("Expected error closing serial writer on %s: %s", self.port, e)
        except Exception as e:
            logger.warning("Error closing serial writer on %s: %s", self.port, e)

        if hasattr(writer, "wait_closed"):
            try:
                await asyncio.wait_for(writer.wait_closed(), timeout=2.0)
            except asyncio.TimeoutError:
                logger.warning("Timeout waiting for serial close on %s (port may still be held)", self.port)
                await asyncio.sleep(0.2)
            except Exception as e:
                logger.debug("Error in wait_closed for serial on %s: %s", self.port, e)
        else:
            await asyncio.sleep(0.1)

        logger.info("Disconnected from GPS on %s", self.port)

    async def read_line(self, timeout: float = 1.0) -> Optional[str]:
        """Read NMEA sentence from GPS. Returns decoded line or None."""
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
            logger.warning("Serial stream ended on %s (EOF)", self.port)
            self._last_error = "Stream ended (EOF)"
            return None

        decoded = line.decode("ascii", errors="ignore").strip()
        return decoded if decoded else None

    async def read_sentences(self, timeout: float = 1.0):
        """Async generator yielding NMEA sentences starting with '$'."""
        while self.is_connected:
            line = await self.read_line(timeout=timeout)
            if line and line.startswith("$"):
                yield line
