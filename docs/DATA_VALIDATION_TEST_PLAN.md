# Data Validation Test Plan (Super Sanity Test)

## Executive Summary

This document defines the comprehensive "super sanity test" that validates **all module data is captured correctly, stored according to specification, and contains expected values**. This is the most critical test for the Logger system as it verifies the entire data pipeline.

---

## Goals

1. **Data Integrity**: Verify all modules output data matching their documented schemas
2. **Completeness**: Ensure no data columns are missing or corrupted
3. **Synchronization**: Validate cross-module timing correlation works correctly
4. **Transparency**: Clearly document which devices/modules could not be tested (hardware unavailable)

---

## Module Data Specifications

### Standard 6-Column Prefix (All CSV Modules)

Every CSV-outputting module MUST include this prefix:

| Column | Type | Description | Validation |
|--------|------|-------------|------------|
| `trial` | int | Trial number (1-indexed) | > 0 |
| `module` | str | Module name | Matches module's DISPLAY_NAME |
| `device_id` | str | Device identifier | Non-empty |
| `label` | str | User-assigned label | Can be empty |
| `record_time_unix` | float | Epoch seconds (system time) | > 0, increasing |
| `record_time_mono` | float | Monotonic clock seconds | >= 0, strictly increasing |

---

## Per-Module Data Schemas

### GPS Module (26 columns)

**Hardware Required**: USB GPS device (NMEA protocol)

| Column | Type | Valid Range | Notes |
|--------|------|-------------|-------|
| (6-column prefix) | - | - | - |
| `device_time_iso` | str | ISO8601 format | Device-reported time |
| `device_time_unix` | float | > 0 | Device epoch time |
| `latitude_deg` | float | -90 to 90 | Decimal degrees |
| `longitude_deg` | float | -180 to 180 | Decimal degrees |
| `altitude_m` | float | -500 to 50000 | Meters above sea level |
| `speed_mps` | float | >= 0 | Meters per second |
| `speed_kmh` | float | >= 0 | Kilometers per hour |
| `speed_knots` | float | >= 0 | Nautical miles per hour |
| `speed_mph` | float | >= 0 | Miles per hour |
| `course_deg` | float | 0 to 360 | Degrees from north |
| `fix_quality` | int | 0-8 | GPS fix quality code |
| `fix_mode` | str | 'A'/'V' or mode string | Autonomous/Void |
| `fix_valid` | int | 0/1 | Boolean as int |
| `satellites_in_use` | int | >= 0 | Active satellites |
| `satellites_in_view` | int | >= 0 | Visible satellites |
| `hdop` | float | > 0 | Horizontal dilution |
| `pdop` | float | > 0 | Position dilution |
| `vdop` | float | > 0 | Vertical dilution |
| `sentence_type` | str | GGA/RMC/VTG/etc | NMEA sentence type |
| `raw_sentence` | str | NMEA format | Raw NMEA for debugging |

**Validation Rules**:
- Speed fields must be consistent (mps * 3.6 ≈ kmh)
- satellites_in_use <= satellites_in_view
- If fix_valid=0, position may be NaN

---

### DRT Module - sDRT Protocol (10 columns)

**Hardware Required**: Simple DRT device (serial USB)

| Column | Type | Valid Range | Notes |
|--------|------|-------------|-------|
| (6-column prefix) | - | - | - |
| `device_time_ms` | int | >= 0 | Device milliseconds |
| `device_time_unix` | float | > 0 | Computed device epoch |
| `responses` | int | >= 0 | Response count for trial |
| `reaction_time_ms` | int | -1 or > 0 | -1 = timeout/miss |

**Validation Rules**:
- reaction_time_ms = -1 indicates missed response
- responses typically 0 or 1 per trial

---

### DRT Module - wDRT Protocol (11 columns)

**Hardware Required**: Wireless DRT device (serial USB)

| Column | Type | Valid Range | Notes |
|--------|------|-------------|-------|
| (all sDRT columns) | - | - | - |
| `battery_percent` | int | 0-100 | Battery level |

**Validation Rules**:
- Same as sDRT plus battery bounds check

---

### VOG Module - sVOG Protocol (7 columns)

**Hardware Required**: Simple VOG device (serial USB)

