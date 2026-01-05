"""End-to-end tests for GPS hardware operations.

This module tests real GPS device operations when hardware is available.
All tests are marked with @pytest.mark.gps and @pytest.mark.hardware
to ensure they are skipped gracefully when GPS hardware is not connected.

Hardware Requirements:
    - USB GPS receiver (U-Blox, Prolific, CP210x-based) or serial GPS
    - Device must output NMEA sentences (standard GPS protocol)

Test Coverage:
    - Device detection and enumeration
    - NMEA data stream reception
    - CSV file creation during recording
    - CSV schema validation
    - Position data validity checks

Usage:
    # Run all E2E tests (skips if no hardware)
    pytest tests/e2e/ --run-hardware

    # Run only GPS E2E tests
    pytest tests/e2e/test_gps_e2e.py --run-hardware -v

    # Run with verbose hardware detection output
    pytest tests/e2e/test_gps_e2e.py --run-hardware -v -s
"""

from __future__ import annotations

import asyncio
import csv
import time
from pathlib import Path
from typing import List, Optional

import pytest

# Schema validation imports
from tests.infrastructure.schemas.csv_schema import (
    GPS_SCHEMA,
    validate_csv_file,
    ValidationResult,
)


# =============================================================================
# GPS E2E Test Class
# =============================================================================

