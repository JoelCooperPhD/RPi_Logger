"""End-to-end test fixtures for hardware-dependent testing.

This conftest provides fixtures specifically for E2E tests that:
- Require physical hardware (GPS, DRT, VOG, cameras, etc.)
- Test complete workflows from device to file output
- Need automatic skip behavior when hardware is unavailable

Fixtures in this file complement (not duplicate) the root conftest.py fixtures.
The root conftest provides:
- project_root, test_data_dir
- --run-hardware command line option
- pytest.mark.hardware marker

This file provides:
- Hardware detection fixtures for specific device types
- Skip markers for specific hardware (@pytest.mark.gps, @pytest.mark.drt, etc.)
- Device cleanup fixtures for proper resource management
- Recording output directory fixtures
- pytest hooks for auto-skip behavior
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple

import pytest

# Import hardware detection from infrastructure
from tests.infrastructure.schemas.hardware_detection import (
    HardwareAvailability,
    get_hardware_availability,
    DeviceType,
    DeviceInfo,
    ModuleAvailability,
)


# =============================================================================
# Pytest Hooks for Custom Markers and Auto-Skip
# =============================================================================

def pytest_configure(config):
    """Configure custom pytest markers for E2E hardware tests.

    This hook registers custom markers for each hardware type:
    - @pytest.mark.hardware - marks tests requiring any hardware
    - @pytest.mark.gps - marks tests requiring GPS hardware
    - @pytest.mark.drt - marks tests requiring DRT device
    - @pytest.mark.vog - marks tests requiring VOG device
    - @pytest.mark.cameras - marks tests requiring USB cameras
    - @pytest.mark.audio - marks tests requiring audio input
    - @pytest.mark.eyetracker - marks tests requiring Pupil Labs Neon
    """
    # Register hardware-specific markers
    config.addinivalue_line(
        "markers", "gps: mark test as requiring GPS hardware"
    )
    config.addinivalue_line(
        "markers", "drt: mark test as requiring DRT device"
    )
    config.addinivalue_line(
        "markers", "vog: mark test as requiring VOG device"
    )
    config.addinivalue_line(
        "markers", "cameras: mark test as requiring USB cameras"
    )
    config.addinivalue_line(
        "markers", "audio: mark test as requiring audio input device"
    )
    config.addinivalue_line(
        "markers", "eyetracker: mark test as requiring Pupil Labs Neon eye tracker"
    )
    config.addinivalue_line(
        "markers", "csi_cameras: mark test as requiring Raspberry Pi CSI cameras"
    )


def pytest_collection_modifyitems(config, items):
    """Auto-skip hardware tests when hardware is unavailable.

    This hook runs during test collection and:
    1. Detects available hardware using HardwareAvailability
    2. For each test with a hardware marker, checks if required hardware is present
    3. Adds skip marker to tests where hardware is unavailable

    The --run-hardware flag from root conftest.py is respected - if not provided,
    all hardware tests are skipped. If provided, only tests for available
    hardware will run.
    """
    # Check if --run-hardware flag is provided
    run_hardware = config.getoption("--run-hardware", default=False)
    if not run_hardware:
        # Let root conftest.py handle this - skip all hardware tests
        return

    # Detect available hardware (cached at module level)
    hw = get_hardware_availability()

    # Map markers to module names in HardwareAvailability
    marker_to_module = {
        "gps": "GPS",
        "drt": "DRT",
        "vog": "VOG",
        "cameras": "Cameras",
        "audio": "Audio",
        "eyetracker": "EyeTracker",
        "csi_cameras": "CSICameras",
    }

    for item in items:
        # Check each hardware-specific marker
        for marker_name, module_name in marker_to_module.items():
            if marker_name in item.keywords:
                avail = hw.get_availability(module_name)
                if not avail.available:
                    skip_marker = pytest.mark.skip(
                        reason=f"{module_name} hardware not available: {avail.reason}"
                    )
                    item.add_marker(skip_marker)


# =============================================================================
# Hardware Detection Fixtures
# =============================================================================

@pytest.fixture(scope="session")
def hardware_availability():
    """Provide hardware availability detection.

    Detects all available hardware at session start and caches results.
    Use this to check hardware availability before running tests.

    Scope: session (detected once, shared across all tests)

    Returns:
        HardwareAvailability instance with detection results

    Example:
        def test_requires_gps(hardware_availability):
            if not hardware_availability.is_available("GPS"):
                pytest.skip("GPS hardware not available")
            # Run GPS test...
    """
    hw = HardwareAvailability()
    hw.detect_all()
    return hw


@pytest.fixture(scope="session")
def gps_available(hardware_availability) -> bool:
    """Check if GPS hardware is available.

    Scope: session

    Args:
        hardware_availability: Hardware detection fixture

    Returns:
        True if GPS hardware is detected and available
    """
    return hardware_availability.is_available("GPS")


@pytest.fixture(scope="session")
def drt_available(hardware_availability) -> bool:
    """Check if DRT hardware is available.

    Scope: session

    Args:
        hardware_availability: Hardware detection fixture

    Returns:
        True if DRT hardware is detected and available
    """
    return hardware_availability.is_available("DRT")


@pytest.fixture(scope="session")
def vog_available(hardware_availability) -> bool:
    """Check if VOG hardware is available.

    Scope: session

    Args:
        hardware_availability: Hardware detection fixture

    Returns:
        True if VOG hardware is detected and available
    """
    return hardware_availability.is_available("VOG")


@pytest.fixture(scope="session")
def cameras_available(hardware_availability) -> bool:
    """Check if USB camera hardware is available.

    Scope: session

    Args:
        hardware_availability: Hardware detection fixture

    Returns:
        True if USB cameras are detected and available
    """
    return hardware_availability.is_available("Cameras")


@pytest.fixture(scope="session")
def audio_available(hardware_availability) -> bool:
    """Check if audio input hardware is available.

    Scope: session

    Args:
        hardware_availability: Hardware detection fixture

    Returns:
        True if audio input devices are detected and available
    """
    return hardware_availability.is_available("Audio")


@pytest.fixture(scope="session")
def eyetracker_available(hardware_availability) -> bool:
    """Check if Pupil Labs Neon eye tracker is available.

    Scope: session

    Args:
        hardware_availability: Hardware detection fixture

    Returns:
        True if eye tracker is detected and available
    """
    return hardware_availability.is_available("EyeTracker")


@pytest.fixture(scope="session")
def available_modules(hardware_availability) -> List[str]:
    """Provide list of modules with available hardware.

    Scope: session

    Args:
        hardware_availability: Hardware detection fixture

    Returns:
        List of module names that can be tested with real hardware

    Example:
        def test_available_modules(available_modules):
            print(f"Can test: {available_modules}")
    """
    return hardware_availability.get_testable_modules()


@pytest.fixture(scope="session")
def unavailable_modules(hardware_availability) -> List[str]:
    """Provide list of modules without available hardware.

    Scope: session

    Args:
        hardware_availability: Hardware detection fixture

    Returns:
        List of module names that cannot be tested (no hardware)

    Example:
        def test_skip_unavailable(unavailable_modules):
            if "GPS" in unavailable_modules:
                pytest.skip("GPS hardware not available")
    """
    return hardware_availability.get_untestable_modules()


@pytest.fixture(scope="session", autouse=True)
def print_hardware_matrix(hardware_availability, request):
    """Print hardware availability matrix at start of E2E test session.

    This fixture runs automatically at session start and prints
    a summary of available hardware for debugging.

    Scope: session (runs once at start)
    """
    # Only print if we're actually collecting E2E tests and verbosity is enabled
    if request.config.getoption("verbose", 0) > 0:
        print("\n" + "=" * 60)
        print("E2E TEST SESSION - HARDWARE AVAILABILITY")
        print("=" * 60)
        print(hardware_availability.availability_matrix())
        print("=" * 60 + "\n")


# =============================================================================
# Hardware Skip Fixtures (Function-Scoped)
# =============================================================================

@pytest.fixture(scope="function")
def skip_without_gps(hardware_availability):
    """Skip test if GPS hardware is not available.

    Use this fixture in tests that require GPS hardware.
    The test will be skipped with a descriptive message if no GPS is detected.

    Scope: function

    Args:
        hardware_availability: Hardware detection fixture

    Example:
        def test_gps_connection(skip_without_gps):
            # This test only runs if GPS is available
            pass
    """
    avail = hardware_availability.get_availability("GPS")
    if not avail.available:
        pytest.skip(f"GPS hardware not available: {avail.reason}")


@pytest.fixture(scope="function")
def skip_without_drt(hardware_availability):
    """Skip test if DRT hardware is not available.

    Scope: function

    Args:
        hardware_availability: Hardware detection fixture

    Example:
        def test_drt_connection(skip_without_drt):
            # This test only runs if DRT is available
            pass
    """
    avail = hardware_availability.get_availability("DRT")
    if not avail.available:
        pytest.skip(f"DRT hardware not available: {avail.reason}")


@pytest.fixture(scope="function")
def skip_without_vog(hardware_availability):
    """Skip test if VOG hardware is not available.

    Scope: function

    Args:
        hardware_availability: Hardware detection fixture

    Example:
        def test_vog_connection(skip_without_vog):
            # This test only runs if VOG is available
            pass
    """
    avail = hardware_availability.get_availability("VOG")
    if not avail.available:
        pytest.skip(f"VOG hardware not available: {avail.reason}")


@pytest.fixture(scope="function")
def skip_without_eyetracker(hardware_availability):
    """Skip test if EyeTracker hardware is not available.

    Scope: function

    Args:
        hardware_availability: Hardware detection fixture

    Example:
        def test_eyetracker_connection(skip_without_eyetracker):
            # This test only runs if EyeTracker is available
            pass
    """
    avail = hardware_availability.get_availability("EyeTracker")
    if not avail.available:
        pytest.skip(f"EyeTracker hardware not available: {avail.reason}")


@pytest.fixture(scope="function")
def skip_without_audio(hardware_availability):
    """Skip test if Audio hardware is not available.

    Scope: function

    Args:
        hardware_availability: Hardware detection fixture

    Example:
        def test_audio_recording(skip_without_audio):
            # This test only runs if Audio input is available
            pass
    """
    avail = hardware_availability.get_availability("Audio")
    if not avail.available:
        pytest.skip(f"Audio hardware not available: {avail.reason}")


@pytest.fixture(scope="function")
def skip_without_cameras(hardware_availability):
    """Skip test if Camera hardware is not available.

    Scope: function

    Args:
        hardware_availability: Hardware detection fixture

    Example:
        def test_camera_capture(skip_without_cameras):
            # This test only runs if USB camera is available
            pass
    """
    avail = hardware_availability.get_availability("Cameras")
    if not avail.available:
        pytest.skip(f"Camera hardware not available: {avail.reason}")


@pytest.fixture(scope="function")
def skip_without_csi_cameras(hardware_availability):
    """Skip test if CSI Camera hardware is not available.

    Scope: function

    Args:
        hardware_availability: Hardware detection fixture

    Example:
        def test_csi_camera_capture(skip_without_csi_cameras):
            # This test only runs if CSI camera is available
            pass
    """
    avail = hardware_availability.get_availability("CSICameras")
    if not avail.available:
        pytest.skip(f"CSI Camera hardware not available: {avail.reason}")


@pytest.fixture(scope="function")
def require_hardware(hardware_availability) -> Callable[[str], None]:
    """Provide function to skip test if specified hardware unavailable.

    This fixture returns a callable that can be used to require
    multiple hardware types in a single test.

    Scope: function

    Args:
        hardware_availability: Hardware detection fixture

    Returns:
        Function that skips test if hardware unavailable

    Example:
        def test_multiple_devices(require_hardware):
            require_hardware("GPS")
            require_hardware("DRT")
            # Test runs only if both GPS and DRT are available
    """
    def require(module_name: str) -> None:
        """Skip test if specified module's hardware is unavailable."""
        avail = hardware_availability.get_availability(module_name)
        if not avail.available:
            pytest.skip(f"{module_name} hardware not available: {avail.reason}")

    return require


