"""Unit tests for NMEA parser."""

import datetime as dt
import pytest

from rpi_logger.modules.GPS.gps_core.parsers.nmea_parser import (
    NMEAParser,
    validate_checksum,
    _parse_float,
    _parse_int,
    _parse_latlon,
    _parse_hms,
    _parse_date,
)
from rpi_logger.modules.GPS.gps_core.parsers.nmea_types import GPSFixSnapshot


class TestHelperFunctions:
    """Test helper parsing functions."""

    def test_parse_float_valid(self):
        assert _parse_float("123.456") == pytest.approx(123.456)
        assert _parse_float("0") == pytest.approx(0.0)
        assert _parse_float("-45.5") == pytest.approx(-45.5)

    def test_parse_float_invalid(self):
        assert _parse_float(None) is None
        assert _parse_float("") is None
        assert _parse_float("abc") is None

    def test_parse_int_valid(self):
        assert _parse_int("123") == 123
        assert _parse_int("0") == 0
        assert _parse_int("-5") == -5

    def test_parse_int_invalid(self):
        assert _parse_int(None) is None
        assert _parse_int("") is None
        assert _parse_int("12.5") is None
        assert _parse_int("abc") is None

    def test_parse_latlon_north_east(self):
        # 48 degrees, 7.038 minutes = 48.1173 degrees
        result = _parse_latlon("4807.038", "N", is_lat=True)
        assert result == pytest.approx(48.1173, rel=1e-4)

        # 11 degrees, 31.000 minutes = 11.5166 degrees
        result = _parse_latlon("01131.000", "E", is_lat=False)
        assert result == pytest.approx(11.5166, rel=1e-4)

    def test_parse_latlon_south_west(self):
        # Southern hemisphere should be negative
        result = _parse_latlon("3348.456", "S", is_lat=True)
        assert result is not None
        assert result < 0

        # Western hemisphere should be negative
        result = _parse_latlon("15101.123", "W", is_lat=False)
        assert result is not None
        assert result < 0

    def test_parse_latlon_invalid(self):
        assert _parse_latlon(None, "N", is_lat=True) is None
        assert _parse_latlon("4807.038", None, is_lat=True) is None
        assert _parse_latlon("", "N", is_lat=True) is None
        assert _parse_latlon("4807.038", "", is_lat=True) is None

    def test_parse_hms_valid(self):
        result = _parse_hms("123519")
        assert result is not None
        assert result.hour == 12
        assert result.minute == 35
        assert result.second == 19

    def test_parse_hms_with_fractional_seconds(self):
        result = _parse_hms("123519.500")
        assert result is not None
        assert result.hour == 12
        assert result.minute == 35
        assert result.second == 19
        assert result.microsecond == 500000

    def test_parse_hms_invalid(self):
        assert _parse_hms(None) is None
        assert _parse_hms("") is None
        assert _parse_hms("abc") is None

    def test_parse_date_valid(self):
        result = _parse_date("230394")
        assert result is not None
        assert result.day == 23
        assert result.month == 3
        assert result.year == 2094

    def test_parse_date_invalid(self):
        assert _parse_date(None) is None
        assert _parse_date("") is None
        assert _parse_date("12345") is None  # Too short
        assert _parse_date("1234567") is None  # Too long
        assert _parse_date("abcdef") is None


class TestChecksumValidation:
    """Test NMEA checksum validation."""

    def test_valid_checksum(self):
        # Real NMEA sentence with correct checksum
        sentence = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,47.0,M,,*47"
        assert validate_checksum(sentence) is True

    def test_invalid_checksum(self):
        # Same sentence with wrong checksum
        sentence = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,47.0,M,,*00"
        assert validate_checksum(sentence) is False

    def test_missing_checksum(self):
        sentence = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,47.0,M,,"
        assert validate_checksum(sentence) is False

    def test_invalid_format(self):
        assert validate_checksum("") is False
        assert validate_checksum("GPGGA,123519*47") is False  # Missing $
        assert validate_checksum("$GPGGA*XX") is False  # Invalid hex


