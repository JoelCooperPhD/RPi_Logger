"""Unit tests for GPS data logger."""

import csv
import time
from pathlib import Path
import pytest

from rpi_logger.modules.GPS.gps_core.data_logger import GPSDataLogger
from rpi_logger.modules.GPS.gps_core.parsers.nmea_types import GPSFixSnapshot
from rpi_logger.modules.GPS.gps_core.constants import GPS_CSV_HEADER


class TestGPSDataLogger:
    """Test GPS data logger functionality."""

    def test_initialization(self, tmp_path):
        """Test logger initialization."""
        logger = GPSDataLogger(tmp_path, "GPS:serial0")
        assert logger.output_dir == tmp_path
        assert logger.device_id == "GPS:serial0"
        assert logger.is_recording is False
        assert logger.filepath is None

    def test_sanitize_device_id(self, tmp_path):
        """Test device ID sanitization."""
        logger = GPSDataLogger(tmp_path, "GPS:serial0")
        assert logger._sanitize_device_id() == "GPS_serial0"

        logger2 = GPSDataLogger(tmp_path, "/dev/ttyUSB0")
        assert logger2._sanitize_device_id() == "_dev_ttyUSB0"

    def test_start_recording_creates_file(self, tmp_path):
        """Test that start_recording creates a CSV file."""
        logger = GPSDataLogger(tmp_path, "GPS:serial0")
        path = logger.start_recording(trial_number=1)

        assert path is not None
        assert path.exists()
        assert path.suffix == ".csv"
        assert logger.is_recording is True
        assert logger.filepath == path

        logger.stop_recording()

    def test_start_recording_writes_header(self, tmp_path):
        """Test that CSV header is written."""
        logger = GPSDataLogger(tmp_path, "GPS:serial0")
        path = logger.start_recording()
        logger.stop_recording()

        # Read the file and check header
        with open(path, "r") as f:
            reader = csv.reader(f)
            header = next(reader)
            assert header == GPS_CSV_HEADER

    def test_start_recording_twice(self, tmp_path):
        """Test that starting recording twice returns existing path."""
        logger = GPSDataLogger(tmp_path, "GPS:serial0")
        path1 = logger.start_recording()
        path2 = logger.start_recording()

        assert path1 == path2
        logger.stop_recording()

    def test_stop_recording(self, tmp_path):
        """Test stopping recording."""
        logger = GPSDataLogger(tmp_path, "GPS:serial0")
        logger.start_recording()
        assert logger.is_recording is True

        logger.stop_recording()
        assert logger.is_recording is False
        assert logger.filepath is None

    def test_stop_recording_when_not_recording(self, tmp_path):
        """Test that stopping when not recording is a no-op."""
        logger = GPSDataLogger(tmp_path, "GPS:serial0")
        logger.stop_recording()  # Should not raise
        assert logger.is_recording is False

    def test_log_fix(self, tmp_path):
        """Test logging a GPS fix."""
        logger = GPSDataLogger(tmp_path, "GPS:serial0")
        path = logger.start_recording(trial_number=1)

        fix = GPSFixSnapshot(
            latitude=48.1173,
            longitude=11.5166,
            altitude_m=545.4,
            speed_knots=22.4,
            speed_kmh=41.5,
            speed_mph=25.8,
            course_deg=84.4,
            fix_quality=1,
            fix_mode="3D",
            fix_valid=True,
            satellites_in_use=8,
            satellites_in_view=11,
            hdop=0.9,
            pdop=1.3,
            vdop=1.0,
        )

        result = logger.log_fix(fix, "GGA", "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,47.0,M,,*47")
        assert result is True

        # Give writer thread time to flush
        time.sleep(0.6)
        logger.stop_recording()

        # Verify data was written
        with open(path, "r") as f:
            reader = csv.reader(f)
            header = next(reader)
            row = next(reader)

        assert header == GPS_CSV_HEADER
        assert int(row[0]) == 1  # trial
        assert row[1] == "GPS"  # module
        lat_idx = header.index("latitude_deg")
        lon_idx = header.index("longitude_deg")
        alt_idx = header.index("altitude_m")
        sentence_idx = header.index("sentence_type")
        assert float(row[lat_idx]) == pytest.approx(48.1173)  # latitude
        assert float(row[lon_idx]) == pytest.approx(11.5166)  # longitude
        assert float(row[alt_idx]) == pytest.approx(545.4)  # altitude
        assert row[sentence_idx] == "GGA"  # sentence_type

    def test_log_fix_not_recording(self, tmp_path):
        """Test that logging when not recording returns False."""
        logger = GPSDataLogger(tmp_path, "GPS:serial0")

        fix = GPSFixSnapshot(latitude=48.1173, longitude=11.5166)
        result = logger.log_fix(fix, "GGA", "$GPGGA...")

        assert result is False

    def test_log_multiple_fixes(self, tmp_path):
        """Test logging multiple GPS fixes."""
        logger = GPSDataLogger(tmp_path, "GPS:serial0")
        path = logger.start_recording(trial_number=1)

        for i in range(5):
            fix = GPSFixSnapshot(
                latitude=48.0 + i * 0.001,
                longitude=11.0 + i * 0.001,
                fix_valid=True,
            )
            logger.log_fix(fix, "RMC", f"$GPRMC,{i}...")

        # Give writer thread time to flush
        time.sleep(0.6)
        logger.stop_recording()

        # Count rows (excluding header)
        with open(path, "r") as f:
            reader = csv.reader(f)
            next(reader)  # Skip header
            rows = list(reader)

        assert len(rows) == 5

    def test_update_trial_number(self, tmp_path):
        """Test updating trial number during recording."""
        logger = GPSDataLogger(tmp_path, "GPS:serial0")
        path = logger.start_recording(trial_number=1)

        fix = GPSFixSnapshot(latitude=48.0, longitude=11.0)
        logger.log_fix(fix, "GGA", "$GPGGA...")

        logger.update_trial_number(2)
        logger.log_fix(fix, "GGA", "$GPGGA...")

        time.sleep(0.6)
        logger.stop_recording()

        with open(path, "r") as f:
            reader = csv.reader(f)
            next(reader)  # Skip header
            row1 = next(reader)
            row2 = next(reader)

        assert int(row1[0]) == 1
        assert int(row2[0]) == 2

    def test_update_output_dir(self, tmp_path):
        """Test updating output directory."""
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"

        logger = GPSDataLogger(dir1, "GPS:serial0")
        assert logger.output_dir == dir1

        logger.update_output_dir(dir2)
        assert logger.output_dir == dir2

    def test_speed_conversion(self, tmp_path):
        """Test that speed is correctly converted to m/s."""
        logger = GPSDataLogger(tmp_path, "GPS:serial0")
        path = logger.start_recording(trial_number=1)

        # 10 knots = 5.14444 m/s (approximately)
        fix = GPSFixSnapshot(
            latitude=48.0,
            longitude=11.0,
            speed_knots=10.0,
        )
        logger.log_fix(fix, "RMC", "$GPRMC...")

        time.sleep(0.6)
        logger.stop_recording()

        with open(path, "r") as f:
            reader = csv.reader(f)
            next(reader)  # Skip header
            row = next(reader)

        speed_idx = GPS_CSV_HEADER.index("speed_mps")
        speed_mps = float(row[speed_idx])  # speed_mps column
        assert speed_mps == pytest.approx(5.14444, rel=0.01)

    def test_fix_valid_encoding(self, tmp_path):
        """Test that fix_valid is encoded as 0/1."""
        logger = GPSDataLogger(tmp_path, "GPS:serial0")
        path = logger.start_recording(trial_number=1)

        fix_valid = GPSFixSnapshot(latitude=48.0, longitude=11.0, fix_valid=True)
        fix_invalid = GPSFixSnapshot(latitude=48.0, longitude=11.0, fix_valid=False)

        logger.log_fix(fix_valid, "GGA", "$GPGGA...")
        logger.log_fix(fix_invalid, "GGA", "$GPGGA...")

        time.sleep(0.6)
        logger.stop_recording()

        with open(path, "r") as f:
            reader = csv.reader(f)
            next(reader)  # Skip header
            row1 = next(reader)
            row2 = next(reader)

        fix_valid_idx = GPS_CSV_HEADER.index("fix_valid")
        assert row1[fix_valid_idx] == "1"  # fix_valid column
        assert row2[fix_valid_idx] == "0"

    def test_dropped_records_counter(self, tmp_path):
        """Test that dropped records are tracked."""
        logger = GPSDataLogger(tmp_path, "GPS:serial0")
        assert logger.dropped_records == 0

        # Start recording to initialize the counter
        logger.start_recording()
        logger.stop_recording()

        assert logger.dropped_records == 0

    def test_flush_threshold(self, tmp_path):
        """Test custom flush threshold."""
        logger = GPSDataLogger(tmp_path, "GPS:serial0", flush_threshold=10)
        assert logger._flush_threshold == 10


class TestGPSDataLoggerEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_fix(self, tmp_path):
        """Test logging a fix with minimal data."""
        logger = GPSDataLogger(tmp_path, "GPS:serial0")
        path = logger.start_recording(trial_number=1)

        fix = GPSFixSnapshot()  # All None/default values
        result = logger.log_fix(fix, "GGA", "$GPGGA...")

        assert result is True

        time.sleep(0.6)
        logger.stop_recording()

        # Verify file was written
        assert path.exists()

    def test_special_characters_in_raw_sentence(self, tmp_path):
        """Test that special characters in raw sentence are handled."""
        logger = GPSDataLogger(tmp_path, "GPS:serial0")
        path = logger.start_recording(trial_number=1)

        fix = GPSFixSnapshot(latitude=48.0, longitude=11.0)
        raw_sentence = '$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,47.0,M,,*47\r\n"special"'
        logger.log_fix(fix, "GGA", raw_sentence)

        time.sleep(0.6)
        logger.stop_recording()

        # Should be able to read without errors
        with open(path, "r") as f:
            reader = csv.reader(f)
            list(reader)  # Should not raise

    def test_output_dir_created(self, tmp_path):
        """Test that output directory is created if it doesn't exist."""
        nested_dir = tmp_path / "a" / "b" / "c"
        logger = GPSDataLogger(nested_dir, "GPS:serial0")

        path = logger.start_recording()
        assert path is not None
        assert nested_dir.exists()

        logger.stop_recording()
