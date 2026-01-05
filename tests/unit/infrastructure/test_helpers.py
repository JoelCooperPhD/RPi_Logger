"""Unit tests for test infrastructure helpers.

Tests the assertion helpers and data generators in the helpers package.
"""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path
from typing import List

import pytest

from tests.infrastructure.schemas.csv_schema import (
    GPS_SCHEMA,
    DRT_SDRT_SCHEMA,
    DRT_WDRT_SCHEMA,
    VOG_SVOG_SCHEMA,
    VOG_WVOG_SCHEMA,
    NOTES_SCHEMA,
)
from tests.infrastructure.helpers import (
    # Assertions
    CSVValidationError,
    TimingValidationError,
    assert_csv_valid,
    assert_timing_monotonic,
    assert_no_time_travel,
    assert_csv_row_count,
    assert_column_values,
    # Generators
    generate_nmea_sentence,
    generate_csv_row,
    generate_csv_rows,
    generate_mock_device_response,
    generate_mock_command_response,
    generate_gps_track,
)


# =============================================================================
# Tests for assertion helpers
# =============================================================================

class TestAssertCsvValid:
    """Tests for assert_csv_valid function."""

    def test_valid_csv_passes(self, tmp_path):
        """Test that a valid CSV file passes validation."""
        csv_path = tmp_path / "test.csv"

        # Generate valid GPS data
        rows = generate_csv_rows(GPS_SCHEMA, count=5)
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(GPS_SCHEMA.header)
            writer.writerows(rows)

        result = assert_csv_valid(csv_path, GPS_SCHEMA)
        assert result.is_valid
        assert result.row_count == 5

    def test_invalid_csv_raises_error(self, tmp_path):
        """Test that an invalid CSV file raises CSVValidationError."""
        csv_path = tmp_path / "invalid.csv"

        # Write CSV with wrong header
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            f.write("wrong,header,columns\n")
            f.write("1,2,3\n")

        with pytest.raises(CSVValidationError) as exc_info:
            assert_csv_valid(csv_path, GPS_SCHEMA)

        assert "validation failed" in str(exc_info.value).lower()
        assert exc_info.value.path == csv_path

    def test_missing_file_raises_error(self, tmp_path):
        """Test that a missing file raises FileNotFoundError."""
        csv_path = tmp_path / "nonexistent.csv"

        with pytest.raises(FileNotFoundError):
            assert_csv_valid(csv_path, GPS_SCHEMA)

    def test_empty_file_raises_error_by_default(self, tmp_path):
        """Test that an empty file (header only) raises error by default."""
        csv_path = tmp_path / "empty.csv"

        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            f.write(GPS_SCHEMA.header_string + "\n")

        with pytest.raises(CSVValidationError) as exc_info:
            assert_csv_valid(csv_path, GPS_SCHEMA)

        assert "no data rows" in str(exc_info.value).lower()

    def test_empty_file_allowed_with_flag(self, tmp_path):
        """Test that an empty file passes with allow_empty=True."""
        csv_path = tmp_path / "empty.csv"

        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            f.write(GPS_SCHEMA.header_string + "\n")

        result = assert_csv_valid(csv_path, GPS_SCHEMA, allow_empty=True)
        assert result.is_valid
        assert result.row_count == 0


