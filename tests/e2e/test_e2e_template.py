"""E2E Test Template - A guide for writing end-to-end tests for Logger modules.

This template demonstrates the standard patterns for writing E2E tests that
interact with real hardware. Use this as a starting point when creating E2E
tests for new modules (DRT, VOG, Cameras, Audio, EyeTracker, etc.).

================================================================================
E2E TEST STRUCTURE OVERVIEW
================================================================================

E2E tests verify complete workflows from device connection to file output.
They differ from unit tests (isolated logic) and integration tests (component
interactions) by testing the full system with real hardware.

Key characteristics of E2E tests:
    1. Require physical hardware (use markers to skip when unavailable)
    2. Test device detection, connection, data streaming, and file output
    3. Validate output files against defined schemas
    4. Properly clean up resources (devices, files) after tests
    5. Handle hardware variability (timeouts, intermittent data, etc.)

================================================================================
FILE ORGANIZATION
================================================================================

tests/e2e/
    conftest.py          - Shared fixtures for all E2E tests
    test_gps_e2e.py      - GPS module E2E tests
    test_drt_e2e.py      - DRT module E2E tests
    test_vog_e2e.py      - VOG module E2E tests
    test_cameras_e2e.py  - Camera module E2E tests
    test_audio_e2e.py    - Audio module E2E tests
    test_e2e_template.py - This template file

================================================================================
RUNNING E2E TESTS
================================================================================

# Run all E2E tests (skips if hardware unavailable):
pytest tests/e2e/ --run-hardware -v

# Run E2E tests for a specific module:
pytest tests/e2e/test_<module>_e2e.py --run-hardware -v

# See hardware availability before running:
pytest tests/e2e/ --run-hardware -v -s

================================================================================
"""

from __future__ import annotations

import asyncio
import csv
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest


# =============================================================================
# SECTION 1: IMPORTS
# =============================================================================
#
# Import the schema validation utilities for your module:
#
# from tests.infrastructure.schemas.csv_schema import (
#     YOUR_MODULE_SCHEMA,  # e.g., DRT_SDRT_SCHEMA, VOG_SVOG_SCHEMA
#     validate_csv_file,
#     ValidationResult,
# )
#
# Import the module's production code:
#
# from rpi_logger.modules.YourModule.transport import YourTransport
# from rpi_logger.modules.YourModule.handler import YourHandler


# =============================================================================
# SECTION 2: TEST CLASS STRUCTURE
# =============================================================================
#
# All E2E tests should:
# 1. Be in a class decorated with @pytest.mark.hardware and the module marker
# 2. Have clear docstrings explaining hardware requirements
# 3. Use the appropriate skip_without_* fixture


