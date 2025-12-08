"""
XBee Proxy Transport

Transport that proxies XBee communication through the command protocol.
Used when the XBee coordinator lives in the main logger process and modules
run as subprocesses (DRT, VOG, etc.).

Data flow:
- Incoming: Main logger sends xbee_data commands -> runtime pushes to this transport
- Outgoing: This transport sends via callback -> runtime sends xbee_send status
"""

import asyncio
import logging
from typing import Optional, Callable, Awaitable

logger = logging.getLogger(__name__)


class XBeeProxyTransport:
    """
    Proxy transport for XBee communication via command protocol.

    Data is received via push from the runtime (which gets it from
    xbee_data commands), and sends are requested via callback (which
    the runtime forwards as xbee_send status messages).

    This is a shared implementation used by all modules that communicate
    with wireless devices (wDRT, wVOG, etc.).
    """

    MAX_BUFFER_SIZE = 1000

    def __init__(
        self,
        node_id: str,
        send_callback: Callable[[str, str], Awaitable[bool]]
    ):
        """
        Initialize the proxy transport.

        Args:
            node_id: Device node ID (e.g., "wDRT_01", "wVOG_01")
            send_callback: Async callback to send data (node_id, data) -> success
        """
        self.node_id = node_id
        self._send_callback = send_callback
        self._connected = False

        # Receive buffer - asyncio Queue for async/await compatibility
        self._receive_buffer: asyncio.Queue[str] = asyncio.Queue(maxsize=self.MAX_BUFFER_SIZE)
        self._dropped_messages = 0

    @property
    def device_id(self) -> str:
        """Return the device identifier (node ID)."""
        return self.node_id

    @property
    def is_connected(self) -> bool:
        """Check if the transport is connected."""
        return self._connected

    async def connect(self) -> bool:
        """Mark transport as connected."""
        self._connected = True
        logger.info(f"XBee proxy transport ready for {self.node_id}")
        return True

    async def disconnect(self) -> None:
        """Mark transport as disconnected and clear buffer."""
        self._connected = False
        # Clear buffer
        while not self._receive_buffer.empty():
            try:
                self._receive_buffer.get_nowait()
            except asyncio.QueueEmpty:
                break
        logger.info(f"XBee proxy transport disconnected for {self.node_id}")

    async def write(self, data: bytes) -> bool:
        """Send data via the proxy callback."""
        if not self._connected:
            logger.error(f"Cannot write to {self.node_id}: not connected")
            return False

        try:
            data_str = data.decode('utf-8', errors='replace').strip()
            logger.debug(f"XBee proxy sending to {self.node_id}: '{data_str}'")
            return await self._send_callback(self.node_id, data_str)
        except Exception as e:
            logger.error(f"XBee proxy write error to {self.node_id}: {e}")
            return False

    async def read_line(self) -> Optional[str]:
        """Read from the receive buffer (non-blocking)."""
        try:
            return self._receive_buffer.get_nowait()
        except asyncio.QueueEmpty:
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

    def push_data(self, data: str) -> None:
        """
        Push received data into the buffer.

        Called by runtime when xbee_data command arrives.
        This is called from the asyncio event loop thread.

        Args:
            data: Raw data string from the device
        """
        stripped = data.strip()
        try:
            self._receive_buffer.put_nowait(stripped)
            logger.debug(
                f"XBee proxy buffered for {self.node_id}: '{stripped}' "
                f"(queue size: {self._receive_buffer.qsize()})"
            )
        except asyncio.QueueFull:
            # Buffer full - drop oldest to make room (ring buffer behavior)
            try:
                dropped = self._receive_buffer.get_nowait()
                self._dropped_messages += 1
                logger.warning(
                    f"Receive buffer full for {self.node_id}, dropped: "
                    f"'{dropped[:50]}...' (total dropped: {self._dropped_messages})"
                )
                self._receive_buffer.put_nowait(stripped)
            except asyncio.QueueEmpty:
                pass

    def clear_buffer(self) -> None:
        """Clear the receive buffer."""
        while not self._receive_buffer.empty():
            try:
                self._receive_buffer.get_nowait()
            except asyncio.QueueEmpty:
                break

    @property
    def buffer_size(self) -> int:
        """Return current number of messages in the receive buffer."""
        return self._receive_buffer.qsize()

    @property
    def dropped_message_count(self) -> int:
        """Return total number of messages dropped due to buffer overflow."""
        return self._dropped_messages

    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()
        return False
