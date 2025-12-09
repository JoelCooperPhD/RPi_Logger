"""Unit tests for GPS serial transport."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from rpi_logger.modules.GPS.gps_core.transports.serial_transport import (
    SerialGPSTransport,
    SERIAL_AVAILABLE,
)
from rpi_logger.modules.GPS.gps_core.transports.base_transport import BaseGPSTransport


class TestBaseGPSTransport:
    """Test the abstract base transport interface."""

    def test_interface_defined(self):
        """Test that BaseGPSTransport defines the expected interface."""
        assert hasattr(BaseGPSTransport, "connect")
        assert hasattr(BaseGPSTransport, "disconnect")
        assert hasattr(BaseGPSTransport, "read_line")
        assert hasattr(BaseGPSTransport, "is_connected")


class TestSerialGPSTransport:
    """Test the serial transport implementation."""

    def test_initialization(self):
        """Test transport initialization."""
        transport = SerialGPSTransport("/dev/serial0", 9600)
        assert transport.port == "/dev/serial0"
        assert transport.baudrate == 9600
        assert transport.is_connected is False

    def test_default_baudrate(self):
        """Test default baudrate is 9600."""
        transport = SerialGPSTransport("/dev/serial0")
        assert transport.baudrate == 9600

    def test_is_connected_initially_false(self):
        """Test that transport starts disconnected."""
        transport = SerialGPSTransport("/dev/serial0")
        assert transport.is_connected is False
        assert transport.last_error is None

    @pytest.mark.asyncio
    async def test_connect_success(self):
        """Test successful connection."""
        if not SERIAL_AVAILABLE:
            pytest.skip("serial_asyncio not available")

        with patch("rpi_logger.modules.GPS.gps_core.transports.serial_transport.serial_asyncio") as mock_serial:
            mock_reader = AsyncMock()
            mock_writer = MagicMock()
            mock_serial.open_serial_connection = AsyncMock(return_value=(mock_reader, mock_writer))

            transport = SerialGPSTransport("/dev/serial0", 9600)
            result = await transport.connect()

            assert result is True
            assert transport.is_connected is True
            mock_serial.open_serial_connection.assert_called_once_with(
                url="/dev/serial0",
                baudrate=9600,
            )

    @pytest.mark.asyncio
    async def test_connect_failure(self):
        """Test connection failure handling."""
        if not SERIAL_AVAILABLE:
            pytest.skip("serial_asyncio not available")

        with patch("rpi_logger.modules.GPS.gps_core.transports.serial_transport.serial_asyncio") as mock_serial:
            mock_serial.open_serial_connection = AsyncMock(side_effect=OSError("Device not found"))

            transport = SerialGPSTransport("/dev/serial0", 9600)
            result = await transport.connect()

            assert result is False
            assert transport.is_connected is False
            assert "Device not found" in transport.last_error

    @pytest.mark.asyncio
    async def test_disconnect(self):
        """Test disconnection."""
        if not SERIAL_AVAILABLE:
            pytest.skip("serial_asyncio not available")

        with patch("rpi_logger.modules.GPS.gps_core.transports.serial_transport.serial_asyncio") as mock_serial:
            mock_reader = AsyncMock()
            mock_writer = MagicMock()
            mock_writer.close = MagicMock()
            mock_writer.wait_closed = AsyncMock()
            mock_serial.open_serial_connection = AsyncMock(return_value=(mock_reader, mock_writer))

            transport = SerialGPSTransport("/dev/serial0", 9600)
            await transport.connect()
            assert transport.is_connected is True

            await transport.disconnect()
            assert transport.is_connected is False
            mock_writer.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_read_line_success(self):
        """Test successful line reading."""
        if not SERIAL_AVAILABLE:
            pytest.skip("serial_asyncio not available")

        with patch("rpi_logger.modules.GPS.gps_core.transports.serial_transport.serial_asyncio") as mock_serial:
            mock_reader = AsyncMock()
            mock_reader.readline = AsyncMock(return_value=b"$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,47.0,M,,*47\r\n")
            mock_writer = MagicMock()
            mock_serial.open_serial_connection = AsyncMock(return_value=(mock_reader, mock_writer))

            transport = SerialGPSTransport("/dev/serial0", 9600)
            await transport.connect()

            line = await transport.read_line()
            assert line == "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,47.0,M,,*47"

    @pytest.mark.asyncio
    async def test_read_line_timeout(self):
        """Test read timeout handling."""
        if not SERIAL_AVAILABLE:
            pytest.skip("serial_asyncio not available")

        with patch("rpi_logger.modules.GPS.gps_core.transports.serial_transport.serial_asyncio") as mock_serial:
            mock_reader = AsyncMock()
            # Simulate timeout by raising asyncio.TimeoutError
            mock_reader.readline = AsyncMock(side_effect=asyncio.TimeoutError())
            mock_writer = MagicMock()
            mock_serial.open_serial_connection = AsyncMock(return_value=(mock_reader, mock_writer))

            transport = SerialGPSTransport("/dev/serial0", 9600)
            await transport.connect()

            # Mock wait_for to immediately raise TimeoutError
            with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()):
                line = await transport.read_line()
                assert line is None

    @pytest.mark.asyncio
    async def test_read_line_not_connected(self):
        """Test read when not connected returns None."""
        transport = SerialGPSTransport("/dev/serial0", 9600)
        line = await transport.read_line()
        assert line is None

    @pytest.mark.asyncio
    async def test_read_sentences_generator(self):
        """Test the read_sentences async generator."""
        if not SERIAL_AVAILABLE:
            pytest.skip("serial_asyncio not available")

        with patch("rpi_logger.modules.GPS.gps_core.transports.serial_transport.serial_asyncio") as mock_serial:
            sentences = [
                b"$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,47.0,M,,*47\r\n",
                b"$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A\r\n",
                b"",  # Empty line - will cause EOF detection
            ]
            call_count = 0

            async def mock_readline():
                nonlocal call_count
                if call_count < len(sentences):
                    result = sentences[call_count]
                    call_count += 1
                    return result
                return b""  # EOF

            mock_reader = AsyncMock()
            mock_reader.readline = mock_readline
            mock_writer = MagicMock()
            mock_serial.open_serial_connection = AsyncMock(return_value=(mock_reader, mock_writer))

            transport = SerialGPSTransport("/dev/serial0", 9600)
            await transport.connect()

            collected = []
            async for sentence in transport.read_sentences():
                collected.append(sentence)
                if len(collected) >= 2:
                    break

            assert len(collected) == 2
            assert collected[0].startswith("$GPGGA")
            assert collected[1].startswith("$GPRMC")

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager protocol."""
        if not SERIAL_AVAILABLE:
            pytest.skip("serial_asyncio not available")

        with patch("rpi_logger.modules.GPS.gps_core.transports.serial_transport.serial_asyncio") as mock_serial:
            mock_reader = AsyncMock()
            mock_writer = MagicMock()
            mock_writer.close = MagicMock()
            mock_writer.wait_closed = AsyncMock()
            mock_serial.open_serial_connection = AsyncMock(return_value=(mock_reader, mock_writer))

            async with SerialGPSTransport("/dev/serial0", 9600) as transport:
                assert transport.is_connected is True

            # After context exit, should be disconnected
            assert transport.is_connected is False


class TestSerialUnavailable:
    """Test behavior when serial module is not available."""

    @pytest.mark.asyncio
    async def test_connect_without_serial(self):
        """Test that connect fails gracefully when serial is unavailable."""
        # Temporarily make serial unavailable
        with patch("rpi_logger.modules.GPS.gps_core.transports.serial_transport.SERIAL_AVAILABLE", False):
            with patch("rpi_logger.modules.GPS.gps_core.transports.serial_transport.SERIAL_IMPORT_ERROR", ImportError("No module")):
                transport = SerialGPSTransport("/dev/serial0", 9600)
                result = await transport.connect()

                assert result is False
                assert transport.is_connected is False
                assert "not available" in transport.last_error