# =============================================================================
# Device Information Fixtures
# =============================================================================

@pytest.fixture(scope="session")
def gps_device_path(hardware_availability) -> Optional[str]:
    """Provide path to available GPS device.

    Scope: session

    Args:
        hardware_availability: Hardware detection fixture

    Returns:
        Device path string (e.g., "/dev/ttyUSB0") or None if not available

    Example:
        def test_gps_serial(gps_device_path, skip_without_gps):
            import serial
            ser = serial.Serial(gps_device_path, 9600)
    """
    avail = hardware_availability.get_availability("GPS")
    if avail.available and avail.devices:
        for device in avail.devices:
            if device.available and device.device_path:
                return device.device_path
    return None


@pytest.fixture(scope="session")
def drt_device_info(hardware_availability) -> Optional[Dict[str, Any]]:
    """Provide information about available DRT device.

    Scope: session

    Args:
        hardware_availability: Hardware detection fixture

    Returns:
        Dictionary with device info or None if not available
        Keys: device_type, device_path, device_name

    Example:
        def test_drt_connection(drt_device_info, skip_without_drt):
            if drt_device_info["device_type"] == "DRT_WDRT":
                # wDRT specific setup
                pass
    """
    avail = hardware_availability.get_availability("DRT")
    if avail.available and avail.devices:
        for device in avail.devices:
            if device.available:
                return {
                    "device_type": device.device_type.name,
                    "device_path": device.device_path,
                    "device_name": device.device_name,
                }
    return None