class TestNMEAParser:
    """Test NMEA sentence parsing."""

    def test_parser_initialization(self):
        parser = NMEAParser()
        assert parser.fix is not None
        assert parser.fix.latitude is None
        assert parser.fix.longitude is None
        assert parser.last_known_date is None

    def test_parse_gprmc_valid(self):
        parser = NMEAParser(validate_checksums=False)
        sentence = "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A"
        result = parser.parse_sentence(sentence)

        assert result is not None
        assert result["fix_valid"] is True
        assert result["latitude"] == pytest.approx(48.1173, rel=1e-4)
        assert result["longitude"] == pytest.approx(11.5166, rel=1e-4)
        assert result["speed_knots"] == pytest.approx(22.4)
        assert result["course_deg"] == pytest.approx(84.4)

        # Check fix was updated
        assert parser.fix.latitude == pytest.approx(48.1173, rel=1e-4)
        assert parser.fix.fix_valid is True

    def test_parse_gpgga_valid(self):
        parser = NMEAParser(validate_checksums=False)
        sentence = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,47.0,M,,*47"
        result = parser.parse_sentence(sentence)

        assert result is not None
        assert result["fix_quality"] == 1
        assert result["satellites_in_use"] == 8
        assert result["hdop"] == pytest.approx(0.9)
        assert result["altitude_m"] == pytest.approx(545.4)
        assert result["fix_valid"] is True

    def test_parse_gpvtg_valid(self):
        parser = NMEAParser(validate_checksums=False)
        sentence = "$GPVTG,054.7,T,034.4,M,005.5,N,010.2,K*48"
        result = parser.parse_sentence(sentence)

        assert result is not None
        assert result["course_deg"] == pytest.approx(54.7)
        assert result["speed_knots"] == pytest.approx(5.5)
        assert result["speed_kmh"] == pytest.approx(10.2)

    def test_parse_gpgsa_valid(self):
        parser = NMEAParser(validate_checksums=False)
        sentence = "$GPGSA,A,3,04,05,,09,12,,,24,,,,,2.5,1.3,2.1*39"
        result = parser.parse_sentence(sentence)

        assert result is not None
        assert result["fix_mode"] == "3D"
        assert result["pdop"] == pytest.approx(2.5)
        assert result["hdop"] == pytest.approx(1.3)
        assert result["vdop"] == pytest.approx(2.1)

    def test_parse_gpgll_valid(self):
        parser = NMEAParser(validate_checksums=False)
        sentence = "$GPGLL,4807.038,N,01131.000,E,123519,A*2D"
        result = parser.parse_sentence(sentence)

        assert result is not None
        assert result["latitude"] == pytest.approx(48.1173, rel=1e-4)
        assert result["longitude"] == pytest.approx(11.5166, rel=1e-4)
        assert result["fix_valid"] is True

    def test_parse_gpgsv_valid(self):
        parser = NMEAParser(validate_checksums=False)
        sentence = "$GPGSV,3,1,11,03,03,111,00,04,15,270,00,06,01,010,00,13,06,292,00*74"
        result = parser.parse_sentence(sentence)

        assert result is not None
        assert result["satellites_in_view"] == 11

    def test_fix_state_accumulation(self):
        """Test that fix state accumulates across multiple sentences."""
        parser = NMEAParser(validate_checksums=False)

        # Parse GGA for position, altitude, satellites
        parser.parse_sentence("$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,47.0,M,,*47")

        assert parser.fix.latitude is not None
        assert parser.fix.altitude_m == pytest.approx(545.4)
        assert parser.fix.satellites_in_use == 8

        # Parse VTG for speed (should preserve other fields)
        parser.parse_sentence("$GPVTG,054.7,T,034.4,M,005.5,N,010.2,K*48")

        assert parser.fix.latitude is not None  # Still has position
        assert parser.fix.altitude_m == pytest.approx(545.4)  # Still has altitude
        assert parser.fix.speed_knots == pytest.approx(5.5)  # Now has speed
        assert parser.fix.speed_kmh == pytest.approx(10.2)

    def test_southern_hemisphere(self):
        """Test parsing coordinates in southern hemisphere."""
        parser = NMEAParser(validate_checksums=False)
        sentence = "$GPRMC,123519,A,3348.456,S,15101.123,W,0.0,0.0,010120,,,A*00"
        result = parser.parse_sentence(sentence)

        assert result is not None
        assert result["latitude"] < 0  # South
        assert result["longitude"] < 0  # West

    def test_invalid_sentence_format(self):
        parser = NMEAParser(validate_checksums=False)

        assert parser.parse_sentence("") is None
        assert parser.parse_sentence("GPGGA,123519*47") is None  # Missing $
        assert parser.parse_sentence("$INVALID*00") is None  # Unknown type

    def test_short_sentence(self):
        """Test handling of sentences with missing fields."""
        parser = NMEAParser(validate_checksums=False)

        # Too few fields for RMC
        result = parser.parse_sentence("$GPRMC,123519,A*00")
        assert result is None

    def test_callback_invocation(self):
        """Test that callback is invoked on successful parse."""
        callback_data = []

        def callback(fix, update):
            callback_data.append((fix.copy(), update.copy()))

        parser = NMEAParser(on_fix_update=callback, validate_checksums=False)
        parser.parse_sentence("$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,47.0,M,,*47")

        assert len(callback_data) == 1
        fix, update = callback_data[0]
        assert fix.latitude == pytest.approx(48.1173, rel=1e-4)
        assert update["sentence_type"] == "GGA"

    def test_checksum_validation_enabled(self):
        """Test that checksum validation works when enabled."""
        parser = NMEAParser(validate_checksums=True)

        # Valid checksum
        result = parser.parse_sentence("$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,47.0,M,,*47")
        assert result is not None

        # Invalid checksum
        result = parser.parse_sentence("$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,47.0,M,,*00")
        assert result is None

    def test_reset(self):
        """Test parser reset clears state."""
        parser = NMEAParser(validate_checksums=False)
        parser.parse_sentence("$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,47.0,M,,*47")

        assert parser.fix.latitude is not None

        parser.reset()

        assert parser.fix.latitude is None
        assert parser.last_known_date is None

    def test_speed_unit_conversions(self):
        """Test that speed is properly converted to all units."""
        parser = NMEAParser(validate_checksums=False)
        parser.parse_sentence("$GPRMC,123519,A,4807.038,N,01131.000,E,10.0,084.4,230394,003.1,W*00")

        assert parser.fix.speed_knots == pytest.approx(10.0)
        assert parser.fix.speed_kmh == pytest.approx(10.0 * 1.852)  # KMH_PER_KNOT
        assert parser.fix.speed_mph == pytest.approx(10.0 * 1.15077945)  # MPH_PER_KNOT

    def test_date_persistence(self):
        """Test that date is persisted across sentences."""
        parser = NMEAParser(validate_checksums=False)

        # RMC provides date
        parser.parse_sentence("$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,150524,003.1,W*00")
        assert parser.last_known_date is not None
        assert parser.last_known_date.day == 15
        assert parser.last_known_date.month == 5
        assert parser.last_known_date.year == 2024

        # GGA should use stored date
        parser.parse_sentence("$GPGGA,124000,4807.038,N,01131.000,E,1,08,0.9,545.4,M,47.0,M,,*47")
        assert parser.fix.timestamp is not None
        assert parser.fix.timestamp.date() == parser.last_known_date


class TestGPSFixSnapshot:
    """Test GPSFixSnapshot dataclass."""

    def test_age_seconds_no_update(self):
        fix = GPSFixSnapshot()
        assert fix.age_seconds() is None

    def test_has_position_no_fix(self):
        fix = GPSFixSnapshot()
        assert fix.has_position() is False

    def test_has_position_valid(self):
        fix = GPSFixSnapshot(
            latitude=48.1173,
            longitude=11.5166,
            fix_valid=True,
        )
        assert fix.has_position() is True

    def test_has_position_invalid_fix(self):
        fix = GPSFixSnapshot(
            latitude=48.1173,
            longitude=11.5166,
            fix_valid=False,
        )
        assert fix.has_position() is False

    def test_copy(self):
        fix = GPSFixSnapshot(
            latitude=48.1173,
            longitude=11.5166,
            altitude_m=545.4,
            fix_valid=True,
        )
        copy = fix.copy()

        assert copy.latitude == fix.latitude
        assert copy.longitude == fix.longitude
        assert copy.altitude_m == fix.altitude_m
        assert copy.fix_valid == fix.fix_valid

        # Modify original, copy should not change
        fix.latitude = 0.0
        assert copy.latitude == pytest.approx(48.1173, rel=1e-4)
