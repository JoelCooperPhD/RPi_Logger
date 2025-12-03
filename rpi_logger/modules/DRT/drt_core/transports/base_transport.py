"""
Base Transport

Abstract base class defining the transport interface for DRT device communication.
Implementations include USB Serial and XBee wireless transports.
"""

from abc import ABC, abstractmethod
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class BaseTransport(ABC):
    """
    Abstract base class for device transport layers.

    Provides a common interface for sending and receiving data
    regardless of the underlying transport mechanism (USB Serial, XBee, etc.).
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
        """
        Establish connection to the device.

        Returns:
            True if connection was successful
        """
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """
        Close the connection to the device.
        """
        ...

    @abstractmethod
    async def write(self, data: bytes) -> bool:
        """
        Write data to the device.

        Args:
            data: Bytes to write

        Returns:
            True if write was successful
        """
        ...

    @abstractmethod
    async def read_line(self) -> Optional[str]:
        """
        Read a line of text from the device.

        Returns:
            The line read (without line ending), or None if no data
        """
        ...

    async def write_line(self, line: str, ending: str = '\n') -> bool:
        """
        Write a line of text to the device.

        Args:
            line: Text to write
            ending: Line ending to append

        Returns:
            True if write was successful
        """
        data = f"{line}{ending}".encode('utf-8')
        return await self.write(data)

    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()
        return False