@pytest.fixture(scope="session")
def vog_device_info(hardware_availability) -> Optional[Dict[str, Any]]:
    """Provide information about available VOG device.

    Scope: session

    Args:
        hardware_availability: Hardware detection fixture

    Returns:
        Dictionary with device info or None if not available
        Keys: device_type, device_path, device_name

    Example:
        def test_vog_connection(vog_device_info, skip_without_vog):
            if vog_device_info["device_type"] == "VOG_WVOG":
                # wVOG specific setup
                pass
    """
    avail = hardware_availability.get_availability("VOG")
    if avail.available and avail.devices:
        for device in avail.devices:
            if device.available:
                return {
                    "device_type": device.device_type.name,
                    "device_path": device.device_path,
                    "device_name": device.device_name,
                }
    return None


@pytest.fixture(scope="session")
def camera_device_paths(hardware_availability) -> List[str]:
    """Provide list of available camera device paths.

    Scope: session

    Args:
        hardware_availability: Hardware detection fixture

    Returns:
        List of device paths (e.g., ["/dev/video0", "/dev/video2"])

    Example:
        def test_multi_camera(camera_device_paths, skip_without_cameras):
            if len(camera_device_paths) >= 2:
                # Test multi-camera capture
                pass
    """
    avail = hardware_availability.get_availability("Cameras")
    paths = []
    if avail.available and avail.devices:
        for device in avail.devices:
            if device.available and device.device_path:
                paths.append(device.device_path)
    return paths


