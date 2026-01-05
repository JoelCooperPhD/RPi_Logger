"""Unit test fixtures for isolated, fast test execution.

This conftest provides fixtures specifically for unit tests that:
- Run in complete isolation (no external dependencies)
- Execute quickly (< 1s per test)
- Use mocks for all hardware and I/O operations

Fixtures in this file complement (not duplicate) the root conftest.py fixtures.
The root conftest provides:
- project_root, test_data_dir
- sample CSV path fixtures (sample_gps_csv, etc.)
- Basic mock device fixtures (mock_serial_device, mock_gps_device, etc.)

This file provides:
- Isolated environment fixtures (isolated_env, temp_work_dir)
- Mock factory fixtures for creating customized mocks
- Async test support fixtures
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, Generator, Optional, Type
from unittest.mock import MagicMock, patch

import pytest


# =============================================================================
# Isolated Environment Fixtures
# =============================================================================

@pytest.fixture(scope="function")
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a completely isolated test environment.

    This fixture provides:
    - A clean temporary directory as the working directory
    - Isolated environment variables (HOME, XDG paths, etc.)
    - Clean sys.path (project root only)

    Scope: function (fresh environment per test)

    Args:
        tmp_path: pytest's temporary directory fixture
        monkeypatch: pytest's monkeypatch fixture

    Returns:
        Path to the isolated working directory

    Example:
        def test_creates_config_file(isolated_env):
            config_path = isolated_env / "config.json"
            # Test code that creates files will use isolated_env
    """
    # Set up isolated directory structure
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    config_dir = tmp_path / "config"
    config_dir.mkdir()

    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # Isolate environment variables
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_dir))
    monkeypatch.setenv("XDG_DATA_HOME", str(data_dir))
    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))

    # Create tmp directory
    (tmp_path / "tmp").mkdir()

    # Change to isolated working directory
    original_cwd = os.getcwd()
    os.chdir(work_dir)

    yield work_dir

    # Restore original working directory
    os.chdir(original_cwd)


@pytest.fixture(scope="function")
def temp_work_dir(tmp_path: Path) -> Generator[Path, None, None]:
    """Provide a temporary working directory for file operations.

    Simpler than isolated_env - just provides a clean temp directory
    without modifying environment variables.

    Scope: function (fresh directory per test)

    Args:
        tmp_path: pytest's temporary directory fixture

    Yields:
        Path to the temporary working directory

    Example:
        def test_writes_output_file(temp_work_dir):
            output = temp_work_dir / "output.csv"
            write_data(output)
            assert output.exists()
    """
    work_dir = tmp_path / "test_work"
    work_dir.mkdir()
    yield work_dir


@pytest.fixture(scope="function")
def temp_output_dir(tmp_path: Path) -> Path:
    """Provide a temporary directory for test outputs.

    Use this when testing code that writes CSV files, logs, or other outputs.

    Scope: function

    Args:
        tmp_path: pytest's temporary directory fixture

    Returns:
        Path to the output directory
    """
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    return output_dir


# =============================================================================
# Mock Factory Fixtures
# =============================================================================

@pytest.fixture(scope="function")
def mock_serial_factory() -> Callable[..., MagicMock]:
    """Factory for creating customized mock serial ports.

    Creates mock serial.Serial instances with configurable behavior.
    Use this when you need mocks with specific responses or behaviors
    beyond what MockSerialDevice provides.

    Scope: function

    Returns:
        Factory function that creates configured mock serial ports

    Example:
        def test_custom_serial(mock_serial_factory):
            mock = mock_serial_factory(
                port="/dev/ttyUSB0",
                baudrate=115200,
                read_data=b"RESPONSE\\n"
            )
            assert mock.read() == b"RESPONSE\\n"
    """
    def factory(
        port: str = "/dev/ttyMOCK",
        baudrate: int = 9600,
        timeout: float = 1.0,
        read_data: Optional[bytes] = None,
        is_open: bool = True,
    ) -> MagicMock:
        mock = MagicMock()
        mock.port = port
        mock.baudrate = baudrate
        mock.timeout = timeout
        mock.is_open = is_open

        if read_data is not None:
            mock.read.return_value = read_data
            mock.readline.return_value = read_data
        else:
            mock.read.return_value = b""
            mock.readline.return_value = b""

        mock.write.return_value = 0
        mock.in_waiting = 0

        return mock

    return factory


