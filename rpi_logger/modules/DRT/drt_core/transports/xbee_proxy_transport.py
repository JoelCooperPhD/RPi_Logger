"""
XBee Proxy Transport

Transport that proxies XBee communication through the command protocol.
Used when the XBee coordinator lives in the main logger process and this
module runs as a subprocess.

Data flow:
- Incoming: Main logger sends xbee_data commands -> runtime pushes to this transport
- Outgoing: This transport sends via callback -> runtime sends xbee_send status
"""

import asyncio
import logging
from typing import Optional, Callable, Awaitable

from .base_transport import BaseTransport

logger = logging.getLogger(__name__)


class XBeeProxyTransport(BaseTransport):
    """
    Proxy transport for XBee communication via command protocol.

    Data is received via push from the runtime (which gets it from
    xbee_data commands), and sends are requested via callback (which
    the runtime forwards as xbee_send status messages).
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
            node_id: Device node ID (e.g., "wDRT_01")
            send_callback: Async callback to send data (node_id, data) -> success
        """
        super().__init__()
        self.node_id = node_id
        self._send_callback = send_callback

        # Receive buffer - asyncio Queue for async/await compatibility
        self._receive_buffer: asyncio.Queue[str] = asyncio.Queue(maxsize=self.MAX_BUFFER_SIZE)
        self._dropped_messages = 0

    @property
    def device_id(self) -> str:
        """Return the device identifier (node ID)."""
        return self.node_id

    async def connect(self) -> bool:
        """Mark transport as connected."""
        self._connected = True
        logger.info("XBee proxy transport ready for %s", self.node_id)
        return True

    async def disconnect(self) -> None:
        """Mark transport as disconnected and clear buffer."""
        self._connected = False
        while not self._receive_buffer.empty():
            try:
                self._receive_buffer.get_nowait()
            except asyncio.QueueEmpty:
                break
        logger.info("XBee proxy transport disconnected for %s", self.node_id)

    async def write(self, data: bytes) -> bool:
        """Send data via the proxy callback."""
        if not self._connected:
            logger.error("Cannot write to %s: not connected", self.node_id)
            return False

        try:
            data_str = data.decode('utf-8', errors='replace').strip()
            logger.debug("XBee proxy sending to %s: '%s'", self.node_id, data_str)
            return await self._send_callback(self.node_id, data_str)
        except Exception as e:
            logger.error("XBee proxy write error to %s: %s", self.node_id, e)
            return False

    async def read_line(self) -> Optional[str]:
        """Read from the receive buffer (non-blocking)."""
        try:
            return self._receive_buffer.get_nowait()
        except asyncio.QueueEmpty:
            return None

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
                "XBee proxy buffered for %s: '%s' (queue size: %d)",
                self.node_id, stripped, self._receive_buffer.qsize()
            )
        except asyncio.QueueFull:
            try:
                dropped = self._receive_buffer.get_nowait()
                self._dropped_messages += 1
                logger.warning(
                    "Receive buffer full for %s, dropped: '%s...' (total dropped: %d)",
                    self.node_id, dropped[:50], self._dropped_messages
                )
                self._receive_buffer.put_nowait(stripped)
            except asyncio.QueueEmpty:
                pass
