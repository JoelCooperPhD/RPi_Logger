"""Base transport interface for GPS communication.

This module defines the abstract transport interface that all GPS transport
implementations must follow. This allows the handler to work with different
transport mechanisms (UART serial, USB serial, network, etc.).
"""

from abc import ABC, abstractmethod
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class BaseGPSTransport(ABC):
    """Abstract base class for GPS transport layers.

    Provides a common interface for receiving NMEA sentences from GPS devices
    regardless of the underlying transport mechanism.

    GPS transports are read-only (no write capability needed for most receivers).
    """

    def __init__(self):
        """Initialize the transport."""
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """Check if the transport is connected."""
        return self._connected

    @abstractmethod
    async def connect(self) -> bool:
        """Establish connection to the GPS device.

        Returns:
            True if connection was successful
        """
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the connection to the GPS device."""
        ...

    @abstractmethod
    async def read_line(self, timeout: float = 1.0) -> Optional[str]:
        """Read a line from the GPS device.

        Args:
            timeout: Maximum time to wait for data in seconds

        Returns:
            The line read (without line ending), or None if timeout/no data
        """
        ...

    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()
        return False
