"""
XBee Wireless Transport

Transport implementation for XBee wireless communication with wDRT devices.
Wraps digi-xbee library with an interface compatible with BaseTransport.
"""

import asyncio
from typing import Optional, TYPE_CHECKING
import logging

from .base_transport import BaseTransport
from ..protocols import DEFAULT_READ_TIMEOUT

logger = logging.getLogger(__name__)

# Conditional import for type checking
if TYPE_CHECKING:
    from digi.xbee.devices import XBeeDevice, RemoteRaw802Device


class XBeeTransport(BaseTransport):
    """
    XBee wireless transport for wDRT devices.

    Provides async read/write operations over XBee 802.15.4 network.
    Requires an XBee coordinator (dongle) to communicate with remote devices.
    """

    def __init__(
        self,
        remote_device: 'RemoteRaw802Device',
        coordinator: 'XBeeDevice',
        node_id: str
    ):
        """
        Initialize the XBee transport.

        Args:
            remote_device: The remote XBee device to communicate with
            coordinator: The local XBee coordinator (dongle)
            node_id: The node ID of the remote device (e.g., "wDRT_01")
        """
        super().__init__()
        self._remote_device = remote_device
        self._coordinator = coordinator
        self.node_id = node_id

        # Buffer for received data
        self._receive_buffer: asyncio.Queue[str] = asyncio.Queue()

        # Track connection state
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """Check if the XBee connection is active."""
        return (
            self._connected and
            self._coordinator is not None and
            self._coordinator.is_open() and
            self._remote_device is not None
        )

    @property
    def device_id(self) -> str:
        """Return the device identifier (node ID)."""
        return self.node_id

    async def connect(self) -> bool:
        """
        Mark the transport as connected.

        Note: The actual XBee connection is managed by XBeeManager.
        This just marks this transport as ready to use.

        Returns:
            True if ready
        """
        if self._coordinator and self._coordinator.is_open():
            self._connected = True
            logger.info(f"XBee transport ready for {self.node_id}")
            return True
        else:
            logger.error(f"Cannot connect XBee transport: coordinator not open")
            return False

    async def disconnect(self) -> None:
        """
        Mark the transport as disconnected.

        Note: Does not close the coordinator - that's managed by XBeeManager.
        """
        self._connected = False
        logger.info(f"XBee transport disconnected for {self.node_id}")

    async def write(self, data: bytes) -> bool:
        """
        Send data to the remote XBee device.

        Args:
            data: Bytes to send

        Returns:
            True if send was successful
        """
        if not self.is_connected:
            logger.error(f"Cannot write to {self.node_id}: not connected")
            return False

        try:
            # Send as string (strip newline - XBee doesn't need it)
            # Use send_data (blocking with ACK) instead of send_data_async
            cmd_str = data.decode('utf-8', errors='replace').strip()
            logger.info(f"XBee sending to {self.node_id}: '{cmd_str}'")
            await asyncio.to_thread(
                self._coordinator.send_data,
                self._remote_device,
                cmd_str  # Send as string without newline, matching RS_Logger
            )
            logger.info(f"XBee sent to {self.node_id}: '{cmd_str}'")
            return True

        except Exception as e:
            logger.error(f"XBee write error to {self.node_id}: {e}")
            return False

    async def read_line(self) -> Optional[str]:
        """
        Read a line from the receive buffer.

        Note: Data must be pushed to the buffer via handle_received_data()
        by the XBeeManager when messages arrive.

        Returns:
            The line read, or None if no data available
        """
        try:
            # Non-blocking get with small timeout
            line = await asyncio.wait_for(
                self._receive_buffer.get(),
                timeout=0.01
            )
            return line
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            logger.error(f"XBee read error for {self.node_id}: {e}")
            return None

    def handle_received_data(self, data: str) -> None:
        """
        Handle data received from the remote device.

        Called by XBeeManager when a message arrives for this device.

        Args:
            data: Received data string
        """
        try:
            # Put data in buffer for read_line() to retrieve
            self._receive_buffer.put_nowait(data.strip())
            logger.debug(f"Received from {self.node_id}: {data.strip()}")
        except asyncio.QueueFull:
            logger.warning(f"Receive buffer full for {self.node_id}")

    def clear_buffer(self) -> None:
        """Clear the receive buffer."""
        while not self._receive_buffer.empty():
            try:
                self._receive_buffer.get_nowait()
            except asyncio.QueueEmpty:
                break
