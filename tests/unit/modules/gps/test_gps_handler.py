"""Unit tests for GPS handler."""

import asyncio
from pathlib import Path
from typing import AsyncIterator, Optional
import pytest

from rpi_logger.modules.GPS.gps_core.handlers.gps_handler import GPSHandler
from rpi_logger.modules.GPS.gps_core.handlers.base_handler import BaseGPSHandler
from rpi_logger.modules.GPS.gps_core.transports import BaseGPSTransport
from rpi_logger.modules.GPS.gps_core.parsers.nmea_types import GPSFixSnapshot


def run_async(coro):
    """Run async coroutine synchronously for testing."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class MockTransport(BaseGPSTransport):
    """Mock transport that yields predefined sentences."""

    def __init__(self, sentences: list[str]):
        super().__init__()
        self._sentences = sentences
        self._index = 0

    async def connect(self) -> bool:
        self._connected = True
        return True

    async def disconnect(self) -> None:
        self._connected = False

    async def read_line(self, timeout: float = 1.0) -> Optional[str]:
        if self._index < len(self._sentences):
            sentence = self._sentences[self._index]
            self._index += 1
            await asyncio.sleep(0.01)  # Simulate I/O delay
            return sentence
        # Return None after all sentences are consumed
        return None


class TestBaseGPSHandler:
    """Test the base handler interface."""

    def test_initialization(self, tmp_path):
        """Test handler initialization."""
        transport = MockTransport([])
        handler = GPSHandler("GPS:test", tmp_path, transport)

        assert handler.device_id == "GPS:test"
        assert handler.output_dir == tmp_path
        assert handler.is_running is False
        assert handler.is_recording is False
        assert handler.fix is not None

    def test_fix_property(self, tmp_path):
        """Test that fix property returns parser's fix."""
        transport = MockTransport([])
        handler = GPSHandler("GPS:test", tmp_path, transport)

        assert isinstance(handler.fix, GPSFixSnapshot)
        assert handler.fix.latitude is None


