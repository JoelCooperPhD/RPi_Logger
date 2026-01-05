# Test Reorganization Plan

## Overview

This document provides a comprehensive plan for reorganizing the Logger project's test suite to ensure clarity, maintainability, and ease of use for future developers and AI agents working on the codebase.

**Created:** 2026-01-05
**Project:** Logger (`/home/joel/Development/Logger`)

---

## Current State Analysis

### Directory Structure (As-Is)

```
tests/
├── conftest.py              # Shared pytest configuration and fixtures
├── README.md                # Test documentation
├── __init__.py
│
├── unit/                    # Unit tests
│   ├── base/                # Base module tests
│   │   └── test_camera_validator.py
│   ├── core/                # Core infrastructure tests
│   │   └── devices/
│   │       └── test_master_device.py
│   └── modules/             # Per-module unit tests (MOSTLY EMPTY)
│       ├── audio/           # Empty
│       ├── cameras/         # Empty
│       ├── csi_cameras/     # Empty
│       ├── drt/             # Empty
│       ├── eyetracker/      # Empty
│       ├── gps/             # POPULATED (4 test files)
│       │   ├── test_data_logger.py
│       │   ├── test_gps_handler.py
│       │   ├── test_nmea_parser.py
│       │   └── test_serial_transport.py
│       ├── notes/           # Empty
│       └── vog/             # Empty
│
├── integration/             # Integration tests
│   └── test_data_validation.py  # CSV schema validation (618 lines)
│
├── e2e/                     # End-to-end tests
│   └── __init__.py          # Empty - placeholder
│
└── infrastructure/          # Test support code (NOT tests)
    ├── mocks/               # Mock implementations
    │   ├── audio_mocks.py
    │   ├── camera_mocks.py
    │   ├── network_mocks.py
    │   └── serial_mocks.py
    ├── fixtures/            # Sample CSV data files
    │   └── sample_*.csv     # 9 sample CSV files
    └── schemas/             # Validation schemas
        ├── csv_schema.py    # CSV schema definitions
        └── hardware_detection.py
```

### What Is Currently Being Tested

| Test File | Component | Test Count | Coverage |
|-----------|-----------|------------|----------|
| `test_master_device.py` | MasterDevice, Registry, USB ID Resolver | ~28 tests | Good |
| `test_camera_validator.py` | CapabilityValidator | ~35 tests | Good |
| `test_nmea_parser.py` | NMEA Parser, GPSFixSnapshot | ~30 tests | Good |
| `test_gps_handler.py` | GPS Handler | ~10 tests | Partial |
| `test_serial_transport.py` | Serial Transport | ~10 tests | Partial |
| `test_data_logger.py` | Data Logger | ~10 tests | Partial |
| `test_data_validation.py` | CSV Schemas, Timing, Hardware Detection | ~40 tests | Good |

### Current Issues

1. **Empty Module Directories**: Most module test directories are empty placeholders
2. **Inconsistent Naming**: `test_camera_validator.py` is in `base/` but tests module code
3. **Missing Tests**: DRT, VOG, Audio, Cameras, CSICameras, EyeTracker, Notes all lack unit tests
4. **No E2E Tests**: The `e2e/` folder is a placeholder with no actual tests
5. **Mixed Responsibilities**: `test_data_validation.py` combines schema tests with integration tests
6. **Documentation**: README exists but could be more actionable for parallel work

---

## Proposed Reorganization

### Target Directory Structure

