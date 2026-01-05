# Logger Test Suite

Comprehensive test suite for the Logger project, organized into unit, integration, and end-to-end tests with shared infrastructure for mocks, fixtures, and validation.

---

## Table of Contents

1. [Directory Structure](#directory-structure)
2. [Per-Module Test Organization](#per-module-test-organization)
3. [Mock Usage Guide](#mock-usage-guide)
4. [Fixture Documentation](#fixture-documentation)
5. [Running Tests by Category](#running-tests-by-category)
6. [Contributing New Tests](#contributing-new-tests)
7. [Hardware Requirements](#hardware-requirements)
8. [Test Infrastructure Overview](#test-infrastructure-overview)

---

## Directory Structure

```
tests/
├── conftest.py                    # Root pytest configuration and shared fixtures
├── README.md                      # This file
│
├── unit/                          # Fast, isolated tests (<1s each)
│   ├── conftest.py                # Unit test fixtures (isolated env, mock factories)
│   ├── base/                      # Shared base module tests
│   │   └── test_camera_validator.py    # Camera validation tests (42 tests)
│   ├── core/                      # Core infrastructure tests
│   │   └── devices/
│   │       └── test_master_device.py   # Master device tests (26 tests)
│   ├── modules/                   # Per-module unit tests
│   │   ├── audio/
│   │   │   └── test_audio.py           # Audio module tests (78 tests)
│   │   ├── cameras/
│   │   │   └── test_cameras.py         # USB camera tests (67 tests)
│   │   ├── csi_cameras/
│   │   │   └── test_csicameras.py      # CSI camera tests (58 tests)
│   │   ├── drt/
│   │   │   └── test_drt.py             # DRT module tests (109 tests)
│   │   ├── eyetracker/
│   │   │   └── test_eyetracker.py      # EyeTracker tests (86 tests)
│   │   ├── gps/
│   │   │   ├── test_nmea_parser.py     # NMEA parsing tests (37 tests)
│   │   │   ├── test_serial_transport.py # Serial transport tests (13 tests)
│   │   │   ├── test_gps_handler.py     # GPS handler tests (13 tests)
│   │   │   └── test_data_logger.py     # Data logging tests (19 tests)
│   │   ├── notes/
│   │   │   └── test_notes.py           # Notes module tests (74 tests)
│   │   └── vog/
│   │       └── test_vog.py             # VOG module tests (127 tests)
│   └── infrastructure/
│       └── test_helpers.py             # Infrastructure helper tests (59 tests)
│
├── integration/                   # Multi-component tests
│   ├── conftest.py                # Integration fixtures (CSV data, schemas)
│   ├── test_data_validation.py    # CSV data validation tests
│   ├── test_hardware_detection.py # Hardware detection tests (3 tests)
│   ├── test_schema_detection.py   # Schema detection tests (2 tests)
│   └── schema/                    # Schema validation tests
│       ├── test_gps_schema.py          # GPS schema tests (4 tests)
│       ├── test_drt_schema.py          # DRT schema tests (6 tests)
│       ├── test_vog_schema.py          # VOG schema tests (5 tests)
│       ├── test_eyetracker_schema.py   # EyeTracker schema tests (6 tests)
│       ├── test_notes_schema.py        # Notes schema tests (3 tests)
│       └── test_timing_validation.py   # Timing validation tests (5 tests)
│
├── e2e/                           # End-to-end tests (require hardware)
│   ├── conftest.py                # E2E fixtures (hardware detection, cleanup)
│   ├── test_gps_e2e.py            # GPS hardware tests (7 tests)
│   └── test_e2e_template.py       # E2E test template (7 tests)
│
└── infrastructure/                # Test support code (NOT tests)
    ├── mocks/                     # Mock implementations
    │   ├── __init__.py
    │   ├── serial_mocks.py        # MockSerialDevice, MockGPSDevice, MockDRTDevice, MockVOGDevice
    │   ├── camera_mocks.py        # MockCameraBackend, MockVideoCapture, MockPicamera2
    │   ├── audio_mocks.py         # MockInputStream, MockSoundDevice
    │   └── network_mocks.py       # MockPupilNeonAPI, MockGazeData, MockIMUData
    ├── fixtures/                  # Sample data files
    │   ├── sample_gps.csv
    │   ├── sample_drt_sdrt.csv
    │   ├── sample_drt_wdrt.csv
    │   ├── sample_vog_svog.csv
    │   ├── sample_vog_wvog.csv
    │   └── sample_notes.csv
    ├── schemas/                   # Validation schemas
    │   ├── csv_schema.py          # CSV schema definitions and validation
    │   └── hardware_detection.py  # Hardware availability detection
    └── helpers/                   # Test utilities
        ├── assertions.py          # Custom assertion helpers
        └── generators.py          # Test data generators
```

---

## Per-Module Test Organization

### GPS Module (82 tests)

| File | Tests | Coverage |
|------|-------|----------|
| `tests/unit/modules/gps/test_nmea_parser.py` | 37 | NMEA sentence parsing, checksum validation, coordinate conversion |
| `tests/unit/modules/gps/test_serial_transport.py` | 13 | Serial port management, connection/reconnection, buffering |
| `tests/unit/modules/gps/test_gps_handler.py` | 13 | GPS data handling, state management, event dispatch |
| `tests/unit/modules/gps/test_data_logger.py` | 19 | CSV logging, file rotation, data formatting |

### Audio Module (78 tests)

| File | Tests | Coverage |
|------|-------|----------|
| `tests/unit/modules/audio/test_audio.py` | 78 | RecorderService, device management, recording logic, WAV encoding, sample rate handling |

### Cameras Module (67 tests)

| File | Tests | Coverage |
|------|-------|----------|
| `tests/unit/modules/cameras/test_cameras.py` | 67 | USB backend, frame capture, encoder, device enumeration, resolution/FPS control |

### CSICameras Module (58 tests)

| File | Tests | Coverage |
|------|-------|----------|
| `tests/unit/modules/csi_cameras/test_csicameras.py` | 58 | Picamera2 integration, CSI capture, configuration, libcamera backend |

### DRT Module (109 tests)

| File | Tests | Coverage |
|------|-------|----------|
| `tests/unit/modules/drt/test_drt.py` | 109 | Protocol handlers (sDRT/wDRT), serial comms, trial logging, reaction time calculation, timeout handling |

### VOG Module (127 tests)

| File | Tests | Coverage |
|------|-------|----------|
| `tests/unit/modules/vog/test_vog.py` | 127 | Protocol handlers (sVOG/wVOG), shutter timing, reconnection logic, lens control |

### EyeTracker Module (86 tests)

| File | Tests | Coverage |
|------|-------|----------|
| `tests/unit/modules/eyetracker/test_eyetracker.py` | 86 | Gaze tracking, IMU data, eye events, stream handling, Pupil Labs API integration |

### Notes Module (74 tests)

| File | Tests | Coverage |
|------|-------|----------|
| `tests/unit/modules/notes/test_notes.py` | 74 | Text annotation, history management, timestamp handling, content validation |

---

## Mock Usage Guide

All mocks are located in `tests/infrastructure/mocks/` and provide hardware-free testing.

### MockSerialDevice

Base mock for serial communication. Used for GPS, DRT, and VOG testing.

```python
from tests.infrastructure.mocks.serial_mocks import MockSerialDevice, MockSerialConfig

# Basic usage
mock = MockSerialDevice()
mock.open()

# Queue data to be read
mock._queue_response(b"Hello\r\n")
data = mock.readline()  # Returns b"Hello\r\n"

# Add command response handler
mock.add_response_handler(b"STATUS", lambda: b"OK\r\n")
mock.write(b"STATUS")  # Will queue "OK\r\n" for reading

# Set up auto-streaming responses
mock.set_auto_responses([b"DATA1\r\n", b"DATA2\r\n"])
mock.start_auto_responses(interval=1.0)  # Send every 1 second
```

### MockGPSDevice

Specialized mock for GPS testing with NMEA support.

```python
from tests.infrastructure.mocks.serial_mocks import MockGPSDevice

# Create mock GPS
gps = MockGPSDevice()
gps.open()

# Start streaming NMEA sentences
gps.start_streaming(interval=1.0)

# Generate specific NMEA sentence
nmea = MockGPSDevice.generate_gga(
    lat=48.1173,
    lon=11.5167,
    alt=545.4,
    fix_quality=1,
    satellites=8
)
```

### MockDRTDevice

Mock for DRT (Detection Response Task) testing.

```python
from tests.infrastructure.mocks.serial_mocks import MockDRTDevice

# Create sDRT mock
sdrt = MockDRTDevice(device_type="sdrt")
sdrt.open()

# Simulate trial response
trial_data = sdrt.simulate_trial(
    reaction_time_ms=250,
    responses=1,
    battery_percent=85  # Only for wDRT
)
sdrt._queue_response(trial_data)

# Simulate timeout
timeout_data = sdrt.simulate_timeout()
```

### MockVOGDevice

Mock for VOG (Vision Occlusion Glasses) testing.

```python
from tests.infrastructure.mocks.serial_mocks import MockVOGDevice

# Create wVOG mock
wvog = MockVOGDevice(device_type="wvog")
wvog.open()

# Simulate shutter event
shutter_data = wvog.simulate_shutter_event(
    open_ms=1500,
    closed_ms=1500,
    lens="X",
    battery_percent=85
)
wvog._queue_response(shutter_data)
```

### MockCameraBackend

Mock for USB camera testing.

```python
from tests.infrastructure.mocks.camera_mocks import MockCameraBackend, MockVideoCapture

# As OpenCV VideoCapture replacement
cap = MockVideoCapture("/dev/video0")
ret, frame = cap.read()  # Returns synthetic test frame

# Configure frame generation pattern
backend = MockCameraBackend(width=1920, height=1080, fps=30)
backend.set_pattern("color_bars")  # color_bars, noise, solid, gradient
backend.open()
```

### MockPupilNeonAPI

Mock for Pupil Labs Neon eye tracker testing.

```python
from tests.infrastructure.mocks.network_mocks import MockPupilNeonAPI

# Create mock API
api = MockPupilNeonAPI(gaze_rate=200.0, imu_rate=200.0)
await api.connect()
api.start_streaming()

# Receive gaze data
async for gaze in api.receive_gaze():
    print(f"Gaze: ({gaze.x}, {gaze.y})")

# Receive IMU data
async for imu in api.receive_imu():
    print(f"Accel: ({imu.accel_data['x']}, {imu.accel_data['y']}, {imu.accel_data['z']})")

# Receive eye events
async for event in api.receive_events():
    print(f"Event: {event.event_type}, duration={event.duration}s")
```

### MockSoundDevice / MockInputStream

Mock for audio device testing.

```python
from tests.infrastructure.mocks.audio_mocks import MockSoundDevice, MockInputStream

# Patch sounddevice module
with MockSoundDevice.patch():
    import sounddevice as sd
    devices = sd.query_devices()  # Returns mock devices

# Direct stream usage
stream = MockInputStream(
    samplerate=48000,
    channels=2,
    callback=my_callback
)
stream.start()
```

---

## Fixture Documentation

### Root Fixtures (`tests/conftest.py`)

| Fixture | Scope | Description |
|---------|-------|-------------|
| `project_root` | function | Path to project root directory |
| `test_data_dir` | function | Path to `tests/infrastructure/fixtures/` |
| `sample_gps_csv` | function | Path to sample GPS CSV file |
| `sample_drt_sdrt_csv` | function | Path to sample sDRT CSV file |
| `sample_drt_wdrt_csv` | function | Path to sample wDRT CSV file |
| `sample_vog_svog_csv` | function | Path to sample sVOG CSV file |
| `sample_vog_wvog_csv` | function | Path to sample wVOG CSV file |
| `sample_notes_csv` | function | Path to sample Notes CSV file |
| `mock_serial_device` | function | Pre-configured MockSerialDevice instance |
| `mock_gps_device` | function | Pre-configured MockGPSDevice instance |
| `mock_drt_device` | function | Pre-configured MockDRTDevice instance |
| `mock_vog_device` | function | Pre-configured MockVOGDevice instance |

### Unit Test Fixtures (`tests/unit/conftest.py`)

| Fixture | Scope | Description |
|---------|-------|-------------|
| `isolated_env` | function | Complete isolated environment (temp dirs, env vars, clean PATH) |
| `temp_work_dir` | function | Simple temp directory for file operations |
| `temp_output_dir` | function | Temp directory for test outputs |
| `mock_serial_factory` | function | Factory for creating customized mock serial ports |
| `mock_audio_factory` | function | Factory for creating customized mock audio devices |
| `mock_camera_factory` | function | Factory for creating customized mock cameras |
| `patch_serial` | function | Context manager patching `serial.Serial` |
| `patch_sounddevice` | function | Context manager patching sounddevice module |
| `patch_cv2` | function | Context manager patching cv2 module |
| `frozen_time` | function | Control `time.time()` return value |
| `mock_monotonic` | function | Control `time.monotonic()` return value |
| `nmea_generator` | function | Generate valid NMEA sentences |
| `csv_row_generator` | function | Generate valid CSV row data |

**Usage Example - Isolated Environment:**

```python
def test_creates_config_file(isolated_env):
    # isolated_env is a temp directory with isolated HOME, XDG paths
    config_path = isolated_env / "config.json"
    create_config(config_path)
    assert config_path.exists()
```

**Usage Example - Mock Factory:**

```python
def test_custom_serial(mock_serial_factory):
    mock = mock_serial_factory(
        port="/dev/ttyUSB0",
        baudrate=115200,
        read_data=b"RESPONSE\n"
    )
    assert mock.read() == b"RESPONSE\n"
```

### Integration Test Fixtures (`tests/integration/conftest.py`)

| Fixture | Scope | Description |
|---------|-------|-------------|
| `gps_schema` | session | GPS CSV schema for validation |
| `drt_sdrt_schema` | session | sDRT CSV schema |
| `drt_wdrt_schema` | session | wDRT CSV schema |
| `vog_svog_schema` | session | sVOG CSV schema |
| `vog_wvog_schema` | session | wVOG CSV schema |
| `eyetracker_gaze_schema` | session | EyeTracker GAZE CSV schema |
| `eyetracker_imu_schema` | session | EyeTracker IMU CSV schema |
| `eyetracker_events_schema` | session | EyeTracker EVENTS CSV schema |
| `notes_schema` | session | Notes CSV schema |
| `all_schemas` | session | Dictionary of all schemas by name |
| `module_schemas` | session | Mapping of module names to applicable schemas |
| `load_csv_data` | function | Function to load CSV as list of dicts |
| `write_test_csv` | function | Function to write test CSV files |
| `sample_csv_with_schema` | function | Create sample CSVs matching a schema |
| `validate_csv` | function | CSV validation function |
| `detect_csv_schema` | function | Auto-detect schema from CSV header |
| `timing_validator` | function | Validate monotonic timestamp ordering |
| `standard_prefix_columns` | session | List of 6 standard prefix column names |
| `validate_standard_prefix` | function | Validate CSV has correct standard prefix |

**Usage Example - Schema Validation:**

```python
def test_gps_output_valid(validate_csv, gps_schema, output_file):
    result = validate_csv(output_file, gps_schema)
    assert result.is_valid, f"Errors: {result.errors}"
```

### E2E Test Fixtures (`tests/e2e/conftest.py`)

| Fixture | Scope | Description |
|---------|-------|-------------|
| `hardware_availability` | session | HardwareAvailability instance with all detection |
| `gps_available` | session | True if GPS hardware detected |
| `drt_available` | session | True if DRT hardware detected |
| `vog_available` | session | True if VOG hardware detected |
| `cameras_available` | session | True if USB cameras detected |
| `audio_available` | session | True if audio input detected |
| `eyetracker_available` | session | True if Pupil Labs Neon detected |
| `available_modules` | session | List of modules with available hardware |
| `unavailable_modules` | session | List of modules without hardware |
| `skip_without_gps` | function | Skip test if GPS unavailable |
| `skip_without_drt` | function | Skip test if DRT unavailable |
| `skip_without_vog` | function | Skip test if VOG unavailable |
| `skip_without_eyetracker` | function | Skip test if EyeTracker unavailable |
| `skip_without_audio` | function | Skip test if audio unavailable |
| `skip_without_cameras` | function | Skip test if cameras unavailable |
| `skip_without_csi_cameras` | function | Skip test if CSI cameras unavailable |
| `require_hardware` | function | Callable to require specific hardware |
| `gps_device_path` | session | Path to GPS device (e.g., "/dev/ttyUSB0") |
| `drt_device_info` | session | Dict with DRT device info |
| `vog_device_info` | session | Dict with VOG device info |
| `camera_device_paths` | session | List of camera device paths |
| `audio_device_info` | session | Dict with audio device info |
| `recording_output_dir` | function | Temp directory for E2E recordings |
| `recording_session_dir` | function | Session directory with video/audio/data/logs subdirs |
| `cleanup_serial` | function | Auto-cleanup list for serial ports |
| `cleanup_cameras` | function | Auto-cleanup list for cameras |
| `cleanup_audio` | function | Auto-cleanup list for audio streams |
| `cleanup_devices` | function | Combined cleanup dict for all device types |
| `recording_duration` | function | Default recording duration (2.0s) |
| `connection_timeout` | function | Default connection timeout (5.0s) |
| `data_timeout` | function | Default data timeout (10.0s) |

**Usage Example - Hardware Skip:**

```python
def test_gps_streaming(skip_without_gps, gps_device_path, cleanup_serial):
    import serial
    ser = serial.Serial(gps_device_path, 9600)
    cleanup_serial.append(ser)  # Auto-closed after test
    # Test code...
```

**Usage Example - Multiple Hardware:**

```python
def test_multi_device(require_hardware):
    require_hardware("GPS")
    require_hardware("DRT")
    # Test runs only if both GPS and DRT are available
```

---

## Running Tests by Category

### All Tests

```bash
# Run entire test suite
pytest tests/

# With verbose output
pytest tests/ -v

# With coverage report
pytest tests/ --cov=rpi_logger --cov-report=html

# Open coverage report
open htmlcov/index.html
```

### Unit Tests Only (Fast)

```bash
# All unit tests
pytest tests/unit/ -v

# Specific module
pytest tests/unit/modules/gps/ -v
pytest tests/unit/modules/drt/ -v
pytest tests/unit/modules/vog/ -v
pytest tests/unit/modules/audio/ -v
pytest tests/unit/modules/cameras/ -v
pytest tests/unit/modules/eyetracker/ -v
pytest tests/unit/modules/notes/ -v

# Core infrastructure tests
pytest tests/unit/core/ -v

# Base module tests
pytest tests/unit/base/ -v
```

### Integration Tests

```bash
# All integration tests
pytest tests/integration/ -v

# Schema validation tests
pytest tests/integration/schema/ -v

# Specific schema tests
pytest tests/integration/schema/test_gps_schema.py -v
pytest tests/integration/schema/test_drt_schema.py -v
```

### E2E Tests (Hardware Required)

```bash
# E2E tests (skipped without --run-hardware)
pytest tests/e2e/ -v

# Run with hardware (requires physical devices)
pytest tests/e2e/ --run-hardware -v

# Specific hardware tests
pytest tests/e2e/test_gps_e2e.py --run-hardware -v
```

### Skip Hardware Tests

```bash
# Skip all hardware-dependent tests
pytest tests/ -m "not hardware"

# Include hardware tests (requires hardware)
pytest tests/e2e/ --run-hardware
```

### By Marker

```bash
# Tests by module marker
pytest tests/ -m "gps"
pytest tests/ -m "drt"
pytest tests/ -m "vog"
pytest tests/ -m "audio"
pytest tests/ -m "eyetracker"

# Skip slow tests
pytest tests/ -m "not slow"

# Async tests only
pytest tests/ -m "asyncio"
```

### Pattern Matching

```bash
# Tests matching pattern in name
pytest tests/ -k "nmea"
pytest tests/ -k "schema"
pytest tests/ -k "serial"
pytest tests/ -k "timeout"
pytest tests/ -k "validation"

# Combine patterns
pytest tests/ -k "nmea or gga"
pytest tests/ -k "drt and not hardware"
```

### Parallel Execution

```bash
# Run tests in parallel (requires pytest-xdist)
pytest tests/ -n auto

# Specific number of workers
pytest tests/ -n 4
```

---

## Contributing New Tests

### File Naming Conventions

| Pattern | Example | Purpose |
|---------|---------|---------|
| `test_<component>.py` | `test_audio.py` | Main test file for a component |
| `test_<feature>.py` | `test_nmea_parser.py` | Test file for specific feature |
| `test_<component>_<variant>.py` | `test_drt_sdrt.py` | Variant-specific tests |

### Class Naming Conventions

```python
class TestAudioRecorder:
    """Tests for AudioRecorder class."""
    pass

class TestNMEAParser:
    """Tests for NMEA parser functionality."""
    pass

class TestDRTProtocolSDRT:
    """Tests specific to sDRT protocol."""
    pass
```

### Method Naming Conventions

Use the pattern: `test_<what>_<scenario>_<expected>`

```python
def test_parse_gga_valid_sentence_returns_position():
    """Test parsing valid GGA sentence returns correct position."""
    pass

def test_connect_timeout_raises_connection_error():
    """Test connection timeout raises ConnectionError."""
    pass

def test_record_no_device_skips_gracefully():
    """Test recording without device skips gracefully."""
    pass
```

### Using Existing Mocks

```python
from tests.infrastructure.mocks.serial_mocks import MockSerialDevice, MockGPSDevice
from tests.infrastructure.mocks.camera_mocks import MockCameraBackend
from tests.infrastructure.mocks.audio_mocks import MockSoundDevice
from tests.infrastructure.mocks.network_mocks import MockPupilNeonAPI


class TestMyComponent:
    def test_with_mock_serial(self, mock_serial_device):
        # Use fixture-provided mock
        mock_serial_device.open()
        mock_serial_device._queue_response(b"TEST\r\n")
        # ...

    def test_with_custom_mock(self):
        # Create custom mock
        mock = MockGPSDevice()
        mock.open()
        mock.start_streaming(interval=0.1)
        # ...
```

### Adding New Fixtures

Add fixtures to the appropriate conftest.py:

```python
# In tests/unit/conftest.py for unit test fixtures
@pytest.fixture(scope="function")
def my_custom_fixture(tmp_path):
    """Provide a custom test resource.

    Scope: function (fresh per test)

    Args:
        tmp_path: pytest's temp directory

    Yields:
        Custom resource

    Example:
        def test_with_custom(my_custom_fixture):
            my_custom_fixture.do_something()
    """
    resource = create_resource(tmp_path)
    yield resource
    resource.cleanup()
```

### Example Test Structure

```python
"""Tests for MyModule functionality.

This module tests:
- Feature A: description
- Feature B: description
"""

import pytest
from unittest.mock import MagicMock, patch

from tests.infrastructure.mocks.serial_mocks import MockSerialDevice


class TestMyModuleBasics:
    """Basic functionality tests for MyModule."""

    def test_init_default_config_sets_defaults(self):
        """Test initialization with default config sets expected defaults."""
        module = MyModule()
        assert module.timeout == 5.0
        assert module.retries == 3

    def test_init_custom_config_applies_config(self):
        """Test initialization with custom config applies all settings."""
        config = {"timeout": 10.0, "retries": 5}
        module = MyModule(config)
        assert module.timeout == 10.0
        assert module.retries == 5


class TestMyModuleConnection:
    """Connection-related tests for MyModule."""

    def test_connect_success_returns_true(self, mock_serial_device):
        """Test successful connection returns True."""
        mock_serial_device.open()
        module = MyModule(device=mock_serial_device)
        result = module.connect()
        assert result is True

    def test_connect_timeout_raises_timeout_error(self, mock_serial_device):
        """Test connection timeout raises TimeoutError."""
        mock_serial_device.config.timeout = 0.001
        module = MyModule(device=mock_serial_device)
        with pytest.raises(TimeoutError):
            module.connect()

    @pytest.mark.asyncio
    async def test_connect_async_success(self):
        """Test async connection succeeds."""
        module = MyModule()
        await module.connect_async()
        assert module.is_connected


class TestMyModuleDataProcessing:
    """Data processing tests for MyModule."""

    @pytest.mark.parametrize("input_data,expected", [
        (b"valid_data", {"status": "ok"}),
        (b"", {"status": "empty"}),
        (b"invalid", {"status": "error"}),
    ])
    def test_process_data_various_inputs(self, input_data, expected):
        """Test data processing with various inputs."""
        module = MyModule()
        result = module.process(input_data)
        assert result["status"] == expected["status"]
```

---

## Hardware Requirements

E2E tests require physical hardware. The following table lists hardware needed for each module:

| Module | Hardware | Device Type | Notes |
|--------|----------|-------------|-------|
| **GPS** | USB GPS Receiver | `/dev/ttyUSB*` or `/dev/ttyACM*` | U-Blox 7/8 or compatible NMEA GPS |
| **DRT** | DRT Serial Device | sDRT (Arduino) or wDRT (Pyboard) | sDRT: 115200 baud, wDRT: 57600 baud |
| **VOG** | VOG Serial Device | sVOG (Arduino) or wVOG (Pyboard) | Vision Occlusion Glasses controller |
| **Cameras** | USB Webcam | `/dev/video*` | UVC-compatible USB camera |
| **CSICameras** | RPi CSI Camera | Raspberry Pi only | Requires libcamera, Picamera2 |
| **Audio** | USB Microphone | ALSA/PulseAudio | Any USB audio input device |
| **EyeTracker** | Pupil Labs Neon | Network (WiFi/USB) | Requires pupil_labs.realtime_api |

### Hardware Detection

The test suite automatically detects available hardware:

```bash
# Check hardware availability
python -m tests.infrastructure.schemas.hardware_detection

# Output example:
# === HARDWARE AVAILABILITY MATRIX ===
#
# Module         | Device Type          | Available  | Reason
# --------------------------------------------------------------------------------
# GPS            | GPS_SERIAL           | YES        | /dev/ttyUSB0
# DRT            | DRT_SDRT             | NO         | No matching VID/PID
# Cameras        | CAMERA_USB           | YES        | /dev/video0
# ...
```

### Markers for Hardware Tests

```python
import pytest

@pytest.mark.hardware
def test_requires_any_hardware():
    """Skipped unless --run-hardware flag is used."""
    pass

@pytest.mark.gps
def test_requires_gps():
    """Skipped if GPS hardware not detected."""
    pass

@pytest.mark.drt
def test_requires_drt():
    """Skipped if DRT hardware not detected."""
    pass

@pytest.mark.cameras
def test_requires_camera():
    """Skipped if USB camera not detected."""
    pass
```

---

## Test Infrastructure Overview

### Custom Assertion Helpers (`infrastructure/helpers/assertions.py`)

Specialized assertions for CSV validation and timing verification:

```python
from tests.infrastructure.helpers.assertions import (
    assert_csv_valid,
    assert_timing_monotonic,
    assert_no_time_travel,
    assert_csv_row_count,
    assert_column_values,
)

# Validate CSV against schema
result = assert_csv_valid('/path/to/gps.csv', GPS_SCHEMA)

# Ensure timestamps are monotonically increasing
timestamps = assert_timing_monotonic('/path/to/data.csv')

# Check for time travel and drift
stats = assert_no_time_travel('/path/to/data.csv')

# Verify row count
count = assert_csv_row_count('/path/to/data.csv', min_rows=10, max_rows=1000)

# Validate column values
values = assert_column_values('/path/to/data.csv', 'fix_valid', allowed_values=[0, 1])
```

### Test Data Generators (`infrastructure/helpers/generators.py`)

Generate valid test data for protocols and CSV files:

```python
from tests.infrastructure.helpers.generators import (
    generate_nmea_sentence,
    generate_csv_row,
    generate_csv_rows,
    generate_mock_device_response,
    generate_gps_track,
)

# Generate NMEA sentence
nmea = generate_nmea_sentence(
    sentence_type="GGA",
    lat=48.1173,
    lon=11.5167,
    alt=545.4
)

# Generate CSV row matching schema
row = generate_csv_row(GPS_SCHEMA, latitude_deg=48.1173, trial=1)

# Generate multiple rows with incrementing timestamps
rows = generate_csv_rows(GPS_SCHEMA, count=100, time_increment=0.1)

# Generate device response
response = generate_mock_device_response("sdrt", reaction_time_ms=250)

# Generate GPS track for movement simulation
track = generate_gps_track(
    start_lat=48.1173,
    start_lon=11.5167,
    points=100,
    bearing=45.0,
    speed_mps=10.0
)
```

### CSV Schema Validation (`infrastructure/schemas/csv_schema.py`)

Comprehensive schema definitions and validation for all module outputs:

```python
from tests.infrastructure.schemas.csv_schema import (
    GPS_SCHEMA,
    DRT_SDRT_SCHEMA,
    DRT_WDRT_SCHEMA,
    VOG_SVOG_SCHEMA,
    VOG_WVOG_SCHEMA,
    EYETRACKER_GAZE_SCHEMA,
    EYETRACKER_IMU_SCHEMA,
    EYETRACKER_EVENTS_SCHEMA,
    NOTES_SCHEMA,
    validate_csv_file,
    detect_schema,
    validate_csv_directory,
)

# Validate single file
result = validate_csv_file('/path/to/gps.csv', GPS_SCHEMA)
if not result.is_valid:
    for error in result.errors:
        print(error)

# Auto-detect schema from header
schema = detect_schema('/path/to/unknown.csv')

# Validate all CSVs in directory
results = validate_csv_directory('/path/to/output/')
for path, result in results.items():
    print(result.summary())
```

### Hardware Detection (`infrastructure/schemas/hardware_detection.py`)

Detect available hardware for E2E testing:

```python
from tests.infrastructure.schemas.hardware_detection import (
    HardwareAvailability,
    get_hardware_availability,
    requires_hardware,
)

# Get hardware status
hw = get_hardware_availability()

# Check specific module
if hw.is_available("GPS"):
    # GPS hardware detected
    gps_info = hw.get_availability("GPS")
    print(f"GPS devices: {gps_info.devices}")

# Get testable modules
testable = hw.get_testable_modules()
print(f"Can test: {testable}")

# Print availability matrix
print(hw.availability_matrix())

# Use as decorator
@requires_hardware("GPS")
def test_gps_streaming():
    """Skipped if GPS unavailable."""
    pass
```

---

## Quick Reference

### Test Counts Summary

| Category | Tests |
|----------|-------|
| Unit Tests | 808 |
| Integration Tests | 34 |
| E2E Tests | 14 |
| **Total** | **856** |

### Key Commands

```bash
# Fast feedback (unit only)
pytest tests/unit/ -v --tb=short

# Full suite with coverage
pytest tests/ --cov=rpi_logger --cov-report=html -v

# Specific module deep dive
pytest tests/unit/modules/gps/ tests/integration/schema/test_gps_schema.py -v

# Hardware testing
pytest tests/e2e/ --run-hardware -v
```

### File Locations Quick Reference

| Need | Location |
|------|----------|
| Add unit test | `tests/unit/modules/<module>/test_<component>.py` |
| Add integration test | `tests/integration/test_<feature>.py` |
| Add E2E test | `tests/e2e/test_<module>_e2e.py` |
| Add mock | `tests/infrastructure/mocks/<type>_mocks.py` |
| Add fixture | `tests/<category>/conftest.py` |
| Add sample data | `tests/infrastructure/fixtures/` |
| Add schema | `tests/infrastructure/schemas/csv_schema.py` |