class TestAssertTimingMonotonic:
    """Tests for assert_timing_monotonic function."""

    def test_monotonic_timestamps_pass(self, tmp_path):
        """Test that monotonically increasing timestamps pass."""
        csv_path = tmp_path / "monotonic.csv"

        rows = generate_csv_rows(GPS_SCHEMA, count=10, time_increment=0.1)
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(GPS_SCHEMA.header)
            writer.writerows(rows)

        timestamps = assert_timing_monotonic(csv_path)
        assert len(timestamps) == 10

        # Verify timestamps are increasing
        for i in range(1, len(timestamps)):
            assert timestamps[i][1] > timestamps[i-1][1]

    def test_non_monotonic_timestamps_raise_error(self, tmp_path):
        """Test that decreasing timestamps raise TimingValidationError."""
        csv_path = tmp_path / "non_monotonic.csv"

        # Generate rows with decreasing timestamps
        rows = generate_csv_rows(GPS_SCHEMA, count=5, time_increment=-0.1)
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(GPS_SCHEMA.header)
            writer.writerows(rows)

        with pytest.raises(TimingValidationError) as exc_info:
            assert_timing_monotonic(csv_path)

        assert "violation" in str(exc_info.value).lower()
        assert exc_info.value.path == csv_path

    def test_equal_timestamps_raise_error_with_strict(self, tmp_path):
        """Test that equal timestamps raise error with strict=True."""
        csv_path = tmp_path / "equal_times.csv"

        # Generate rows with same timestamp
        rows = generate_csv_rows(GPS_SCHEMA, count=3, time_increment=0)
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(GPS_SCHEMA.header)
            writer.writerows(rows)

        with pytest.raises(TimingValidationError):
            assert_timing_monotonic(csv_path, strict=True)

    def test_equal_timestamps_pass_without_strict(self, tmp_path):
        """Test that equal timestamps pass with strict=False."""
        csv_path = tmp_path / "equal_times.csv"

        rows = generate_csv_rows(GPS_SCHEMA, count=3, time_increment=0)
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(GPS_SCHEMA.header)
            writer.writerows(rows)

        timestamps = assert_timing_monotonic(csv_path, strict=False)
        assert len(timestamps) == 3

    def test_missing_column_raises_keyerror(self, tmp_path):
        """Test that a missing time column raises KeyError."""
        csv_path = tmp_path / "no_time_column.csv"

        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            f.write("a,b,c\n")
            f.write("1,2,3\n")

        with pytest.raises(KeyError):
            assert_timing_monotonic(csv_path, time_column="nonexistent")


class TestAssertNoTimeTravel:
    """Tests for assert_no_time_travel function."""

    def test_valid_timing_passes(self, tmp_path):
        """Test that valid timing passes."""
        csv_path = tmp_path / "valid_timing.csv"

        rows = generate_csv_rows(GPS_SCHEMA, count=10, time_increment=1.0)
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(GPS_SCHEMA.header)
            writer.writerows(rows)

        stats = assert_no_time_travel(csv_path)
        assert stats['total_rows'] == 10
        assert stats['mono_duration'] == pytest.approx(9.0, rel=0.01)

    def test_time_travel_raises_error(self, tmp_path):
        """Test that backward time jump raises error."""
        csv_path = tmp_path / "time_travel.csv"

        # Create rows with time travel
        rows = generate_csv_rows(GPS_SCHEMA, count=5, time_increment=1.0)
        # Make third row go back in time
        mono_col = GPS_SCHEMA.header.index("record_time_mono")
        rows[2][mono_col] = str(float(rows[0][mono_col]) - 5)

        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(GPS_SCHEMA.header)
            writer.writerows(rows)

        with pytest.raises(TimingValidationError) as exc_info:
            assert_no_time_travel(csv_path)

        assert "time travel" in str(exc_info.value).lower()


class TestAssertCsvRowCount:
    """Tests for assert_csv_row_count function."""

    def test_exact_count_passes(self, tmp_path):
        """Test that exact row count passes."""
        csv_path = tmp_path / "exact.csv"

        rows = generate_csv_rows(GPS_SCHEMA, count=5)
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(GPS_SCHEMA.header)
            writer.writerows(rows)

        count = assert_csv_row_count(csv_path, exact_rows=5)
        assert count == 5

    def test_wrong_count_raises_error(self, tmp_path):
        """Test that wrong row count raises error."""
        csv_path = tmp_path / "wrong_count.csv"

        rows = generate_csv_rows(GPS_SCHEMA, count=5)
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(GPS_SCHEMA.header)
            writer.writerows(rows)

        with pytest.raises(AssertionError) as exc_info:
            assert_csv_row_count(csv_path, exact_rows=10)

        assert "expected exactly 10" in str(exc_info.value).lower()

    def test_min_rows_passes(self, tmp_path):
        """Test that min_rows passes when count is sufficient."""
        csv_path = tmp_path / "min.csv"

        rows = generate_csv_rows(GPS_SCHEMA, count=10)
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(GPS_SCHEMA.header)
            writer.writerows(rows)

        count = assert_csv_row_count(csv_path, min_rows=5)
        assert count == 10

    def test_max_rows_raises_when_exceeded(self, tmp_path):
        """Test that max_rows raises when exceeded."""
        csv_path = tmp_path / "max.csv"

        rows = generate_csv_rows(GPS_SCHEMA, count=10)
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(GPS_SCHEMA.header)
            writer.writerows(rows)

        with pytest.raises(AssertionError) as exc_info:
            assert_csv_row_count(csv_path, max_rows=5)

        assert "at most 5" in str(exc_info.value).lower()