| Column | Type | Valid Range | Notes |
|--------|------|-------------|-------|
| `device_id` | str | - | Device identifier |
| `label` | str | - | User label |
| `unix_time` | float | > 0 | System time |
| `ms_since_record` | int | >= 0 | Milliseconds since start |
| `trial_number` | int | >= 1 | Trial number |
| `shutter_open` | int | 0/1 | Shutter state |
| `shutter_closed` | int | 0/1 | Inverse of open |

**Validation Rules**:
- shutter_open XOR shutter_closed = 1

---

### VOG Module - wVOG Protocol (11 columns)

**Hardware Required**: Wireless VOG device (serial USB)

| Column | Type | Valid Range | Notes |
|--------|------|-------------|-------|
| (sVOG columns) | - | - | - |
| `shutter_total` | int | >= 0 | Total shutter events |
| `lens` | str | 'A'/'B'/'X' | Lens identifier |
| `battery_percent` | int | 0-100 | Battery level |
| `device_unix_time` | float | > 0 | Device-side timestamp |

**Validation Rules**:
- lens must be one of 'A', 'B', 'X'
- battery_percent bounded

---

### EyeTracker Module - GAZE CSV (36 columns)

**Hardware Required**: Pupil Labs Neon (network connection)

| Column | Type | Valid Range | Notes |
|--------|------|-------------|-------|
| (6-column prefix) | - | - | - |
| `timestamp` | float | > 0 | Device timestamp |
| `timestamp_ns` | int | > 0 | Nanosecond precision |
| `stream_type` | str | 'GAZE' | Stream identifier |
| `worn` | int | 0/1 | Headset worn status |
| `x` | float | 0-1 | Normalized gaze X |
| `y` | float | 0-1 | Normalized gaze Y |
| `left_x` | float | 0-1 | Left eye X |
| `left_y` | float | 0-1 | Left eye Y |
| `right_x` | float | 0-1 | Right eye X |
| `right_y` | float | 0-1 | Right eye Y |
| `pupil_diameter_left` | float | > 0 | mm, can be NaN |
| `pupil_diameter_right` | float | > 0 | mm, can be NaN |
| `eyeball_center_left_x/y/z` | float | - | 3D position |
| `optical_axis_left_x/y/z` | float | - | Unit vector |
| `eyeball_center_right_x/y/z` | float | - | 3D position |
| `optical_axis_right_x/y/z` | float | - | Unit vector |
| `eyelid_angle_top/bottom_left` | float | - | Degrees |
| `eyelid_aperture_left` | float | >= 0 | mm |
| `eyelid_angle_top/bottom_right` | float | - | Degrees |
| `eyelid_aperture_right` | float | >= 0 | mm |

**Validation Rules**:
- Normalized coordinates 0-1 when valid
- NaN allowed for missing eye data
- timestamp_ns must be strictly increasing

---

### EyeTracker Module - IMU CSV (19 columns)

**Hardware Required**: Pupil Labs Neon (network connection)

| Column | Type | Valid Range | Notes |
|--------|------|-------------|-------|
| (6-column prefix) | - | - | - |
| `timestamp` | float | > 0 | Device timestamp |
| `timestamp_ns` | int | > 0 | Nanosecond precision |
| `gyro_x/y/z` | float | - | Angular velocity (rad/s) |
| `accel_x/y/z` | float | - | Linear acceleration (m/s^2) |
| `quat_w/x/y/z` | float | - | Orientation quaternion |
| `temperature` | float | -40 to 85 | Sensor temp (C) |

**Validation Rules**:
- Quaternion must be normalized: w^2+x^2+y^2+z^2 ≈ 1
- Temperature in sensor range

---

### EyeTracker Module - EVENTS CSV (24 columns)

**Hardware Required**: Pupil Labs Neon (network connection)