```
tests/
├── conftest.py              # Global pytest configuration
├── README.md                # Updated test documentation
├── __init__.py
│
├── unit/                    # Fast, isolated tests (<1s each)
│   ├── __init__.py
│   ├── conftest.py          # Unit-specific fixtures
│   │
│   ├── core/                # Core infrastructure tests
│   │   ├── __init__.py
│   │   ├── devices/
│   │   │   ├── __init__.py
│   │   │   ├── test_master_device.py
│   │   │   ├── test_master_registry.py    # Split from master_device
│   │   │   └── test_physical_id.py        # Split from master_device
│   │   └── config/
│   │       └── test_config_manager.py     # NEW
│   │
│   ├── base/                # Shared base module tests
│   │   ├── __init__.py
│   │   ├── test_camera_validator.py
│   │   ├── test_camera_storage.py         # NEW
│   │   ├── test_camera_models.py          # NEW
│   │   └── test_av_muxer.py               # NEW
│   │
│   └── modules/             # Per-module unit tests
│       ├── __init__.py
│       │
│       ├── audio/
│       │   ├── __init__.py
│       │   ├── test_recorder_service.py   # NEW
│       │   ├── test_device_manager.py     # NEW
│       │   └── test_recording_manager.py  # NEW
│       │
│       ├── cameras/
│       │   ├── __init__.py
│       │   ├── test_usb_backend.py        # NEW
│       │   ├── test_frame_capture.py      # NEW
│       │   └── test_encoder.py            # NEW
│       │
│       ├── csi_cameras/
│       │   ├── __init__.py
│       │   ├── test_picamera2_backend.py  # NEW
│       │   └── test_csi_capture.py        # NEW
│       │
│       ├── drt/
│       │   ├── __init__.py
│       │   ├── test_drt_protocol.py       # NEW (sDRT/wDRT handlers)
│       │   ├── test_drt_serial.py         # NEW (serial communication)
│       │   └── test_trial_logger.py       # NEW
│       │
│       ├── eyetracker/
│       │   ├── __init__.py
│       │   ├── test_gaze_handler.py       # NEW
│       │   ├── test_stream_handler.py     # NEW
│       │   └── test_pupil_neon_api.py     # NEW
│       │
│       ├── gps/
│       │   ├── __init__.py
│       │   ├── test_nmea_parser.py        # Existing
│       │   ├── test_gps_handler.py        # Existing
│       │   ├── test_serial_transport.py   # Existing
│       │   └── test_data_logger.py        # Existing
│       │
│       ├── notes/
│       │   ├── __init__.py
│       │   ├── test_note_service.py       # NEW
│       │   └── test_history_manager.py    # NEW
│       │
│       └── vog/
│           ├── __init__.py
│           ├── test_vog_protocol.py       # NEW (sVOG/wVOG handlers)
│           ├── test_vog_serial.py         # NEW
│           └── test_reconnection.py       # NEW
│
├── integration/             # Multi-component tests
│   ├── __init__.py
│   ├── conftest.py          # Integration-specific fixtures
│   │
│   ├── schema/              # CSV schema validation tests
│   │   ├── __init__.py
│   │   ├── test_gps_schema.py
│   │   ├── test_drt_schema.py
│   │   ├── test_vog_schema.py
│   │   ├── test_eyetracker_schema.py
│   │   ├── test_notes_schema.py
│   │   └── test_timing_validation.py
│   │
│   └── data_flow/           # Data pipeline tests
│       ├── __init__.py
│       └── test_csv_writer_integration.py # NEW
│
├── e2e/                     # End-to-end tests (require hardware)
│   ├── __init__.py
│   ├── conftest.py          # E2E-specific fixtures, hardware detection
│   ├── test_gps_e2e.py      # NEW
│   ├── test_drt_e2e.py      # NEW
│   ├── test_vog_e2e.py      # NEW
│   └── test_recording_e2e.py # NEW
│
└── infrastructure/          # Test support code (NOT tests)
    ├── __init__.py
    │
    ├── mocks/               # Mock implementations
    │   ├── __init__.py
    │   ├── serial_mocks.py
    │   ├── audio_mocks.py
    │   ├── camera_mocks.py
    │   └── network_mocks.py
    │
    ├── fixtures/            # Sample data files
    │   ├── __init__.py
    │   └── sample_*.csv
    │
    ├── schemas/             # Validation schemas
    │   ├── __init__.py
    │   ├── csv_schema.py
    │   └── hardware_detection.py
    │
    └── helpers/             # NEW: Test utilities
        ├── __init__.py
        ├── assertions.py    # Custom assertions
        └── generators.py    # Test data generators
```