class TestAssertColumnValues:
    """Tests for assert_column_values function."""

    def test_allowed_values_pass(self, tmp_path):
        """Test that allowed values pass."""
        csv_path = tmp_path / "allowed.csv"

        rows = generate_csv_rows(GPS_SCHEMA, count=5, fix_valid=1)
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(GPS_SCHEMA.header)
            writer.writerows(rows)

        values = assert_column_values(csv_path, "fix_valid", allowed_values=[0, 1])
        assert all(v in ("0", "1") for v in values)

    def test_invalid_value_raises_error(self, tmp_path):
        """Test that invalid value raises error."""
        csv_path = tmp_path / "invalid.csv"

        rows = generate_csv_rows(GPS_SCHEMA, count=5, fix_valid=2)
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(GPS_SCHEMA.header)
            writer.writerows(rows)

        with pytest.raises(AssertionError) as exc_info:
            assert_column_values(csv_path, "fix_valid", allowed_values=[0, 1])

        assert "not in allowed values" in str(exc_info.value)


# =============================================================================
# Tests for NMEA generator
# =============================================================================

class TestGenerateNmeaSentence:
    """Tests for generate_nmea_sentence function."""

    def test_gga_sentence_format(self):
        """Test GGA sentence has correct format."""
        nmea = generate_nmea_sentence(sentence_type="GGA", lat=48.1173, lon=11.5167)

        assert nmea.startswith("$GPGGA")
        assert nmea.endswith("\r\n")
        assert "*" in nmea  # Has checksum

    def test_rmc_sentence_format(self):
        """Test RMC sentence has correct format."""
        nmea = generate_nmea_sentence(sentence_type="RMC", lat=48.1173, lon=11.5167)

        assert nmea.startswith("$GPRMC")
        assert nmea.endswith("\r\n")
        assert ",A," in nmea  # Valid fix

    def test_rmc_invalid_fix(self):
        """Test RMC sentence with invalid fix."""
        nmea = generate_nmea_sentence(sentence_type="RMC", fix_valid=False)

        assert ",V," in nmea  # Invalid fix

    def test_vtg_sentence_format(self):
        """Test VTG sentence has correct format."""
        nmea = generate_nmea_sentence(sentence_type="VTG", speed_knots=10.0)

        assert nmea.startswith("$GPVTG")
        assert ",T," in nmea  # True course

    def test_gsa_sentence_format(self):
        """Test GSA sentence has correct format."""
        nmea = generate_nmea_sentence(sentence_type="GSA")

        assert nmea.startswith("$GPGSA")
        assert nmea.endswith("\r\n")

    def test_gll_sentence_format(self):
        """Test GLL sentence has correct format."""
        nmea = generate_nmea_sentence(sentence_type="GLL", lat=48.1173, lon=11.5167)

        assert nmea.startswith("$GPGLL")
        assert nmea.endswith("\r\n")

    def test_checksum_calculation(self):
        """Test that checksum is correctly calculated."""
        nmea = generate_nmea_sentence(sentence_type="GGA")

        # Extract sentence content and checksum
        content = nmea[1:].split("*")[0]  # After $ and before *
        checksum = nmea.strip()[-2:]  # Last 2 chars before \r\n

        # Recalculate checksum
        calculated = 0
        for char in content:
            calculated ^= ord(char)

        assert f"{calculated:02X}" == checksum

    def test_without_checksum(self):
        """Test generating sentence without checksum."""
        nmea = generate_nmea_sentence(sentence_type="GGA", include_checksum=False)

        assert nmea.startswith("$GPGGA")
        assert "*" not in nmea

    def test_latitude_conversion(self):
        """Test latitude is correctly converted to NMEA format."""
        nmea = generate_nmea_sentence(sentence_type="GGA", lat=48.1173, lon=11.5167)

        # 48.1173 degrees = 48 degrees, 7.038 minutes
        assert ",4807." in nmea  # Lat degrees and start of minutes
        assert ",N," in nmea  # North

    def test_southern_latitude(self):
        """Test southern hemisphere latitude."""
        nmea = generate_nmea_sentence(sentence_type="GGA", lat=-33.8688, lon=151.2093)

        assert ",S," in nmea  # South

    def test_western_longitude(self):
        """Test western hemisphere longitude."""
        nmea = generate_nmea_sentence(sentence_type="GGA", lat=37.7749, lon=-122.4194)

        assert ",W," in nmea  # West

    def test_invalid_sentence_type_raises_error(self):
        """Test that invalid sentence type raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            generate_nmea_sentence(sentence_type="INVALID")

        assert "unsupported sentence type" in str(exc_info.value).lower()

    def test_invalid_latitude_raises_error(self):
        """Test that invalid latitude raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            generate_nmea_sentence(lat=91.0)

        assert "latitude" in str(exc_info.value).lower()

    def test_invalid_longitude_raises_error(self):
        """Test that invalid longitude raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            generate_nmea_sentence(lon=181.0)

        assert "longitude" in str(exc_info.value).lower()


# =============================================================================
# Tests for CSV row generator
# =============================================================================

class TestGenerateCsvRow:
    """Tests for generate_csv_row function."""

    def test_gps_row_column_count(self):
        """Test GPS row has correct column count."""
        row = generate_csv_row(GPS_SCHEMA)
        assert len(row) == GPS_SCHEMA.column_count

    def test_drt_sdrt_row_column_count(self):
        """Test sDRT row has correct column count."""
        row = generate_csv_row(DRT_SDRT_SCHEMA)
        assert len(row) == DRT_SDRT_SCHEMA.column_count

    def test_vog_wvog_row_column_count(self):
        """Test wVOG row has correct column count."""
        row = generate_csv_row(VOG_WVOG_SCHEMA)
        assert len(row) == VOG_WVOG_SCHEMA.column_count

    def test_override_single_value(self):
        """Test overriding a single value."""
        row = generate_csv_row(GPS_SCHEMA, latitude_deg=48.5)
        lat_idx = GPS_SCHEMA.header.index("latitude_deg")
        assert row[lat_idx] == "48.5"

    def test_override_multiple_values(self):
        """Test overriding multiple values."""
        row = generate_csv_row(GPS_SCHEMA, trial=5, latitude_deg=48.5, longitude_deg=11.5)

        assert row[0] == "5"  # trial
        lat_idx = GPS_SCHEMA.header.index("latitude_deg")
        lon_idx = GPS_SCHEMA.header.index("longitude_deg")
        assert row[lat_idx] == "48.5"
        assert row[lon_idx] == "11.5"

    def test_as_dict_returns_dict(self):
        """Test as_dict returns dictionary."""
        row = generate_csv_row(GPS_SCHEMA, as_dict=True, latitude_deg=48.5)

        assert isinstance(row, dict)
        assert row["latitude_deg"] == "48.5"

    def test_invalid_override_key_raises_error(self):
        """Test that invalid override key raises KeyError."""
        with pytest.raises(KeyError) as exc_info:
            generate_csv_row(GPS_SCHEMA, nonexistent_column=123)

        assert "invalid column names" in str(exc_info.value).lower()

    def test_generated_row_passes_validation(self, tmp_path):
        """Test that generated rows pass schema validation."""
        csv_path = tmp_path / "generated.csv"

        rows = generate_csv_rows(GPS_SCHEMA, count=10)
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(GPS_SCHEMA.header)
            writer.writerows(rows)

        result = assert_csv_valid(csv_path, GPS_SCHEMA)
        assert result.is_valid


class TestGenerateCsvRows:
    """Tests for generate_csv_rows function."""

    def test_generates_correct_count(self):
        """Test that correct number of rows are generated."""
        rows = generate_csv_rows(GPS_SCHEMA, count=10)
        assert len(rows) == 10

    def test_timestamps_are_incrementing(self):
        """Test that timestamps increment correctly."""
        rows = generate_csv_rows(
            GPS_SCHEMA,
            count=5,
            time_increment=0.5,
            start_mono=100.0,
        )

        mono_idx = GPS_SCHEMA.header.index("record_time_mono")

        for i, row in enumerate(rows):
            expected = 100.0 + (i * 0.5)
            assert float(row[mono_idx]) == pytest.approx(expected)

    def test_base_overrides_applied(self):
        """Test that base overrides are applied to all rows."""
        rows = generate_csv_rows(GPS_SCHEMA, count=5, trial=3)

        for row in rows:
            assert row[0] == "3"  # trial is first column


# =============================================================================
# Tests for device response generator
# =============================================================================

class TestGenerateMockDeviceResponse:
    """Tests for generate_mock_device_response function."""

    def test_gps_response(self):
        """Test GPS device response generation."""
        response = generate_mock_device_response("gps", lat=48.1173, lon=11.5167)

        assert response.startswith(b"$GPGGA")
        assert response.endswith(b"\r\n")

    def test_gps_rmc_response(self):
        """Test GPS RMC response generation."""
        response = generate_mock_device_response("gps", sentence_type="RMC")

        assert response.startswith(b"$GPRMC")

    def test_sdrt_response(self):
        """Test sDRT device response generation."""
        response = generate_mock_device_response(
            "sdrt",
            trial_number=1,
            reaction_time_ms=250,
        )

        assert b"trl>" in response
        assert b",250" in response

    def test_wdrt_response(self):
        """Test wDRT device response generation."""
        response = generate_mock_device_response(
            "wdrt",
            trial_number=1,
            reaction_time_ms=250,
            battery_percent=85,
        )

        assert b"dta>" in response
        assert b",85," in response

    def test_svog_response(self):
        """Test sVOG device response generation."""
        response = generate_mock_device_response(
            "svog",
            trial_number=1,
            open_ms=1500,
            closed_ms=1500,
        )

        assert b"data|" in response
        assert b",1500," in response

    def test_wvog_response(self):
        """Test wVOG device response generation."""
        response = generate_mock_device_response(
            "wvog",
            trial_number=1,
            open_ms=1500,
            closed_ms=1500,
            lens="A",
        )

        assert b"dta>" in response
        assert b",A," in response

    def test_invalid_device_type_raises_error(self):
        """Test that invalid device type raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            generate_mock_device_response("invalid_device")

        assert "unsupported device type" in str(exc_info.value).lower()