@pytest.fixture(scope="session")
def audio_device_info(hardware_availability) -> Optional[Dict[str, Any]]:
    """Provide information about available audio input devices.

    Scope: session

    Args:
        hardware_availability: Hardware detection fixture

    Returns:
        Dictionary with device info or None if not available
        Keys: device_name, index, channels

    Example:
        def test_audio_recording(audio_device_info, skip_without_audio):
            device_index = audio_device_info["index"]
            # Use device_index for recording
    """
    avail = hardware_availability.get_availability("Audio")
    if avail.available and avail.devices:
        for device in avail.devices:
            if device.available:
                return {
                    "device_name": device.device_name,
                    "index": device.extra.get("index"),
                    "channels": device.extra.get("channels"),
                }
    return None


# =============================================================================
# Recording Output Fixtures
# =============================================================================

@pytest.fixture(scope="function")
def recording_output_dir(tmp_path: Path) -> Generator[Path, None, None]:
    """Provide temporary directory for E2E test recordings.

    Creates a clean directory for test recordings, CSV outputs, etc.
    The directory is automatically cleaned up after the test completes.

    Scope: function (fresh directory per test)

    Args:
        tmp_path: pytest's temporary directory fixture

    Yields:
        Path to the output directory

    Example:
        def test_recording_creates_files(recording_output_dir):
            output_csv = recording_output_dir / "gps_data.csv"
            # Run recording...
            assert output_csv.exists()
    """
    output_dir = tmp_path / "e2e_recording"
    output_dir.mkdir(parents=True, exist_ok=True)

    yield output_dir

    # Cleanup: remove directory and contents after test
    try:
        if output_dir.exists():
            shutil.rmtree(output_dir)
    except Exception:
        pass  # Ignore cleanup errors


@pytest.fixture(scope="function")
def recording_session_dir(recording_output_dir: Path) -> Generator[Path, None, None]:
    """Provide a recording session directory structure.

    Creates the standard directory structure used by Logger for recordings:
    - session_dir/
      - video/
      - audio/
      - data/
      - logs/

    Scope: function

    Args:
        recording_output_dir: E2E output directory fixture

    Yields:
        Path to the session directory

    Example:
        def test_full_recording(recording_session_dir):
            video_dir = recording_session_dir / "video"
            data_dir = recording_session_dir / "data"
            # Recording output goes to these directories
    """
    session_dir = recording_output_dir / "recording_session"
    session_dir.mkdir(parents=True, exist_ok=True)

    # Create standard subdirectories
    (session_dir / "video").mkdir(exist_ok=True)
    (session_dir / "audio").mkdir(exist_ok=True)
    (session_dir / "data").mkdir(exist_ok=True)
    (session_dir / "logs").mkdir(exist_ok=True)

    yield session_dir


# =============================================================================
# Device Cleanup Fixtures
# =============================================================================