@pytest.mark.hardware
@pytest.mark.gps  # Replace 'gps' with your module: drt, vog, cameras, audio, eyetracker
class TestModuleEndToEndTemplate:
    """Template for end-to-end tests.

    Replace this class with your module's E2E tests. Each test class should
    focus on one module type and use the appropriate hardware marker.

    Hardware Markers Available:
        @pytest.mark.gps        - GPS module tests
        @pytest.mark.drt        - DRT module tests
        @pytest.mark.vog        - VOG module tests
        @pytest.mark.cameras    - USB camera tests
        @pytest.mark.audio      - Audio input tests
        @pytest.mark.eyetracker - Pupil Labs Neon tests
        @pytest.mark.csi_cameras - Raspberry Pi CSI camera tests

    Skip Fixtures Available:
        skip_without_gps        - Skip if no GPS hardware
        skip_without_drt        - Skip if no DRT hardware
        skip_without_vog        - Skip if no VOG hardware
        skip_without_cameras    - Skip if no USB cameras
        skip_without_audio      - Skip if no audio input
        skip_without_eyetracker - Skip if no eye tracker
        skip_without_csi_cameras - Skip if no CSI cameras
    """

    # -------------------------------------------------------------------------
    # Test 1: Device Detection
    # -------------------------------------------------------------------------
    # This test verifies that the hardware detection system finds your device.
    # It's the most basic E2E test and should always be included.

    def test_device_detection_template(
        self,
        hardware_availability,
        skip_without_gps,  # Replace with your module's skip fixture
    ):
        """Template: Verify device detection.

        Pattern:
        1. Use skip_without_* fixture to skip if hardware unavailable
        2. Get availability info from hardware_availability fixture
        3. Assert device is available and has expected properties

        Customize for your module:
        - Change skip_without_gps to skip_without_<your_module>
        - Change "GPS" to your module name
        - Add module-specific device checks
        """
        # Get availability for your module
        module_name = "GPS"  # Change to: "DRT", "VOG", "Cameras", "Audio", etc.
        avail = hardware_availability.get_availability(module_name)

        # Basic assertions (skip fixture ensures these pass)
        assert avail.available, f"{module_name} should be available"
        assert avail.devices, f"Should detect {module_name} device(s)"

        # Module-specific checks (examples):
        # For serial devices (GPS, DRT, VOG):
        #   device_paths = [d.device_path for d in avail.devices if d.device_path]
        #   assert device_paths, "Should have device path"
        #
        # For USB cameras:
        #   assert any("/dev/video" in d.device_path for d in avail.devices if d.device_path)
        #
        # For audio:
        #   assert any(d.extra.get("channels", 0) > 0 for d in avail.devices)

        # Log detection results for debugging
        print(f"\nDetected {module_name} devices:")
        for device in avail.devices:
            print(f"  - {device.device_path}: {device.reason}")

    # -------------------------------------------------------------------------
    # Test 2: Data Stream Reception
    # -------------------------------------------------------------------------
    # This test verifies that data is being received from the device.
    # The approach varies by device type (serial, network, USB, etc.)

    def test_data_stream_template(
        self,
        skip_without_gps,  # Replace with your module's skip fixture
        gps_device_path,   # Replace with your module's device info fixture
        cleanup_serial,    # Use appropriate cleanup fixture
        data_timeout,
    ):
        """Template: Verify data stream reception.

        Pattern:
        1. Get device path/info from fixture
        2. Open connection to device (add to cleanup list!)
        3. Read data with timeout
        4. Verify data format/content
        5. Cleanup is automatic via fixture

        Customize for your module:
        - Use appropriate device info fixture (gps_device_path, drt_device_info, etc.)
        - Use appropriate cleanup fixture (cleanup_serial, cleanup_cameras, etc.)
        - Implement device-specific connection and reading
        """
        # Example for serial devices:
        # import serial
        #
        # assert gps_device_path is not None
        # ser = serial.Serial(gps_device_path, 9600, timeout=1.0)
        # cleanup_serial.append(ser)  # Auto-cleanup
        #
        # data_received = []
        # start_time = time.time()
        # while time.time() - start_time < data_timeout:
        #     line = ser.readline().decode("ascii", errors="ignore").strip()
        #     if line:
        #         data_received.append(line)
        #         if len(data_received) >= 10:
        #             break
        #
        # assert data_received, "Should receive data from device"

        # Example for cameras:
        # import cv2
        #
        # cap = cv2.VideoCapture(camera_device_path)
        # cleanup_cameras.append(cap)  # Auto-cleanup
        #
        # ret, frame = cap.read()
        # assert ret, "Should capture frame"
        # assert frame is not None

        # Placeholder - implement for your module
        pytest.skip("Template test - implement for your module")

    # -------------------------------------------------------------------------
    # Test 3: Recording Creates Output File
    # -------------------------------------------------------------------------
    # This test verifies that the recording workflow produces output files.

    @pytest.mark.asyncio
    async def test_recording_creates_file_template(
        self,
        skip_without_gps,      # Replace with your module's skip fixture
        gps_device_path,       # Replace with your module's device info fixture
        recording_output_dir,  # Temporary directory for test output
        recording_duration,    # How long to record
    ):
        """Template: Verify recording creates output file.

        Pattern:
        1. Create transport and handler for your module
        2. Connect to device
        3. Start recording (get output file path)
        4. Start handler and wait for duration
        5. Stop handler and recording
        6. Verify output file exists and has content
        7. Cleanup transport

        Customize for your module:
        - Import your module's transport and handler classes
        - Configure appropriate settings for your device
        - Check for module-specific output (CSV, video, audio, etc.)
        """
        # Example pattern:
        #
        # from rpi_logger.modules.YourModule.transport import YourTransport
        # from rpi_logger.modules.YourModule.handler import YourHandler
        #
        # transport = YourTransport(device_path, settings...)
        # handler = YourHandler(device_id, recording_output_dir, transport)
        #
        # try:
        #     connected = await transport.connect()
        #     assert connected
        #
        #     output_path = handler.start_recording(trial_number=1)
        #     assert output_path is not None
        #
        #     await handler.start()
        #     await asyncio.sleep(recording_duration)
        #     await handler.stop()
        #     handler.stop_recording()
        #
        #     assert output_path.exists()
        #     assert output_path.stat().st_size > 0
        #
        # finally:
        #     await transport.disconnect()

        # Placeholder - implement for your module
        pytest.skip("Template test - implement for your module")

    # -------------------------------------------------------------------------
    # Test 4: Output Schema Validation
    # -------------------------------------------------------------------------
    # This test verifies that output files match the expected schema.

    @pytest.mark.asyncio
    async def test_schema_validation_template(
        self,
        skip_without_gps,
        gps_device_path,
        recording_output_dir,
        recording_duration,
    ):
        """Template: Verify output matches schema.

        Pattern:
        1. Record data (similar to previous test)
        2. Use validate_csv_file() with appropriate schema
        3. Check validation result
        4. Report any errors

        Customize for your module:
        - Import the correct schema (DRT_SDRT_SCHEMA, VOG_SVOG_SCHEMA, etc.)
        - Handle multiple output files if needed (e.g., EyeTracker has GAZE, IMU, EVENTS)
        """
        # Example pattern:
        #
        # from tests.infrastructure.schemas.csv_schema import (
        #     YOUR_MODULE_SCHEMA,
        #     validate_csv_file,
        # )
        #
        # # ... record data ...
        #
        # result = validate_csv_file(output_path, YOUR_MODULE_SCHEMA)
        #
        # print(f"Validation: {result.summary()}")
        # if result.errors:
        #     print(f"Errors: {result.errors[:5]}")
        #
        # assert result.is_valid, f"Schema validation failed: {result.errors[:3]}"

        # Placeholder - implement for your module
        pytest.skip("Template test - implement for your module")

    # -------------------------------------------------------------------------
    # Test 5: Data Validity Checks
    # -------------------------------------------------------------------------
    # This test verifies that recorded data is reasonable/valid.

    @pytest.mark.asyncio
    async def test_data_validity_template(
        self,
        skip_without_gps,
        gps_device_path,
        recording_output_dir,
        data_timeout,
    ):
        """Template: Verify recorded data is valid.

        Pattern:
        1. Record data
        2. Parse output file
        3. Check domain-specific validity rules

        Module-specific validity checks:
        - GPS: coordinates in range, satellites >= 0
        - DRT: reaction times > 0 or -1 (timeout)
        - VOG: shutter times >= 0
        - Cameras: frame count > 0, video duration reasonable
        - Audio: sample rate correct, no clipping
        - EyeTracker: gaze coordinates in [0,1], pupil diameter > 0
        """
        # Example pattern for CSV-based modules:
        #
        # with output_path.open("r") as f:
        #     reader = csv.DictReader(f)
        #     rows = list(reader)
        #
        # for row in rows:
        #     value = row.get("your_column")
        #     # Validate according to module rules
        #     assert MIN_VALUE <= float(value) <= MAX_VALUE

        # Placeholder - implement for your module
        pytest.skip("Template test - implement for your module")