| Column | Type | Valid Range | Notes |
|--------|------|-------------|-------|
| (6-column prefix) | - | - | - |
| `timestamp` | float | > 0 | Event timestamp |
| `timestamp_ns` | int | > 0 | Nanosecond precision |
| `event_type` | str | fixation/saccade/blink | Event classification |
| `event_subtype` | str | - | Event subtype |
| `confidence` | float | 0-1 | Detection confidence |
| `duration` | float | >= 0 | Event duration (ms) |
| `start_time_ns` | int | > 0 | Event start |
| `end_time_ns` | int | > 0 | Event end |
| `start_gaze_x/y` | float | 0-1 | Start position |
| `end_gaze_x/y` | float | 0-1 | End position |
| `mean_gaze_x/y` | float | 0-1 | Mean position |
| `amplitude_pixels` | float | >= 0 | Saccade amplitude |
| `amplitude_angle_deg` | float | >= 0 | Visual angle |
| `mean_velocity` | float | >= 0 | Mean angular velocity |
| `max_velocity` | float | >= 0 | Peak velocity |

**Validation Rules**:
- end_time_ns >= start_time_ns
- max_velocity >= mean_velocity

---

### Notes Module (8 columns)

**Hardware Required**: None (user input)

| Column | Type | Valid Range | Notes |
|--------|------|-------------|-------|
| (6-column prefix) | - | - | - |
| `device_time_unix` | float | > 0 | Same as record_time_unix |
| `content` | str | - | Note text (can be empty) |

**Validation Rules**:
- Content can contain any UTF-8 characters
- Proper CSV escaping for quotes/newlines

---

### Audio Module (WAV + optional timing CSV)

**Hardware Required**: USB microphone or audio interface

**Output Files**:
- `<timestamp>_Audio_<device_id>.wav` - Audio data
- `<timestamp>_Audio_<device_id>_timing.csv` - Timing metadata (optional)

**WAV Validation**:
- File size > 0
- Valid WAV header
- Sample rate matches configured value
- Channel count matches configured value

**Timing CSV** (if present):
| Column | Type | Description |
|--------|------|-------------|
| `start_time_unix` | float | Recording start epoch |
| `start_time_mono` | float | Monotonic start time |
| `sample_rate` | int | Audio sample rate |
| `channels` | int | Channel count |

---

### Cameras Module (MP4 video)

**Hardware Required**: USB webcam

**Output Files**:
- `<timestamp>_Cameras_<camera_id>_trial<NNN>.mp4` - Video file

**Video Validation**:
- File size > 0
- Valid MP4 container
- Video stream present
- Frame rate matches configured value
- Resolution matches configured value

**Settings Cache** (`/storage/known_cameras.json`):
- JSON is valid
- Schema version = 2
- Camera entries contain required fields

---

### CSICameras Module (MP4 video)

**Hardware Required**: Raspberry Pi CSI camera

**Output Files**:
- `<timestamp>_CSICameras_<camera_id>_trial<NNN>.mp4` - Video file

**Validation**: Same as Cameras module

---

## Cross-Module Validation

### SYNC Metadata File

After recording stops, a SYNC file aggregates timing data:

**File**: `<timestamp>_SYNC_trial<NNN>.json`

**Contents**:
```json
{
  "trial": 1,
  "start_time_unix": 1704456789.123,
  "start_time_monotonic": 12345.678,
  "modules": {
    "GPS": {
      "file_path": "GPS/..._GPS_device.csv",
      "start_time_unix": 1704456789.124,
      "start_time_monotonic": 12345.679
    },
    ...
  }
}
```

**Validation Rules**:
- All active modules present in `modules` dict
- All referenced file paths exist
- Module start times >= session start time
- No gaps > 1 second between module starts (warning)

---

### Timing Correlation Tests

1. **Monotonic Consistency**: record_time_mono must be strictly increasing within each file
2. **Unix/Mono Alignment**: (record_time_unix[n] - record_time_unix[0]) ≈ (record_time_mono[n] - record_time_mono[0])
3. **Cross-Module Sync**: Same events in different modules should have timestamps within 100ms
4. **No Time Travel**: No negative deltas between consecutive records

---

## Test Categories

### Category A: Schema Validation (No Hardware)

These tests can run on any recorded CSV data:

| Test ID | Description | Module |
|---------|-------------|--------|
| A1 | Verify header matches schema | All CSV |
| A2 | Verify column count per row | All CSV |
| A3 | Verify data types | All CSV |
| A4 | Verify required fields non-empty | All CSV |
| A5 | Verify 6-column prefix consistency | All CSV |
| A6 | Verify timestamp ordering | All CSV |
| A7 | Verify value ranges | Per module |

### Category B: Integration Tests (Requires Hardware OR Mocks)