@pytest.fixture(scope="function")
def mock_audio_factory() -> Callable[..., MagicMock]:
    """Factory for creating customized mock audio devices.

    Creates mock sounddevice instances with configurable behavior.

    Scope: function

    Returns:
        Factory function that creates configured mock audio devices

    Example:
        def test_custom_audio(mock_audio_factory):
            mock = mock_audio_factory(
                sample_rate=44100,
                channels=2,
                device_name="Test Mic"
            )
    """
    def factory(
        sample_rate: float = 48000.0,
        channels: int = 2,
        device_name: str = "Mock Audio Device",
        device_index: int = 0,
    ) -> MagicMock:
        mock = MagicMock()
        mock.sample_rate = sample_rate
        mock.channels = channels
        mock.device = {
            "name": device_name,
            "index": device_index,
            "max_input_channels": channels,
            "max_output_channels": 0,
            "default_samplerate": sample_rate,
        }
        return mock

    return factory


@pytest.fixture(scope="function")
def mock_camera_factory() -> Callable[..., MagicMock]:
    """Factory for creating customized mock camera devices.

    Creates mock camera instances with configurable resolution and FPS.

    Scope: function

    Returns:
        Factory function that creates configured mock cameras

    Example:
        def test_custom_camera(mock_camera_factory):
            mock = mock_camera_factory(
                width=1920,
                height=1080,
                fps=30
            )
            ret, frame = mock.read()
            assert ret is True
    """
    def factory(
        width: int = 1920,
        height: int = 1080,
        fps: float = 30.0,
        device_path: str = "/dev/video0",
        is_opened: bool = True,
    ) -> MagicMock:
        import numpy as np

        mock = MagicMock()
        mock.isOpened.return_value = is_opened
        mock.get.side_effect = lambda prop_id: {
            3: float(width),    # CAP_PROP_FRAME_WIDTH
            4: float(height),   # CAP_PROP_FRAME_HEIGHT
            5: float(fps),      # CAP_PROP_FPS
        }.get(prop_id, 0.0)

        # Generate a simple test frame
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        mock.read.return_value = (is_opened, frame if is_opened else None)

        return mock

    return factory


# =============================================================================
# Patch Context Fixtures
# =============================================================================

@pytest.fixture(scope="function")
def patch_serial() -> Generator[MagicMock, None, None]:
    """Patch serial.Serial for the duration of the test.

    Use this when you need to prevent any actual serial port access.

    Scope: function

    Yields:
        The patched Serial class

    Example:
        def test_no_serial_access(patch_serial):
            # Any code that imports serial.Serial will get the mock
            patch_serial.return_value.read.return_value = b"test"
    """
    with patch("serial.Serial") as mock_serial:
        mock_serial.return_value.is_open = True
        mock_serial.return_value.read.return_value = b""
        mock_serial.return_value.readline.return_value = b""
        yield mock_serial


@pytest.fixture(scope="function")
def patch_sounddevice() -> Generator[MagicMock, None, None]:
    """Patch sounddevice module for the duration of the test.

    Use this when you need to prevent any actual audio device access.

    Scope: function

    Yields:
        The patched sounddevice module

    Example:
        def test_no_audio_access(patch_sounddevice):
            patch_sounddevice.query_devices.return_value = []
    """
    with patch.dict(sys.modules, {"sounddevice": MagicMock()}) as modules:
        mock_sd = modules["sounddevice"]
        mock_sd.query_devices.return_value = []
        mock_sd.default = (0, 0)
        yield mock_sd


@pytest.fixture(scope="function")
def patch_cv2() -> Generator[MagicMock, None, None]:
    """Patch cv2 module for the duration of the test.

    Use this when you need to prevent any actual camera/OpenCV access.

    Scope: function

    Yields:
        The patched cv2 module

    Example:
        def test_no_camera_access(patch_cv2):
            patch_cv2.VideoCapture.return_value.isOpened.return_value = True
    """
    import numpy as np

    with patch.dict(sys.modules, {"cv2": MagicMock()}) as modules:
        mock_cv2 = modules["cv2"]
        mock_capture = MagicMock()
        mock_capture.isOpened.return_value = True
        mock_capture.read.return_value = (True, np.zeros((480, 640, 3), dtype=np.uint8))
        mock_cv2.VideoCapture.return_value = mock_capture
        yield mock_cv2


# =============================================================================
# Time Control Fixtures
# =============================================================================

@pytest.fixture(scope="function")
def frozen_time() -> Generator[Callable[[float], None], None, None]:
    """Fixture to control time.time() return value.

    Use this when testing time-dependent code without actual delays.

    Scope: function

    Yields:
        Function to set the frozen time value

    Example:
        def test_timestamp_handling(frozen_time):
            frozen_time(1000.0)  # Set time to 1000.0
            result = get_timestamp()
            assert result == 1000.0

            frozen_time(1001.0)  # Advance time
            result = get_timestamp()
            assert result == 1001.0
    """
    frozen_value = [0.0]

    def set_time(value: float) -> None:
        frozen_value[0] = value

    def get_frozen_time() -> float:
        return frozen_value[0]

    with patch("time.time", side_effect=get_frozen_time):
        yield set_time