# =============================================================================
# SECTION 3: ADDITIONAL TEST PATTERNS
# =============================================================================

@pytest.mark.hardware
@pytest.mark.gps  # Replace with your module marker
class TestModuleDataQualityTemplate:
    """Template for data quality tests.

    These tests focus on timing, consistency, and integrity of recorded data.
    They're separate from basic functionality tests to allow selective running.
    """

    @pytest.mark.asyncio
    async def test_timestamp_monotonicity_template(
        self,
        skip_without_gps,
        gps_device_path,
        recording_output_dir,
        recording_duration,
    ):
        """Template: Verify timestamps are monotonically increasing.

        This is a common data quality check for all modules that record
        timestamped data. Monotonic timestamps ensure no "time travel"
        in recordings.

        Pattern:
        1. Record data
        2. Extract record_time_mono column
        3. Verify each value >= previous value
        """
        # Implementation pattern:
        #
        # prev_mono = None
        # violations = []
        #
        # for i, row in enumerate(rows):
        #     mono = float(row.get("record_time_mono", 0))
        #     if prev_mono is not None and mono < prev_mono:
        #         violations.append(f"Row {i}: {mono} < {prev_mono}")
        #     prev_mono = mono
        #
        # assert not violations, f"Timestamps went backwards: {violations}"

        # Placeholder - implement for your module
        pytest.skip("Template test - implement for your module")

    @pytest.mark.asyncio
    async def test_trial_number_consistent_template(
        self,
        skip_without_gps,
        gps_device_path,
        recording_output_dir,
        recording_duration,
    ):
        """Template: Verify trial number is consistent.

        All rows in a single recording should have the same trial number
        unless the trial was explicitly updated during recording.
        """
        # Implementation pattern:
        #
        # trial_numbers = set(row.get("trial") for row in rows)
        # assert len(trial_numbers) == 1, f"Multiple trial numbers: {trial_numbers}"

        # Placeholder - implement for your module
        pytest.skip("Template test - implement for your module")