---

## Implementation Tasks

The following tasks are designed to be executed by parallel agents. Each task is independent unless dependencies are noted.

### Phase 1: Structural Changes (Foundation)

#### Task 1.1: Create Infrastructure Helpers
**Assignee:** Agent A
**Priority:** HIGH
**Dependencies:** None

Create `/home/joel/Development/Logger/tests/infrastructure/helpers/` directory with:

1. `__init__.py` - Package exports
2. `assertions.py` - Custom assertion helpers:
   - `assert_csv_valid(path, schema)` - Validate CSV against schema
   - `assert_timing_monotonic(csv_path)` - Check monotonic timestamps
   - `assert_no_time_travel(csv_path)` - Verify no backward jumps
3. `generators.py` - Test data generators:
   - `generate_nmea_sentence(lat, lon, ...)` - Generate valid NMEA
   - `generate_csv_row(schema, **overrides)` - Generate CSV rows
   - `generate_mock_device_response(device_type)` - Device responses

**Acceptance Criteria:**
- All helper functions have docstrings
- Unit tests exist for each helper
- Exports are clean in `__init__.py`

---

#### Task 1.2: Split Integration Test File
**Assignee:** Agent B
**Priority:** HIGH
**Dependencies:** None

Reorganize `tests/integration/test_data_validation.py` (618 lines) into:

1. Create `tests/integration/schema/` directory
2. Split into separate files:
   - `test_gps_schema.py` - `TestGPSSchema` class (~50 lines)
   - `test_drt_schema.py` - `TestDRTSchema` class (~60 lines)
   - `test_vog_schema.py` - `TestVOGSchema` class (~50 lines)
   - `test_eyetracker_schema.py` - `TestEyeTrackerSchema` class (~40 lines)
   - `test_notes_schema.py` - `TestNotesSchema` class (~40 lines)
   - `test_timing_validation.py` - `TestTimingValidation`, `TestStandardPrefix` (~100 lines)
3. Move `TestSchemaDetection`, `TestHardwareDetection` to integration root
4. Keep `TestReport` and CLI in `test_data_validation.py` (runner only)

**Acceptance Criteria:**
- All tests pass after split: `pytest tests/integration/ -v`
- No duplicate code
- Each file has clear module docstring
- Imports work correctly

---

#### Task 1.3: Add Conftest Files Per Test Category
**Assignee:** Agent C
**Priority:** MEDIUM
**Dependencies:** None

Create category-specific conftest files:

1. `tests/unit/conftest.py`:
   - Fixtures for creating isolated test environments
   - Mock factory fixtures
   - Temporary directory fixtures

2. `tests/integration/conftest.py`:
   - Fixtures for CSV test data
   - Schema fixtures
   - Integration test markers

3. `tests/e2e/conftest.py`:
   - Hardware detection fixtures
   - Skip markers for missing hardware
   - Device cleanup fixtures

**Acceptance Criteria:**
- No fixture duplication with root `conftest.py`
- Clear scope definitions (function, module, session)
- Documented fixture purposes

---

### Phase 2: Unit Test Implementation (Parallel)

All Phase 2 tasks can run in parallel. Use GPS tests as templates.

#### Task 2.1: DRT Module Unit Tests
**Assignee:** Agent D
**Priority:** HIGH
**Dependencies:** Phase 1.1 complete

Create tests in `tests/unit/modules/drt/`:

1. `test_drt_protocol.py`:
   - Test sDRT protocol parsing
   - Test wDRT protocol parsing
   - Test command generation
   - Test response validation

2. `test_drt_serial.py`:
   - Test serial port configuration
   - Test read/write operations
   - Test timeout handling
   - Test reconnection logic

3. `test_trial_logger.py`:
   - Test trial data recording
   - Test CSV output format
   - Test reaction time calculations

**Template:** Use `tests/unit/modules/gps/test_nmea_parser.py` as pattern
**Mock:** Use `tests/infrastructure/mocks/serial_mocks.py` (MockDRTDevice)

