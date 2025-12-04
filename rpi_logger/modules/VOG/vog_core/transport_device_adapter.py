"""
Transport Device Adapter

Adapts a transport (USBTransport or XBeeTransport) to the device interface
expected by VOGHandler (which originally used USBSerialDevice).
"""

from typing import Optional
import logging

from .transports import BaseTransport

logger = logging.getLogger(__name__)


class TransportDeviceAdapter:
    """
    Adapts a transport to the device interface expected by VOGHandler.

    VOGHandler was originally designed to work with USBSerialDevice.
    This adapter allows it to work with any transport implementing BaseTransport.
    """

    def __init__(self, transport: BaseTransport, port: str):
        """
        Initialize the adapter.

        Args:
            transport: The underlying transport
            port: The port/device identifier
        """
        self._transport = transport
        self._port = port

    @property
    def port(self) -> str:
        """Return the port identifier."""
        return self._port

    @property
    def is_connected(self) -> bool:
        """Check if the transport is connected."""
        return self._transport.is_connected

    async def write(self, data: bytes) -> bool:
        """
        Write data to the device.

        Args:
            data: Bytes to write

        Returns:
            True if write was successful
        """
        return await self._transport.write(data)

    async def read_line(self) -> Optional[str]:
        """
        Read a line from the device.

        Returns:
            The line read, or None if no data
        """
        return await self._transport.read_line()

    async def write_line(self, line: str, ending: str = '\n') -> bool:
        """
        Write a line to the device.

        Args:
            line: Text to write
            ending: Line ending to append

        Returns:
            True if write was successful
        """
        return await self._transport.write_line(line, ending)