| Test ID | Description | Hardware | Mock Strategy |
|---------|-------------|----------|---------------|
| B1 | GPS data capture | GPS receiver | Replay NMEA file to mock serial |
| B2 | DRT trial recording | DRT device | Mock serial responses |
| B3 | VOG shutter recording | VOG device | Mock serial responses |
| B4 | EyeTracker streams | Pupil Neon | Mock network API |
| B5 | Audio capture | Microphone | Mock sounddevice |
| B6 | Video capture | Webcam | Mock V4L2 with test frames |
| B7 | CSI video capture | CSI camera | Mock picamera2 |
| B8 | Notes entry | None | Direct test |

### Category C: End-to-End Tests (Full Stack)

| Test ID | Description | Dependencies |
|---------|-------------|--------------|
| C1 | Full recording session | All available hardware |
| C2 | SYNC file generation | Multiple modules |
| C3 | Cross-module timing | GPS + DRT + Notes |
| C4 | Long duration stability | 30+ minute recording |
| C5 | Disk space handling | Near-full disk |

---

## Hardware Test Matrix

### Test Environment Status Tracking

The test runner MUST output a hardware availability matrix:

```
=== HARDWARE AVAILABILITY MATRIX ===

Module        | Device Type      | Available | Reason
--------------|------------------|-----------|---------------------------
GPS           | USB GPS          | NO        | No GPS device detected
DRT           | sDRT             | NO        | No serial device with VID/PID
DRT           | wDRT             | NO        | No serial device with VID/PID
VOG           | sVOG             | NO        | No serial device with VID/PID
VOG           | wVOG             | NO        | No serial device with VID/PID
EyeTracker    | Pupil Neon       | NO        | Network discovery failed
Audio         | USB Microphone   | YES       | Device: Blue Yeti
Cameras       | USB Webcam       | YES       | Device: Logitech C920
CSICameras    | RPi CSI          | NO        | Not on Raspberry Pi platform
Notes         | User Input       | YES       | No hardware required

TESTABLE MODULES: Audio, Cameras, Notes
UNTESTABLE MODULES: GPS, DRT, VOG, EyeTracker, CSICameras
```

---

## Test Implementation Phases

### Phase 1: Schema Validation Framework

**Tasks**:
1. Create `CSVSchemaValidator` base class
2. Define schema for each module (column names, types, ranges)
3. Implement row-by-row validation
4. Generate detailed error reports

**Files**:
- `rpi_logger/modules/base/tests/csv_schema.py` - Schema definitions
- `rpi_logger/modules/base/tests/test_data_validation.py` - Validators

### Phase 2: Per-Module Schema Tests

**Tasks**:
1. GPS schema validation tests
2. DRT schema validation tests (sDRT + wDRT)
3. VOG schema validation tests (sVOG + wVOG)
4. EyeTracker schema validation tests (GAZE, IMU, EVENTS)
5. Notes schema validation tests
6. Audio timing CSV validation tests

**Requires**: Sample data files for each module

### Phase 3: Hardware Detection Framework

**Tasks**:
1. Create `HardwareAvailability` class
2. Implement device detection for each module type
3. Generate availability matrix
4. Mark tests as SKIPPED with reason

**Files**:
- `rpi_logger/modules/base/tests/hardware_detection.py`

### Phase 4: Mock Infrastructure

**Tasks**:
1. Create `MockSerialDevice` for DRT/VOG/GPS
2. Create `MockSoundDevice` for Audio
3. Create `MockCameraBackend` for Cameras
4. Create `MockPupilNeonAPI` for EyeTracker

**Files**:
- `rpi_logger/modules/base/tests/mocks/` directory

### Phase 5: Integration Tests

**Tasks**:
1. Recording lifecycle tests (start → capture → stop)
2. SYNC file generation tests
3. Cross-module timing tests
4. Error condition tests (device disconnect, disk full)

### Phase 6: End-to-End Tests

**Tasks**:
1. Full system recording with all available hardware
2. Data completeness verification
3. Long-duration stability tests
4. Performance benchmarks

---

## Test Output Format

### Summary Report