**Acceptance Criteria:**
- Minimum 20 test cases
- No hardware required (all mocked)
- Coverage > 80% for tested modules

---

#### Task 2.2: VOG Module Unit Tests
**Assignee:** Agent E
**Priority:** HIGH
**Dependencies:** Phase 1.1 complete

Create tests in `tests/unit/modules/vog/`:

1. `test_vog_protocol.py`:
   - Test sVOG protocol parsing
   - Test wVOG protocol parsing
   - Test lens value handling (A, B, X)
   - Test battery percentage parsing (wVOG)

2. `test_vog_serial.py`:
   - Test serial communication
   - Test baud rate configuration
   - Test data buffering

3. `test_reconnection.py`:
   - Test disconnect detection
   - Test automatic reconnection
   - Test state recovery

**Template:** Use `tests/unit/modules/gps/test_serial_transport.py` as pattern
**Mock:** Use `tests/infrastructure/mocks/serial_mocks.py` (MockVOGDevice)

**Acceptance Criteria:**
- Minimum 20 test cases
- No hardware required
- Test both sVOG and wVOG variants

---

#### Task 2.3: Audio Module Unit Tests
**Assignee:** Agent F
**Priority:** HIGH
**Dependencies:** Phase 1.1 complete

Create tests in `tests/unit/modules/audio/`:

1. `test_recorder_service.py`:
   - Test recording start/stop
   - Test file path generation
   - Test format configuration
   - Test error handling

2. `test_device_manager.py`:
   - Test device enumeration
   - Test device selection
   - Test capability queries

3. `test_recording_manager.py`:
   - Test recording state machine
   - Test concurrent recordings
   - Test file finalization

**Template:** Use `tests/unit/modules/gps/test_gps_handler.py` as pattern
**Mock:** Use `tests/infrastructure/mocks/audio_mocks.py` (MockSoundDevice)

**Acceptance Criteria:**
- Minimum 25 test cases
- Mock all sounddevice calls
- Test async operations

---

#### Task 2.4: Camera Module Unit Tests
**Assignee:** Agent G
**Priority:** MEDIUM
**Dependencies:** Phase 1.1 complete

Create tests in `tests/unit/modules/cameras/`:

1. `test_usb_backend.py`:
   - Test device discovery
   - Test capability probing
   - Test format selection

2. `test_frame_capture.py`:
   - Test frame grabbing
   - Test FPS validation
   - Test resolution switching

3. `test_encoder.py`:
   - Test video encoding
   - Test codec selection
   - Test bitrate configuration

**Template:** Use `tests/unit/base/test_camera_validator.py` as pattern
**Mock:** Use `tests/infrastructure/mocks/camera_mocks.py` (MockCameraBackend)

**Acceptance Criteria:**
- Minimum 20 test cases
- No V4L2 calls (all mocked)
- Test MJPEG and H264 paths

---

#### Task 2.5: EyeTracker Module Unit Tests
**Assignee:** Agent H
**Priority:** MEDIUM
**Dependencies:** Phase 1.1 complete

Create tests in `tests/unit/modules/eyetracker/`:

1. `test_gaze_handler.py`:
   - Test gaze data parsing
   - Test coordinate transformation
   - Test fixation detection

2. `test_stream_handler.py`:
   - Test stream connection
   - Test data buffering
   - Test stream recovery

3. `test_pupil_neon_api.py`:
   - Test API authentication
   - Test device discovery
   - Test calibration handling

**Template:** Use `tests/unit/modules/gps/test_gps_handler.py` as pattern
**Mock:** Use `tests/infrastructure/mocks/network_mocks.py` (MockPupilNeonAPI)

**Acceptance Criteria:**
- Minimum 20 test cases
- Mock all network calls
- Test all 3 CSV types (gaze, IMU, events)

---

#### Task 2.6: Notes Module Unit Tests
**Assignee:** Agent I
**Priority:** LOW
**Dependencies:** None