class TestGPSHandler:
    """Test GPS handler functionality."""

    def test_start_stop(self, tmp_path):
        """Test starting and stopping the handler."""
        async def _test():
            transport = MockTransport([])
            await transport.connect()

            handler = GPSHandler("GPS:test", tmp_path, transport)
            assert handler.is_running is False

            await handler.start()
            assert handler.is_running is True

            await handler.stop()
            assert handler.is_running is False
        run_async(_test())

    def test_start_twice(self, tmp_path):
        """Test that starting twice is a no-op."""
        async def _test():
            transport = MockTransport([])
            await transport.connect()

            handler = GPSHandler("GPS:test", tmp_path, transport)
            await handler.start()
            await handler.start()  # Should not raise

            assert handler.is_running is True
            await handler.stop()
        run_async(_test())

    def test_processes_nmea_sentences(self, tmp_path):
        """Test that handler processes NMEA sentences."""
        async def _test():
            sentences = [
                "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,47.0,M,,*4F",
                "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A",
            ]
            transport = MockTransport(sentences)
            await transport.connect()

            handler = GPSHandler("GPS:test", tmp_path, transport)
            await handler.start()

            # Wait for sentences to be processed
            await asyncio.sleep(0.1)

            await handler.stop()

            # Check fix was updated
            assert handler.fix.latitude == pytest.approx(48.1173, rel=1e-4)
            assert handler.fix.longitude == pytest.approx(11.5166, rel=1e-4)
        run_async(_test())

    def test_data_callback(self, tmp_path):
        """Test that data callback is invoked."""
        async def _test():
            sentences = [
                "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,47.0,M,,*4F",
            ]
            transport = MockTransport(sentences)
            await transport.connect()

            callback_data = []

            async def callback(device_id, fix, update):
                callback_data.append((device_id, fix.copy(), update.copy()))

            handler = GPSHandler("GPS:test", tmp_path, transport)
            handler.data_callback = callback
            await handler.start()

            await asyncio.sleep(0.3)
            await handler.stop()

            assert len(callback_data) >= 1
            device_id, fix, update = callback_data[0]
            assert device_id == "GPS:test"
            assert fix.latitude is not None
            assert update["sentence_type"] == "GGA"
        run_async(_test())

    def test_recording(self, tmp_path):
        """Test recording functionality."""
        async def _test():
            sentences = [
                "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,47.0,M,,*4F",
            ]
            transport = MockTransport(sentences)
            await transport.connect()

            handler = GPSHandler("GPS:test", tmp_path, transport)

            # Start recording
            result = handler.start_recording(trial_number=1)
            assert result is True
            assert handler.is_recording is True

            # Process some data
            await handler.start()
            await asyncio.sleep(0.1)
            await handler.stop()

            # Stop recording
            handler.stop_recording()
            assert handler.is_recording is False

            # Check that CSV file was created
            csv_files = list(tmp_path.glob("*.csv"))
            assert len(csv_files) == 1
        run_async(_test())

    def test_update_trial_number(self, tmp_path):
        """Test updating trial number."""
        async def _test():
            transport = MockTransport([])
            handler = GPSHandler("GPS:test", tmp_path, transport)

            handler.start_recording(trial_number=1)
            handler.update_trial_number(5)
            handler.stop_recording()

            # Should not raise
        run_async(_test())

    def test_update_output_dir(self, tmp_path):
        """Test updating output directory."""
        async def _test():
            transport = MockTransport([])
            handler = GPSHandler("GPS:test", tmp_path, transport)

            new_dir = tmp_path / "new_output"
            handler.update_output_dir(new_dir)

            assert handler.output_dir == new_dir
        run_async(_test())

    def test_first_fix_logging(self, tmp_path):
        """Test that first valid fix is logged."""
        async def _test():
            sentences = [
                # Invalid fix first (fix_quality=0)
                "$GPGGA,123519,4807.038,N,01131.000,E,0,00,0.0,0.0,M,0.0,M,,*7C",
                # Then valid fix (fix_quality=1)
                "$GPGGA,123520,4807.038,N,01131.000,E,1,08,0.9,545.4,M,47.0,M,,*45",
            ]
            transport = MockTransport(sentences)
            await transport.connect()

            handler = GPSHandler("GPS:test", tmp_path, transport)
            assert handler._logged_first_fix is False

            await handler.start()
            await asyncio.sleep(0.3)
            await handler.stop()

            assert handler._logged_first_fix is True
        run_async(_test())

    def test_reset_first_fix_logged(self, tmp_path):
        """Test resetting first fix flag."""
        async def _test():
            transport = MockTransport([])
            handler = GPSHandler("GPS:test", tmp_path, transport)

            handler._logged_first_fix = True
            handler.reset_first_fix_logged()
            assert handler._logged_first_fix is False
        run_async(_test())


class TestHandlerErrorRecovery:
    """Test error recovery and circuit breaker."""

    def test_recovers_from_timeout(self, tmp_path):
        """Test that handler recovers from read timeouts."""
        async def _test():
            # Transport that returns None (timeout)
            transport = MockTransport([])
            await transport.connect()

            handler = GPSHandler("GPS:test", tmp_path, transport)
            await handler.start()

            # Should continue running despite timeouts
            await asyncio.sleep(0.2)
            assert handler.is_running is True

            await handler.stop()
        run_async(_test())

    def test_stop_cleans_up_tasks(self, tmp_path):
        """Test that stop cancels pending tasks."""
        async def _test():
            sentences = [
                "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,47.0,M,,*4F",
            ]
            transport = MockTransport(sentences)
            await transport.connect()

            handler = GPSHandler("GPS:test", tmp_path, transport)
            handler.data_callback = lambda *args: asyncio.sleep(10)  # Long callback

            await handler.start()
            await asyncio.sleep(0.05)
            await handler.stop()

            # Should complete without hanging
            assert handler.is_running is False
        run_async(_test())