# =============================================================================
# SECTION 4: FIXTURE USAGE REFERENCE
# =============================================================================
#
# Available fixtures from conftest.py:
#
# Hardware Detection:
#   hardware_availability    - Full hardware detection object (session scope)
#   gps_available           - bool: is GPS available? (session scope)
#   drt_available           - bool: is DRT available? (session scope)
#   vog_available           - bool: is VOG available? (session scope)
#   cameras_available       - bool: are USB cameras available? (session scope)
#   audio_available         - bool: is audio input available? (session scope)
#   eyetracker_available    - bool: is eye tracker available? (session scope)
#   available_modules       - List[str]: modules with hardware (session scope)
#   unavailable_modules     - List[str]: modules without hardware (session scope)
#
# Hardware Skip Fixtures (function scope):
#   skip_without_gps        - Skips test if GPS unavailable
#   skip_without_drt        - Skips test if DRT unavailable
#   skip_without_vog        - Skips test if VOG unavailable
#   skip_without_cameras    - Skips test if cameras unavailable
#   skip_without_audio      - Skips test if audio unavailable
#   skip_without_eyetracker - Skips test if eye tracker unavailable
#   skip_without_csi_cameras - Skips test if CSI cameras unavailable
#   require_hardware        - Function to require specific hardware
#
# Device Information (session scope):
#   gps_device_path        - str: path to GPS device
#   drt_device_info        - Dict: DRT device info
#   vog_device_info        - Dict: VOG device info
#   camera_device_paths    - List[str]: camera device paths
#   audio_device_info      - Dict: audio device info
#
# Recording & Cleanup (function scope):
#   recording_output_dir   - Path: temp directory for recordings
#   recording_session_dir  - Path: session directory structure
#   cleanup_serial         - List: serial ports to close
#   cleanup_cameras        - List: cameras to release
#   cleanup_audio          - List: audio streams to stop
#   cleanup_devices        - Dict: all cleanup lists
#
# Timing (function scope):
#   recording_duration     - float: seconds to record (default 2.0)
#   connection_timeout     - float: seconds to wait for connect (default 5.0)
#   data_timeout           - float: seconds to wait for data (default 10.0)
#
# =============================================================================
# SECTION 5: BEST PRACTICES
# =============================================================================
#
# 1. ALWAYS use cleanup fixtures
#    - Add opened resources to cleanup lists immediately after opening
#    - This ensures cleanup even if test fails
#
# 2. Use appropriate timeouts
#    - Hardware can be slow; use data_timeout for reads
#    - Don't make timeouts too long (slow tests are bad)
#
# 3. Handle "no data" gracefully
#    - Some devices may not have data ready (GPS without fix)
#    - Use pytest.skip() for expected cases, fail only for errors
#
# 4. Log useful debug info
#    - Print device info, data counts, etc. with print()
#    - This helps debug when tests fail in CI
#
# 5. Test one thing per test
#    - Split complex validations into separate tests
#    - Makes failures easier to diagnose
#
# 6. Use meaningful assertions
#    - Include context in assertion messages
#    - Example: assert len(rows) > 0, f"Expected data rows, got {len(rows)}"
#
# 7. Document hardware requirements
#    - Use docstrings to explain what hardware is needed
#    - Include any special setup (e.g., "GPS needs sky view")
#
# =============================================================================