class TestGenerateMockCommandResponse:
    """Tests for generate_mock_command_response function."""

    def test_sdrt_exp_start(self):
        """Test sDRT experiment start response."""
        response = generate_mock_command_response("sdrt", "exp_start")
        assert response == b"expStart\r\n"

    def test_sdrt_exp_stop(self):
        """Test sDRT experiment stop response."""
        response = generate_mock_command_response("sdrt", "exp_stop")
        assert response == b"expStop\r\n"

    def test_wvog_exp_start(self):
        """Test wVOG experiment start response."""
        response = generate_mock_command_response("wvog", "exp>1")
        assert response == b"exp>1\n"

    def test_invalid_command_raises_error(self):
        """Test that invalid command raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            generate_mock_command_response("sdrt", "invalid_cmd")

        assert "unknown command" in str(exc_info.value).lower()


# =============================================================================
# Tests for GPS track generator
# =============================================================================

class TestGenerateGpsTrack:
    """Tests for generate_gps_track function."""

    def test_generates_correct_count(self):
        """Test that correct number of points are generated."""
        track = generate_gps_track(points=10)
        assert len(track) == 10

    def test_first_point_is_start_location(self):
        """Test that first point is at start location."""
        track = generate_gps_track(start_lat=48.1173, start_lon=11.5167, points=5)

        assert track[0]["lat"] == pytest.approx(48.1173, rel=1e-6)
        assert track[0]["lon"] == pytest.approx(11.5167, rel=1e-6)

    def test_track_moves_north(self):
        """Test track movement northward (bearing 0)."""
        track = generate_gps_track(
            start_lat=48.0,
            start_lon=11.0,
            points=5,
            bearing=0,
            speed_mps=100,
            interval_seconds=1,
        )

        # Latitude should increase going north
        for i in range(1, len(track)):
            assert track[i]["lat"] > track[i-1]["lat"]

    def test_track_moves_east(self):
        """Test track movement eastward (bearing 90)."""
        track = generate_gps_track(
            start_lat=48.0,
            start_lon=11.0,
            points=5,
            bearing=90,
            speed_mps=100,
            interval_seconds=1,
        )

        # Longitude should increase going east (at this latitude)
        for i in range(1, len(track)):
            assert track[i]["lon"] > track[i-1]["lon"]

    def test_track_points_have_required_fields(self):
        """Test that track points have all required fields."""
        track = generate_gps_track(points=3)

        for point in track:
            assert "lat" in point
            assert "lon" in point
            assert "speed_mps" in point
            assert "bearing" in point