@pytest.fixture(scope="function")
def cleanup_serial() -> Generator[List[Any], None, None]:
    """Provide automatic cleanup for serial port connections.

    Tracks opened serial ports and closes them after test completes.
    This ensures devices are properly released even if test fails.

    Scope: function

    Yields:
        List to track opened serial ports (append ports to auto-close)

    Example:
        def test_gps_streaming(cleanup_serial, gps_device_path):
            import serial
            ser = serial.Serial(gps_device_path, 9600)
            cleanup_serial.append(ser)
            # Test code...
            # ser will be closed automatically after test
    """
    opened_ports = []
    yield opened_ports

    # Cleanup: close all tracked serial ports
    for port in opened_ports:
        try:
            if hasattr(port, "close") and callable(port.close):
                port.close()
        except Exception:
            pass  # Ignore errors during cleanup


@pytest.fixture(scope="function")
def cleanup_cameras() -> Generator[List[Any], None, None]:
    """Provide automatic cleanup for camera connections.

    Tracks opened cameras and releases them after test completes.

    Scope: function

    Yields:
        List to track opened cameras (append cameras to auto-release)

    Example:
        def test_camera_capture(cleanup_cameras):
            import cv2
            cap = cv2.VideoCapture("/dev/video0")
            cleanup_cameras.append(cap)
            # Test code...
            # cap will be released automatically after test
    """
    opened_cameras = []
    yield opened_cameras

    # Cleanup: release all tracked cameras
    for cam in opened_cameras:
        try:
            if hasattr(cam, "release") and callable(cam.release):
                cam.release()
            elif hasattr(cam, "close") and callable(cam.close):
                cam.close()
        except Exception:
            pass  # Ignore errors during cleanup


@pytest.fixture(scope="function")
def cleanup_audio() -> Generator[List[Any], None, None]:
    """Provide automatic cleanup for audio streams.

    Tracks opened audio streams and stops them after test completes.

    Scope: function

    Yields:
        List to track opened audio streams (append streams to auto-stop)

    Example:
        def test_audio_recording(cleanup_audio):
            import sounddevice as sd
            stream = sd.InputStream(...)
            cleanup_audio.append(stream)
            stream.start()
            # Test code...
            # stream will be stopped automatically after test
    """
    opened_streams = []
    yield opened_streams

    # Cleanup: stop all tracked audio streams
    for stream in opened_streams:
        try:
            if hasattr(stream, "stop") and callable(stream.stop):
                stream.stop()
            if hasattr(stream, "close") and callable(stream.close):
                stream.close()
        except Exception:
            pass  # Ignore errors during cleanup


@pytest.fixture(scope="function")
def cleanup_devices(
    cleanup_serial: List[Any],
    cleanup_cameras: List[Any],
    cleanup_audio: List[Any],
) -> Dict[str, List[Any]]:
    """Provide unified cleanup interface for all device types.

    This is a convenience fixture that aggregates all device cleanup lists
    into a single dictionary for tests that use multiple device types.

    Scope: function

    Args:
        cleanup_serial: Serial port cleanup fixture
        cleanup_cameras: Camera cleanup fixture
        cleanup_audio: Audio cleanup fixture

    Returns:
        Dictionary with cleanup lists for each device type:
        - "serial": List for serial ports
        - "camera": List for cameras
        - "audio": List for audio streams

    Example:
        def test_multi_device(cleanup_devices, skip_without_gps, skip_without_cameras):
            import serial
            import cv2

            ser = serial.Serial(...)
            cleanup_devices["serial"].append(ser)

            cap = cv2.VideoCapture(...)
            cleanup_devices["camera"].append(cap)

            # All devices cleaned up after test
    """
    return {
        "serial": cleanup_serial,
        "camera": cleanup_cameras,
        "audio": cleanup_audio,
    }


# =============================================================================
# E2E Test Timing Fixtures
# =============================================================================

@pytest.fixture(scope="function")
def recording_duration() -> float:
    """Provide default recording duration for E2E tests.

    This can be overridden by tests that need different durations.

    Scope: function

    Returns:
        Duration in seconds (default: 2.0)

    Example:
        def test_short_recording(recording_duration):
            # Record for recording_duration seconds
            pass
    """
    return 2.0


@pytest.fixture(scope="function")
def connection_timeout() -> float:
    """Provide default connection timeout for hardware.

    Scope: function

    Returns:
        Timeout in seconds (default: 5.0)

    Example:
        def test_device_connection(connection_timeout):
            # Wait up to connection_timeout seconds for device
            pass
    """
    return 5.0


@pytest.fixture(scope="function")
def data_timeout() -> float:
    """Provide default timeout for waiting on data.

    Scope: function

    Returns:
        Timeout in seconds (default: 10.0)

    Example:
        def test_data_streaming(data_timeout):
            # Wait up to data_timeout seconds for data
            pass
    """
    return 10.0