@pytest.fixture(scope="function")
def mock_monotonic() -> Generator[Callable[[float], None], None, None]:
    """Fixture to control time.monotonic() return value.

    Use this when testing code that uses monotonic timestamps.

    Scope: function

    Yields:
        Function to set the monotonic time value

    Example:
        def test_monotonic_timing(mock_monotonic):
            mock_monotonic(0.0)
            start = get_mono_time()
            mock_monotonic(1.5)
            elapsed = get_mono_time() - start
            assert elapsed == 1.5
    """
    mono_value = [0.0]

    def set_mono(value: float) -> None:
        mono_value[0] = value

    def get_mono() -> float:
        return mono_value[0]

    with patch("time.monotonic", side_effect=get_mono):
        yield set_mono


# =============================================================================
# Data Generation Fixtures
# =============================================================================

@pytest.fixture(scope="function")
def nmea_generator() -> Callable[..., bytes]:
    """Fixture providing NMEA sentence generator.

    Generates valid NMEA sentences for GPS testing.

    Scope: function

    Returns:
        Function to generate NMEA sentences

    Example:
        def test_nmea_parsing(nmea_generator):
            sentence = nmea_generator(
                sentence_type="GPGGA",
                lat=48.1173,
                lon=11.5167
            )
            result = parse_nmea(sentence)
            assert result.latitude == pytest.approx(48.1173, rel=1e-4)
    """
    def generate(
        sentence_type: str = "GPGGA",
        lat: float = 48.1173,
        lon: float = 11.5167,
        alt: float = 545.4,
        fix_quality: int = 1,
        satellites: int = 8,
        time_str: str = "123519",
    ) -> bytes:
        """Generate an NMEA sentence with checksum."""
        if sentence_type == "GPGGA":
            # Convert lat/lon to NMEA format
            lat_deg = int(abs(lat))
            lat_min = (abs(lat) - lat_deg) * 60
            lat_dir = "N" if lat >= 0 else "S"
            lat_str = f"{lat_deg:02d}{lat_min:07.4f}"

            lon_deg = int(abs(lon))
            lon_min = (abs(lon) - lon_deg) * 60
            lon_dir = "E" if lon >= 0 else "W"
            lon_str = f"{lon_deg:03d}{lon_min:07.4f}"

            sentence = f"GPGGA,{time_str},{lat_str},{lat_dir},{lon_str},{lon_dir},{fix_quality},{satellites:02d},0.9,{alt:.1f},M,47.0,M,,"
        elif sentence_type == "GPRMC":
            lat_deg = int(abs(lat))
            lat_min = (abs(lat) - lat_deg) * 60
            lat_dir = "N" if lat >= 0 else "S"
            lat_str = f"{lat_deg:02d}{lat_min:07.4f}"

            lon_deg = int(abs(lon))
            lon_min = (abs(lon) - lon_deg) * 60
            lon_dir = "E" if lon >= 0 else "W"
            lon_str = f"{lon_deg:03d}{lon_min:07.4f}"

            sentence = f"GPRMC,{time_str},A,{lat_str},{lat_dir},{lon_str},{lon_dir},022.4,084.4,230394,003.1,W"
        else:
            raise ValueError(f"Unknown sentence type: {sentence_type}")

        # Calculate checksum
        checksum = 0
        for char in sentence:
            checksum ^= ord(char)

        return f"${sentence}*{checksum:02X}\r\n".encode()

    return generate


@pytest.fixture(scope="function")
def csv_row_generator() -> Callable[..., Dict[str, Any]]:
    """Fixture providing CSV row data generator.

    Generates valid CSV row data matching Logger schemas.

    Scope: function

    Returns:
        Function to generate CSV row dictionaries

    Example:
        def test_csv_writing(csv_row_generator):
            row = csv_row_generator(
                module="GPS",
                trial=1,
                latitude=48.1173
            )
            write_csv_row(output_file, row)
    """
    import time

    def generate(
        module: str = "GPS",
        trial: int = 1,
        device_id: str = "test_device",
        label: str = "test",
        **extra_fields: Any
    ) -> Dict[str, Any]:
        """Generate a CSV row dictionary with standard prefix."""
        current_time = time.time()

        row = {
            "trial": trial,
            "module": module,
            "device_id": device_id,
            "label": label,
            "record_time_unix": current_time,
            "record_time_mono": current_time,  # Simplified for testing
        }
        row.update(extra_fields)
        return row

    return generate