Create tests in `tests/unit/modules/notes/`:

1. `test_note_service.py`:
   - Test note creation
   - Test timestamp handling
   - Test trial association

2. `test_history_manager.py`:
   - Test note retrieval
   - Test filtering
   - Test export

**Note:** This module is simpler; minimal mocking needed.

**Acceptance Criteria:**
- Minimum 10 test cases
- Test Unicode content handling
- Test empty string edge cases

---

#### Task 2.7: Base Module Tests (Camera Storage/Models)
**Assignee:** Agent J
**Priority:** MEDIUM
**Dependencies:** None

Create tests in `tests/unit/base/`:

1. `test_camera_storage.py`:
   - Test cache read/write
   - Test versioning
   - Test file I/O errors

2. `test_camera_models.py`:
   - Test model database lookup
   - Test capability resolution
   - Test unknown model handling

3. `test_av_muxer.py`:
   - Test audio/video combining
   - Test format validation
   - Test timing alignment

**Acceptance Criteria:**
- Minimum 15 test cases per file
- Test file system edge cases
- Use tmp_path fixture

---

### Phase 3: E2E Test Framework

#### Task 3.1: E2E Test Infrastructure
**Assignee:** Agent K
**Priority:** LOW
**Dependencies:** Phase 1.3 complete

Set up E2E testing framework in `tests/e2e/`:

1. Update `conftest.py` with:
   - Hardware detection using `infrastructure/schemas/hardware_detection.py`
   - Automatic skip if hardware unavailable
   - Device cleanup fixtures
   - Recording output directories

2. Create `test_gps_e2e.py`:
   - Test real GPS device connection (if available)
   - Test NMEA data stream
   - Test CSV output

3. Create template for other E2E tests

**Acceptance Criteria:**
- Tests skip gracefully without hardware
- No test pollution between runs
- Clear hardware requirements documented

---

### Phase 4: Documentation Updates

#### Task 4.1: Update Test README
**Assignee:** Agent L
**Priority:** MEDIUM
**Dependencies:** Phases 1-2 complete

Update `tests/README.md` with:

1. New directory structure diagram
2. Per-module test patterns
3. Mock usage guide
4. Fixture documentation
5. Running tests by category
6. Contributing new tests guide

**Acceptance Criteria:**
- All examples work when copy-pasted
- Links to source files work
- Coverage gaps section updated

---

## Test Patterns and Guidelines

### File Naming Convention

```
test_<component>.py           # Primary test file
test_<component>_<aspect>.py  # Specific aspect tests
```

### Class Naming Convention

```python
class Test<ComponentName>:
    """Tests for <ComponentName> class/function."""

class Test<ComponentName><Scenario>:
    """Tests for <ComponentName> in <Scenario> conditions."""
```

### Method Naming Convention

```python
def test_<what>_<scenario>_<expected_outcome>(self):
    """Test that <what> does <expected_outcome> when <scenario>."""
```

Examples:
- `test_parse_nmea_valid_gga_returns_position`
- `test_validate_mode_invalid_fps_corrects_to_nearest`
- `test_register_capability_duplicate_updates_existing`

### Using Mocks

```python
# Good: Import from infrastructure
from tests.infrastructure.mocks import MockSerialDevice, MockGPSDevice

# Good: Use conftest fixtures
def test_with_mock(mock_gps_device):
    result = mock_gps_device.read()
    assert result is not None

# Bad: Inline mock creation (unless unique to test)
from unittest.mock import MagicMock
mock = MagicMock()  # Avoid unless necessary
```

### Using Fixtures

```python
# Use pytest fixtures from conftest.py
def test_gps_csv_valid(sample_gps_csv):
    """Use pre-configured sample CSV."""
    result = validate(sample_gps_csv)
    assert result.is_valid

# Use tmp_path for file operations
def test_write_csv(tmp_path):
    """Use temporary directory for outputs."""
    output = tmp_path / "output.csv"
    write_data(output)
    assert output.exists()
```

### Marking Tests