```
=== DATA VALIDATION TEST REPORT ===
Date: 2025-01-05 10:30:00
Session: /data/recordings/2025-01-05_session_001

SCHEMA VALIDATION:
  GPS:        PASS (0 errors, 1247 rows)
  DRT:        SKIP (Hardware unavailable: no sDRT/wDRT detected)
  VOG:        SKIP (Hardware unavailable: no sVOG/wVOG detected)
  EyeTracker: SKIP (Hardware unavailable: Pupil Neon not found)
  Audio:      PASS (0 errors, WAV valid, 48000Hz stereo)
  Cameras:    PASS (0 errors, MP4 valid, 1920x1080@30fps)
  CSICameras: SKIP (Hardware unavailable: not on RPi)
  Notes:      PASS (0 errors, 15 notes recorded)

TIMING VALIDATION:
  Monotonic ordering:    PASS
  Unix/Mono alignment:   PASS (max drift: 0.003s)
  Cross-module sync:     PASS (max gap: 47ms)
  SYNC file:             PASS

HARDWARE MATRIX:
  Tested:    GPS, Audio, Cameras, Notes
  Untested:  DRT, VOG, EyeTracker, CSICameras (hardware unavailable)

OVERALL: PASS (with 4 modules untested)
```

### Detailed Error Report (on failure)

```
=== DETAILED ERRORS ===

GPS: FAIL
  Row 523: latitude_deg=91.234 exceeds valid range [-90, 90]
  Row 1024: record_time_mono decreased (time travel: -0.001s)

Audio: FAIL
  WAV file corrupted: unexpected EOF at byte 1048576

Cameras: WARN
  Frame rate variance: configured 30fps, measured 29.2fps average
```

---

## Success Criteria

A data validation test run is considered **PASSING** when:

1. **All available hardware modules pass schema validation** (100%)
2. **Timing validation passes** for all modules
3. **SYNC file is complete** and references valid files
4. **Unavailable hardware is clearly documented** with reasons
5. **No critical errors** in any module

A run is considered **FAILING** when:

1. Any schema validation fails for available hardware
2. Timing validation detects anomalies
3. SYNC file is missing or incomplete
4. Data files are corrupted or empty

---

## Integration with CI/CD

### Local Development

```bash
# Run full validation suite
pytest rpi_logger/modules/base/tests/test_data_validation.py -v

# Run with sample data
pytest ... --sample-data=/path/to/recorded/session

# Generate hardware matrix only
python -m rpi_logger.modules.base.tests.hardware_detection
```

### Continuous Integration

- Schema validation tests run on every commit (no hardware)
- Integration tests require hardware fixtures (manual trigger)
- End-to-end tests run weekly on test bench with all hardware

---

## Appendix A: Sample Data Requirements

To run comprehensive schema validation without hardware, we need sample data:

| Module | Files Needed | Source |
|--------|--------------|--------|
| GPS | `sample_gps.csv` | Recorded session or generated |
| DRT | `sample_drt_sdrt.csv`, `sample_drt_wdrt.csv` | Recorded session |
| VOG | `sample_vog_svog.csv`, `sample_vog_wvog.csv` | Recorded session |
| EyeTracker | `sample_gaze.csv`, `sample_imu.csv`, `sample_events.csv` | Recorded session |
| Notes | `sample_notes.csv` | Generated |
| Audio | `sample_audio.wav`, `sample_audio_timing.csv` | Recorded session |
| Cameras | `sample_video.mp4` | Recorded session |

Sample data should be stored in `rpi_logger/modules/base/tests/fixtures/`.

---

## Appendix B: NMEA Mock Sentences (GPS Testing)

```
$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,47.0,M,,*47
$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A
$GPVTG,054.7,T,034.4,M,005.5,N,010.2,K*48
```

---

## Appendix C: Serial Protocol Mock Responses

### DRT sDRT
```
Trial response: "T,1234,1,156\r\n"  # device_time_ms, responses, reaction_time
Timeout: "T,1234,0,-1\r\n"
```

### DRT wDRT
```
Trial response: "T,1234,1,156,87\r\n"  # + battery_percent
```

### VOG sVOG
```
Shutter event: "S,1234,1,1,0\r\n"  # ms, trial, open, closed
```

### VOG wVOG
```
Shutter event: "S,1234,1,1,0,5,A,92,1704456789\r\n"  # + total, lens, battery, device_time
```