@pytest.mark.hardware
@pytest.mark.gps
class TestGPSEndToEnd:
    """End-to-end tests for GPS hardware.

    These tests verify that the GPS module works correctly with real hardware,
    from device detection through data recording and validation.

    All tests in this class require:
        - Physical GPS hardware connected
        - --run-hardware flag passed to pytest
    """

    def test_gps_device_detection(
        self,
        hardware_availability,
        skip_without_gps,
    ):
        """Verify GPS device found via USB/serial.

        This test verifies that the hardware detection system can find
        a GPS device. It checks:
        - GPS module is marked as available
        - At least one GPS device is detected
        - Device has a valid device path

        Hardware Required: GPS receiver (USB or serial)
        """
        avail = hardware_availability.get_availability("GPS")

        # Should be available (skip_without_gps ensures this)
        assert avail.available, f"GPS should be available: {avail.reason}"

        # Should have detected at least one device
        assert avail.devices, "GPS detection should return device information"
        assert len(avail.devices) > 0, "At least one GPS device should be detected"

        # Check that at least one device has a path
        device_paths = [d.device_path for d in avail.devices if d.device_path]
        assert device_paths, "At least one GPS device should have a device path"

        # Log what we found for debugging
        print(f"\nDetected GPS devices:")
        for device in avail.devices:
            print(f"  - {device.device_path}: {device.reason}")

    def test_gps_nmea_stream(
        self,
        skip_without_gps,
        gps_device_path,
        cleanup_serial,
        data_timeout,
    ):
        """Verify NMEA data stream received from GPS.

        This test connects to the GPS device and verifies that NMEA
        sentences are being received. It checks:
        - Serial connection can be established
        - NMEA sentences are received within timeout
        - Sentences start with '$' (NMEA standard)
        - At least one known sentence type received (GGA, RMC, etc.)

        Hardware Required: GPS receiver outputting NMEA
        """
        import serial

        assert gps_device_path is not None, "GPS device path should be available"

        # Open serial connection
        ser = serial.Serial(
            port=gps_device_path,
            baudrate=9600,
            timeout=1.0,
        )
        cleanup_serial.append(ser)  # Ensure cleanup on test end

        # Collect NMEA sentences
        sentences_received: List[str] = []
        sentence_types_seen: set = set()
        known_types = {"GGA", "RMC", "VTG", "GSA", "GSV", "GLL"}

        start_time = time.time()
        while time.time() - start_time < data_timeout:
            try:
                line = ser.readline().decode("ascii", errors="ignore").strip()
                if line.startswith("$"):
                    sentences_received.append(line)
                    # Extract sentence type (e.g., $GPGGA -> GGA, $GNGGA -> GGA)
                    if len(line) >= 6:
                        sentence_type = line[3:6] if line[1:3] in ("GP", "GN", "GL") else line[1:4]
                        sentence_types_seen.add(sentence_type)

                    # Stop once we have enough data
                    if len(sentences_received) >= 10:
                        break
            except Exception as e:
                print(f"Read error: {e}")
                continue

        # Verify we received NMEA data
        assert sentences_received, "Should have received NMEA sentences from GPS"
        assert all(s.startswith("$") for s in sentences_received), \
            "All sentences should start with '$'"

        # Check for known sentence types
        known_seen = sentence_types_seen & known_types
        assert known_seen, f"Should see known NMEA types, got: {sentence_types_seen}"

        print(f"\nReceived {len(sentences_received)} NMEA sentences")
        print(f"Sentence types seen: {sentence_types_seen}")

    @pytest.mark.asyncio
    async def test_gps_recording_creates_csv(
        self,
        skip_without_gps,
        gps_device_path,
        recording_output_dir,
        recording_duration,
    ):
        """Verify CSV file created during GPS recording.

        This test uses the GPS handler to start a recording session
        and verifies that a CSV file is created with data.

        Hardware Required: GPS receiver
        """
        from rpi_logger.modules.GPS.gps_core.transports.serial_transport import (
            SerialGPSTransport,
        )
        from rpi_logger.modules.GPS.gps_core.handlers.gps_handler import GPSHandler

        assert gps_device_path is not None, "GPS device path should be available"

        # Create transport and handler
        transport = SerialGPSTransport(gps_device_path, baudrate=9600)
        handler = GPSHandler(
            device_id=f"GPS:{gps_device_path}",
            output_dir=recording_output_dir,
            transport=transport,
        )

        try:
            # Connect and start
            connected = await transport.connect()
            assert connected, "Should connect to GPS device"

            # Start recording
            csv_path = handler.start_recording(trial_number=1)
            assert csv_path is not None, "start_recording should return CSV path"

            # Start handler and collect data
            await handler.start()

            # Wait for recording duration
            await asyncio.sleep(recording_duration)

            # Stop handler and recording
            await handler.stop()
            handler.stop_recording()

            # Verify CSV file was created
            assert csv_path.exists(), f"CSV file should exist at {csv_path}"
            assert csv_path.stat().st_size > 0, "CSV file should not be empty"

            # Verify we have data rows (not just header)
            with csv_path.open("r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)

            assert len(rows) >= 2, "CSV should have header plus at least one data row"
            print(f"\nCSV file created: {csv_path}")
            print(f"Total rows (including header): {len(rows)}")

        finally:
            # Cleanup
            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_gps_csv_schema_valid(
        self,
        skip_without_gps,
        gps_device_path,
        recording_output_dir,
        recording_duration,
    ):
        """Verify recorded CSV matches GPS schema.

        This test records GPS data and validates the output CSV against
        the defined GPS schema. It checks:
        - Header matches expected column names
        - Column count is correct (26 columns)
        - Data types are valid
        - No validation errors

        Hardware Required: GPS receiver with valid fix
        """
        from rpi_logger.modules.GPS.gps_core.transports.serial_transport import (
            SerialGPSTransport,
        )
        from rpi_logger.modules.GPS.gps_core.handlers.gps_handler import GPSHandler

        assert gps_device_path is not None

        # Create transport and handler
        transport = SerialGPSTransport(gps_device_path, baudrate=9600)
        handler = GPSHandler(
            device_id=f"GPS:{gps_device_path}",
            output_dir=recording_output_dir,
            transport=transport,
        )

        csv_path: Optional[Path] = None

        try:
            # Connect and record
            connected = await transport.connect()
            assert connected, "Should connect to GPS device"

            csv_path = handler.start_recording(trial_number=1)
            await handler.start()
            await asyncio.sleep(recording_duration)
            await handler.stop()
            handler.stop_recording()

            assert csv_path is not None and csv_path.exists()

        finally:
            await transport.disconnect()

        # Validate against GPS schema
        result: ValidationResult = validate_csv_file(csv_path, GPS_SCHEMA)

        # Print validation results for debugging
        print(f"\nSchema validation: {result.summary()}")
        if result.errors:
            print(f"Errors: {result.errors[:5]}")  # Show first 5 errors
        if result.warnings:
            print(f"Warnings: {result.warnings[:5]}")

        # Check validation passed
        assert result.is_valid, f"CSV should match GPS schema: {result.errors[:3]}"
        assert result.row_count > 0, "Should have data rows"

    @pytest.mark.asyncio
    async def test_gps_position_data_valid(
        self,
        skip_without_gps,
        gps_device_path,
        recording_output_dir,
        data_timeout,
    ):
        """Verify position data is reasonable (coordinates in valid range).

        This test checks that recorded GPS position data falls within
        valid geographic ranges:
        - Latitude: -90 to +90 degrees
        - Longitude: -180 to +180 degrees
        - Altitude: -500 to 50000 meters (reasonable Earth range)

        Note: This test may produce empty/null position data if GPS
        does not have a fix. The test validates any data that IS present.

        Hardware Required: GPS receiver (ideally with satellite view)
        """
        from rpi_logger.modules.GPS.gps_core.transports.serial_transport import (
            SerialGPSTransport,
        )
        from rpi_logger.modules.GPS.gps_core.handlers.gps_handler import GPSHandler

        assert gps_device_path is not None

        # Create transport and handler
        transport = SerialGPSTransport(gps_device_path, baudrate=9600)
        handler = GPSHandler(
            device_id=f"GPS:{gps_device_path}",
            output_dir=recording_output_dir,
            transport=transport,
        )

        csv_path: Optional[Path] = None

        try:
            # Connect and record for longer to hopefully get a fix
            connected = await transport.connect()
            assert connected, "Should connect to GPS device"

            csv_path = handler.start_recording(trial_number=1)
            await handler.start()

            # Wait longer for potential GPS fix
            await asyncio.sleep(min(data_timeout, 5.0))

            await handler.stop()
            handler.stop_recording()

            assert csv_path is not None and csv_path.exists()

        finally:
            await transport.disconnect()

        # Parse CSV and validate position data
        with csv_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert rows, "Should have data rows"

        # Check position data validity
        valid_positions = 0
        invalid_positions = []

        for i, row in enumerate(rows):
            lat_str = row.get("latitude_deg", "")
            lon_str = row.get("longitude_deg", "")
            alt_str = row.get("altitude_m", "")

            # Skip rows without position data (no fix)
            if not lat_str or not lon_str:
                continue

            try:
                lat = float(lat_str)
                lon = float(lon_str)
                alt = float(alt_str) if alt_str else None

                # Validate ranges
                if not (-90 <= lat <= 90):
                    invalid_positions.append(f"Row {i}: latitude {lat} out of range")
                elif not (-180 <= lon <= 180):
                    invalid_positions.append(f"Row {i}: longitude {lon} out of range")
                elif alt is not None and not (-500 <= alt <= 50000):
                    invalid_positions.append(f"Row {i}: altitude {alt} out of range")
                else:
                    valid_positions += 1

            except ValueError as e:
                invalid_positions.append(f"Row {i}: parse error - {e}")

        # Report results
        print(f"\nPosition data analysis:")
        print(f"  Total rows: {len(rows)}")
        print(f"  Valid positions: {valid_positions}")
        print(f"  Invalid positions: {len(invalid_positions)}")

        if invalid_positions:
            print(f"  Issues: {invalid_positions[:3]}")

        # Test passes if no invalid positions (empty data is OK - no fix)
        assert not invalid_positions, f"Found invalid positions: {invalid_positions}"

        # Optionally warn if no positions found (no GPS fix)
        if valid_positions == 0:
            pytest.skip(
                "No valid GPS positions recorded - device may not have satellite fix. "
                "Test passes but skipping further validation."
            )


# =============================================================================
# Additional GPS E2E Tests
# =============================================================================

@pytest.mark.hardware
@pytest.mark.gps
class TestGPSDataQuality:
    """Additional data quality tests for GPS recordings.

    These tests focus on data integrity and timing aspects of GPS recordings.
    """

    @pytest.mark.asyncio
    async def test_gps_monotonic_timestamps(
        self,
        skip_without_gps,
        gps_device_path,
        recording_output_dir,
        recording_duration,
    ):
        """Verify monotonic timestamps are increasing.

        This test checks that the record_time_mono column contains
        strictly increasing values, ensuring no time travel in recordings.

        Hardware Required: GPS receiver
        """
        from rpi_logger.modules.GPS.gps_core.transports.serial_transport import (
            SerialGPSTransport,
        )
        from rpi_logger.modules.GPS.gps_core.handlers.gps_handler import GPSHandler

        assert gps_device_path is not None

        transport = SerialGPSTransport(gps_device_path, baudrate=9600)
        handler = GPSHandler(
            device_id=f"GPS:{gps_device_path}",
            output_dir=recording_output_dir,
            transport=transport,
        )

        csv_path: Optional[Path] = None

        try:
            connected = await transport.connect()
            assert connected

            csv_path = handler.start_recording(trial_number=1)
            await handler.start()
            await asyncio.sleep(recording_duration)
            await handler.stop()
            handler.stop_recording()

        finally:
            await transport.disconnect()

        assert csv_path is not None and csv_path.exists()

        # Check monotonic timestamps
        with csv_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        prev_mono = None
        violations = []

        for i, row in enumerate(rows):
            mono_str = row.get("record_time_mono", "")
            if not mono_str:
                continue

            try:
                mono = float(mono_str)
                if prev_mono is not None and mono < prev_mono:
                    violations.append(
                        f"Row {i}: {mono} < {prev_mono} (time went backwards)"
                    )
                prev_mono = mono
            except ValueError:
                continue

        print(f"\nMonotonic timestamp check:")
        print(f"  Total rows checked: {len(rows)}")
        print(f"  Violations: {len(violations)}")

        assert not violations, f"Monotonic timestamps should be increasing: {violations}"

    @pytest.mark.asyncio
    async def test_gps_device_id_consistent(
        self,
        skip_without_gps,
        gps_device_path,
        recording_output_dir,
        recording_duration,
    ):
        """Verify device_id is consistent across all rows.

        This test ensures that the device_id column contains the same
        value for all rows in a recording session.

        Hardware Required: GPS receiver
        """
        from rpi_logger.modules.GPS.gps_core.transports.serial_transport import (
            SerialGPSTransport,
        )
        from rpi_logger.modules.GPS.gps_core.handlers.gps_handler import GPSHandler

        assert gps_device_path is not None

        expected_device_id = f"GPS:{gps_device_path}"
        transport = SerialGPSTransport(gps_device_path, baudrate=9600)
        handler = GPSHandler(
            device_id=expected_device_id,
            output_dir=recording_output_dir,
            transport=transport,
        )

        csv_path: Optional[Path] = None

        try:
            connected = await transport.connect()
            assert connected

            csv_path = handler.start_recording(trial_number=1)
            await handler.start()
            await asyncio.sleep(recording_duration)
            await handler.stop()
            handler.stop_recording()

        finally:
            await transport.disconnect()

        assert csv_path is not None and csv_path.exists()

        # Check device_id consistency
        with csv_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        device_ids = set(row.get("device_id", "") for row in rows)

        print(f"\nDevice ID consistency check:")
        print(f"  Expected: {expected_device_id}")
        print(f"  Found IDs: {device_ids}")

        assert len(device_ids) == 1, f"All rows should have same device_id: {device_ids}"
        assert expected_device_id in device_ids, \
            f"Device ID should match: expected {expected_device_id}, got {device_ids}"