```python
import pytest

@pytest.mark.hardware
def test_requires_hardware():
    """Skip without hardware."""
    pass

@pytest.mark.slow
def test_takes_time():
    """Skip with -m 'not slow'."""
    pass

@pytest.mark.asyncio
async def test_async_operation():
    """Async test with pytest-asyncio."""
    pass

@pytest.mark.parametrize("input,expected", [
    ("4807.038", 48.1173),
    ("3348.456", 33.8076),
])
def test_with_params(input, expected):
    """Data-driven test."""
    assert parse(input) == pytest.approx(expected, rel=1e-4)
```

---

## Quick Reference Commands

```bash
# Run all tests
pytest tests/

# Run unit tests only (fast)
pytest tests/unit/ -v

# Run integration tests
pytest tests/integration/ -v

# Run specific module tests
pytest tests/unit/modules/gps/ -v
pytest tests/unit/modules/drt/ -v

# Skip hardware tests (default)
pytest tests/ -m "not hardware"

# Include hardware tests
pytest tests/ --run-hardware

# Skip slow tests
pytest tests/ -m "not slow"

# Run tests matching pattern
pytest tests/ -k "nmea"
pytest tests/ -k "schema"

# Run with coverage
pytest tests/ --cov=rpi_logger --cov-report=html

# Run single test file
pytest tests/unit/modules/gps/test_nmea_parser.py -v

# Run single test class
pytest tests/unit/modules/gps/test_nmea_parser.py::TestNMEAParser -v

# Run single test method
pytest tests/unit/modules/gps/test_nmea_parser.py::TestNMEAParser::test_parse_gprmc_valid -v
```

---

## Success Metrics

After reorganization is complete:

1. **Coverage**: Unit test coverage > 80% for all modules
2. **Speed**: Unit tests complete in < 30 seconds
3. **Independence**: Each test file runs independently
4. **Documentation**: All test directories have clear README or docstrings
5. **CI Ready**: Tests can run in CI without hardware

---

## Appendix: Source Code to Test Mapping

| Source Path | Test Path | Status |
|-------------|-----------|--------|
| `rpi_logger/core/devices/master_device.py` | `tests/unit/core/devices/test_master_device.py` | EXISTS |
| `rpi_logger/core/devices/master_registry.py` | `tests/unit/core/devices/test_master_registry.py` | TODO |
| `rpi_logger/core/devices/physical_id.py` | `tests/unit/core/devices/test_physical_id.py` | TODO |
| `rpi_logger/modules/base/camera_validator.py` | `tests/unit/base/test_camera_validator.py` | EXISTS |
| `rpi_logger/modules/base/camera_storage.py` | `tests/unit/base/test_camera_storage.py` | TODO |
| `rpi_logger/modules/base/camera_models.py` | `tests/unit/base/test_camera_models.py` | TODO |
| `rpi_logger/modules/base/av_muxer.py` | `tests/unit/base/test_av_muxer.py` | TODO |
| `rpi_logger/modules/GPS/*` | `tests/unit/modules/gps/test_*.py` | EXISTS |
| `rpi_logger/modules/DRT/*` | `tests/unit/modules/drt/test_*.py` | TODO |
| `rpi_logger/modules/VOG/*` | `tests/unit/modules/vog/test_*.py` | TODO |
| `rpi_logger/modules/Audio/*` | `tests/unit/modules/audio/test_*.py` | TODO |
| `rpi_logger/modules/Cameras/*` | `tests/unit/modules/cameras/test_*.py` | TODO |
| `rpi_logger/modules/CSICameras/*` | `tests/unit/modules/csi_cameras/test_*.py` | TODO |
| `rpi_logger/modules/EyeTracker/*` | `tests/unit/modules/eyetracker/test_*.py` | TODO |
| `rpi_logger/modules/Notes/*` | `tests/unit/modules/notes/test_*.py` | TODO |

---

## Change Log

| Date | Author | Changes |
|------|--------|---------|
| 2026-01-05 | AI Agent | Initial plan created |
