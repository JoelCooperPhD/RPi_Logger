"""
XBee Wireless Transport

Transport implementation for XBee wireless communication with wVOG and wDRT devices.
Wraps digi-xbee library with an interface compatible with module BaseTransport classes.

This is the shared implementation used by all modules. The transport is created and
managed by DeviceSystem, and message routing is handled by XBeeManager.
"""

import asyncio
import queue
from typing import Optional, TYPE_CHECKING
import logging

logger = logging.getLogger(__name__)

# Conditional import for type checking
if TYPE_CHECKING:
    from digi.xbee.devices import XBeeDevice, RemoteRaw802Device


class XBeeTransport:
    """
    XBee wireless transport for wVOG and wDRT devices.

    Provides async read/write operations over XBee 802.15.4 network.
    Requires an XBee coordinator (dongle) to communicate with remote devices.

    This transport is created by DeviceSystem and registered with
    XBeeManager for message routing. Modules receive a reference to use for
    communication.
    """

    # Maximum buffer size to prevent memory exhaustion
    MAX_BUFFER_SIZE = 1000

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
            node_id: The node ID of the remote device (e.g., "wVOG_01", "wDRT_02")
        """
        self._remote_device = remote_device
        self._coordinator = coordinator
        self.node_id = node_id

        # Buffer for received data - use thread-safe queue since XBee callbacks
        # come from a different thread than the asyncio event loop.
        # Bounded to prevent memory exhaustion if handler read loop stalls.
        self._receive_buffer: queue.Queue[str] = queue.Queue(maxsize=self.MAX_BUFFER_SIZE)
        self._dropped_messages = 0  # Track overflow for diagnostics

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
            logger.error(
                f"Cannot write to {self.node_id}: not connected "
                f"(connected={self._connected}, coordinator={self._coordinator is not None}, "
                f"open={self._coordinator.is_open() if self._coordinator else False}, "
                f"remote={self._remote_device is not None})"
            )
            return False

        try:
            # Send as string (strip newline - XBee doesn't need it)
            cmd_str = data.decode('utf-8', errors='replace').strip()
            logger.debug(f"XBee sending to {self.node_id}: '{cmd_str}'")
            await asyncio.to_thread(
                self._coordinator.send_data,
                self._remote_device,
                cmd_str
            )
            logger.debug(f"XBee sent to {self.node_id}: '{cmd_str}'")
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
            # Try to get immediately without blocking
            return self._receive_buffer.get_nowait()
        except queue.Empty:
            return None
        except Exception as e:
            logger.error(f"XBee read error for {self.node_id}: {e}")
            return None

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

    def handle_received_data(self, data: str) -> None:
        """
        Handle data received from the remote device.

        Called by XBeeManager when a message arrives for this device.
        This is called from the XBee library's thread, so we use a thread-safe queue.

        If the buffer is full, the oldest message is dropped to make room.

        Args:
            data: Received data string
        """
        stripped_data = data.strip()

        try:
            # Try to put data in buffer without blocking
            self._receive_buffer.put_nowait(stripped_data)
            logger.debug(
                f"XBee buffered from {self.node_id}: {stripped_data} "
                f"(queue size: {self._receive_buffer.qsize()})"
            )
        except queue.Full:
            # Buffer full - drop oldest message to make room (ring buffer behavior)
            try:
                dropped = self._receive_buffer.get_nowait()
                self._dropped_messages += 1
                logger.warning(
                    f"Receive buffer full for {self.node_id}, dropped oldest message: "
                    f"'{dropped[:50]}...' (total dropped: {self._dropped_messages})"
                )
                # Now put the new data
                self._receive_buffer.put_nowait(stripped_data)
            except queue.Empty:
                # Shouldn't happen, but handle it
                pass

    def clear_buffer(self) -> None:
        """Clear the receive buffer."""
        while not self._receive_buffer.empty():
            try:
                self._receive_buffer.get_nowait()
            except queue.Empty:
                break

    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()
        return False
