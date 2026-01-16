"""Unit tests for VOG (Video Oculography / Visual Occlusion Glasses) module.

Tests cover:
- Configuration loading for sVOG vs wVOG
- Protocol parsing (sVOG and wVOG command/response formats)
- Serial communication (mocked)
- Eye position / shutter data parsing
- CSV output format validation
- Lens switching (wVOG dual-lens support)
- Battery monitoring (wVOG)
- Error handling

All tests are isolated and use mocks - no real hardware required.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rpi_logger.modules.VOG.vog_core.protocols.base_protocol import (
    BaseVOGProtocol,
    VOGDataPacket,
    VOGResponse,
    ResponseType,
)
from rpi_logger.modules.VOG.vog_core.protocols.svog_protocol import SVOGProtocol
from rpi_logger.modules.VOG.vog_core.protocols.wvog_protocol import WVOGProtocol
from rpi_logger.modules.VOG.vog_core.device_types import VOGDeviceType

# Import mocks
from tests.infrastructure.mocks.serial_mocks import MockVOGDevice, MockSerialConfig


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def svog_protocol() -> SVOGProtocol:
    """Create an sVOG protocol instance for testing."""
    return SVOGProtocol()


@pytest.fixture
def wvog_protocol() -> WVOGProtocol:
    """Create a wVOG protocol instance for testing."""
    return WVOGProtocol()


@pytest.fixture
def mock_svog_device() -> MockVOGDevice:
    """Create a mock sVOG device for testing."""
    return MockVOGDevice(device_type="svog")


@pytest.fixture
def mock_wvog_device() -> MockVOGDevice:
    """Create a mock wVOG device for testing."""
    return MockVOGDevice(device_type="wvog")


@pytest.fixture
def sample_svog_data_packet() -> VOGDataPacket:
    """Create a sample sVOG data packet for testing."""
    return VOGDataPacket(
        device_id="SVOG_dev_ttyUSB0",
        trial_number=5,
        shutter_open=3000,
        shutter_closed=1500,
        lens="X",  # sVOG always uses X (single lens)
    )


@pytest.fixture
def sample_wvog_data_packet() -> VOGDataPacket:
    """Create a sample wVOG data packet for testing."""
    return VOGDataPacket(
        device_id="WVOG_dev_ttyACM0",
        trial_number=3,
        shutter_open=2000,
        shutter_closed=1500,
        shutter_total=3500,
        lens="A",  # wVOG supports A, B, or X
        battery_percent=85,
        device_unix_time=1733150423,
    )


# =============================================================================
# VOGDataPacket Tests
# =============================================================================


class TestVOGDataPacket:
    """Test VOGDataPacket dataclass."""

    def test_default_values(self):
        """Test that default values are set correctly for optional fields."""
        packet = VOGDataPacket(
            device_id="test",
            trial_number=1,
            shutter_open=1000,
            shutter_closed=500,
        )
        assert packet.shutter_total == 0
        assert packet.lens == "X"
        assert packet.battery_percent == 0
        assert packet.device_unix_time == 0

    def test_full_initialization(self, sample_wvog_data_packet):
        """Test full initialization with all fields."""
        packet = sample_wvog_data_packet
        assert packet.device_id == "WVOG_dev_ttyACM0"
        assert packet.trial_number == 3
        assert packet.shutter_open == 2000
        assert packet.shutter_closed == 1500
        assert packet.shutter_total == 3500
        assert packet.lens == "A"
        assert packet.battery_percent == 85
        assert packet.device_unix_time == 1733150423

    def test_to_csv_row(self, sample_svog_data_packet):
        """Test CSV row generation for legacy format."""
        packet = sample_svog_data_packet
        csv_row = packet.to_csv_row(
            label="test_label",
            unix_time=1700000000,
            ms_since_record=5000,
        )
        # Check expected format: device_id, label, unix_time, ms_since_record, trial, open, closed
        assert "SVOG_dev_ttyUSB0" in csv_row
        assert "test_label" in csv_row
        assert "1700000000" in csv_row
        assert "5000" in csv_row
        assert "5" in csv_row  # trial_number
        assert "3000" in csv_row  # shutter_open
        assert "1500" in csv_row  # shutter_closed


# =============================================================================
# SVOGProtocol Tests
# =============================================================================


class TestSVOGProtocolProperties:
    """Test sVOG protocol properties."""

    def test_device_type(self, svog_protocol):
        """Test device_type property returns 'svog'."""
        assert svog_protocol.device_type == "svog"

    def test_supports_dual_lens(self, svog_protocol):
        """Test that sVOG does not support dual lens control."""
        assert svog_protocol.supports_dual_lens is False

    def test_supports_battery(self, svog_protocol):
        """Test that sVOG does not support battery monitoring."""
        assert svog_protocol.supports_battery is False

    def test_csv_header(self, svog_protocol):
        """Test CSV header format for sVOG."""
        header = svog_protocol.csv_header
        assert "trial" in header
        assert "module" in header
        assert "device_id" in header
        assert "label" in header
        assert "record_time_unix" in header
        assert "record_time_mono" in header
        assert "shutter_open" in header
        assert "shutter_closed" in header
        # sVOG should NOT have extended fields
        assert "battery_percent" not in header
        assert "lens" not in header.split(",")[-1]  # lens should not be a separate column


class TestSVOGProtocolCommands:
    """Test sVOG command formatting."""

    def test_format_exp_start_command(self, svog_protocol):
        """Test experiment start command formatting."""
        cmd = svog_protocol.format_command("exp_start")
        assert cmd == b">do_expStart|<<\n"

    def test_format_exp_stop_command(self, svog_protocol):
        """Test experiment stop command formatting."""
        cmd = svog_protocol.format_command("exp_stop")
        assert cmd == b">do_expStop|<<\n"

    def test_format_trial_start_command(self, svog_protocol):
        """Test trial start command formatting."""
        cmd = svog_protocol.format_command("trial_start")
        assert cmd == b">do_trialStart|<<\n"

    def test_format_trial_stop_command(self, svog_protocol):
        """Test trial stop command formatting."""
        cmd = svog_protocol.format_command("trial_stop")
        assert cmd == b">do_trialStop|<<\n"

    def test_format_peek_open_command(self, svog_protocol):
        """Test peek open command formatting."""
        cmd = svog_protocol.format_command("peek_open")
        assert cmd == b">do_peekOpen|<<\n"

    def test_format_peek_close_command(self, svog_protocol):
        """Test peek close command formatting."""
        cmd = svog_protocol.format_command("peek_close")
        assert cmd == b">do_peekClose|<<\n"

    def test_format_get_config_commands(self, svog_protocol):
        """Test get configuration command formatting."""
        cmd = svog_protocol.format_command("get_device_ver")
        assert cmd == b">get_deviceVer|<<\n"

        cmd = svog_protocol.format_command("get_max_open")
        assert cmd == b">get_configMaxOpen|<<\n"

    def test_format_set_config_command_with_value(self, svog_protocol):
        """Test set configuration command with value substitution."""
        cmd = svog_protocol.format_command("set_max_open", "3000")
        assert cmd == b">set_configMaxOpen|3000<<\n"

        cmd = svog_protocol.format_command("set_debounce", "50")
        assert cmd == b">set_configDebounce|50<<\n"

    def test_format_unknown_command(self, svog_protocol):
        """Test that unknown commands return empty bytes."""
        cmd = svog_protocol.format_command("invalid_command")
        assert cmd == b""

    def test_has_command(self, svog_protocol):
        """Test command existence check."""
        assert svog_protocol.has_command("exp_start") is True
        assert svog_protocol.has_command("trial_start") is True
        assert svog_protocol.has_command("invalid") is False

    def test_get_command_keys(self, svog_protocol):
        """Test that command keys are returned."""
        keys = svog_protocol.get_command_keys()
        assert "exp_start" in keys
        assert "exp_stop" in keys
        assert "trial_start" in keys
        assert "peek_open" in keys


class TestSVOGProtocolResponseParsing:
    """Test sVOG response parsing."""

    def test_parse_experiment_start_response(self, svog_protocol):
        """Test parsing experiment start acknowledgment."""
        response = svog_protocol.parse_response("expStart")
        assert response is not None
        assert response.response_type == ResponseType.EXPERIMENT
        assert response.keyword == "expStart"

    def test_parse_experiment_stop_response(self, svog_protocol):
        """Test parsing experiment stop acknowledgment."""
        response = svog_protocol.parse_response("expStop")
        assert response is not None
        assert response.response_type == ResponseType.EXPERIMENT
        assert response.keyword == "expStop"

    def test_parse_trial_start_response(self, svog_protocol):
        """Test parsing trial start acknowledgment."""
        response = svog_protocol.parse_response("trialStart")
        assert response is not None
        assert response.response_type == ResponseType.TRIAL
        assert response.keyword == "trialStart"

    def test_parse_click_response(self, svog_protocol):
        """Test parsing click/button event."""
        response = svog_protocol.parse_response("Click")
        assert response is not None
        assert response.response_type == ResponseType.STIMULUS
        assert response.keyword == "Click"
        assert response.data.get("button_event") is True

    def test_parse_stimulus_response_open(self, svog_protocol):
        """Test parsing lens open stimulus response."""
        response = svog_protocol.parse_response("stm|1")
        assert response is not None
        assert response.response_type == ResponseType.STIMULUS
        assert response.keyword == "stm"
        assert response.value == "1"
        assert response.data.get("state") == 1

    def test_parse_stimulus_response_closed(self, svog_protocol):
        """Test parsing lens closed stimulus response."""
        response = svog_protocol.parse_response("stm|0")
        assert response is not None
        assert response.response_type == ResponseType.STIMULUS
        assert response.data.get("state") == 0

    def test_parse_button_response(self, svog_protocol):
        """Test parsing button state response."""
        response = svog_protocol.parse_response("btn|1")
        assert response is not None
        assert response.response_type == ResponseType.STIMULUS
        assert response.keyword == "btn"
        assert response.data.get("button_event") is True
        assert response.data.get("button_state") == 1

    def test_parse_config_response(self, svog_protocol):
        """Test parsing configuration response."""
        response = svog_protocol.parse_response("configMaxOpen|3000")
        assert response is not None
        assert response.response_type == ResponseType.CONFIG
        assert response.keyword == "configMaxOpen"
        assert response.value == "3000"

    def test_parse_version_response(self, svog_protocol):
        """Test parsing version response."""
        response = svog_protocol.parse_response("deviceVer|2.2")
        assert response is not None
        assert response.response_type == ResponseType.VERSION
        assert response.keyword == "deviceVer"
        assert response.value == "2.2"

    def test_parse_data_response(self, svog_protocol):
        """Test parsing data response keyword detection."""
        response = svog_protocol.parse_response("data|5,3000,1500")
        assert response is not None
        assert response.response_type == ResponseType.DATA
        assert response.keyword == "data"
        assert response.value == "5,3000,1500"

    def test_parse_empty_response(self, svog_protocol):
        """Test parsing empty response returns None."""
        assert svog_protocol.parse_response("") is None
        assert svog_protocol.parse_response("   ") is None

    def test_parse_unknown_response(self, svog_protocol):
        """Test parsing unknown response returns None."""
        assert svog_protocol.parse_response("unknown|value") is None
        assert svog_protocol.parse_response("garbage") is None


class TestSVOGDataParsing:
    """Test sVOG data response parsing."""

    def test_parse_valid_data(self, svog_protocol):
        """Test parsing valid sVOG data response."""
        packet = svog_protocol.parse_data_response("5,3000,1500", "SVOG_test")
        assert packet is not None
        assert packet.device_id == "SVOG_test"
        assert packet.trial_number == 5
        assert packet.shutter_open == 3000
        assert packet.shutter_closed == 1500
        assert packet.lens == "X"  # sVOG always X

    def test_parse_data_with_whitespace(self, svog_protocol):
        """Test parsing data with whitespace."""
        packet = svog_protocol.parse_data_response(" 3 , 2000 , 1000 ", "SVOG_test")
        assert packet is not None
        assert packet.trial_number == 3
        assert packet.shutter_open == 2000
        assert packet.shutter_closed == 1000

    def test_parse_data_with_empty_fields(self, svog_protocol):
        """Test parsing data with empty fields defaults to 0."""
        packet = svog_protocol.parse_data_response(",2000,1000", "SVOG_test")
        assert packet is not None
        assert packet.trial_number == 0
        assert packet.shutter_open == 2000

    def test_parse_insufficient_fields(self, svog_protocol):
        """Test parsing data with too few fields returns None."""
        packet = svog_protocol.parse_data_response("5,3000", "SVOG_test")
        assert packet is None

    def test_parse_invalid_data(self, svog_protocol):
        """Test parsing invalid data returns None."""
        packet = svog_protocol.parse_data_response("invalid,data,here", "SVOG_test")
        assert packet is None


class TestSVOGPolymorphicMethods:
    """Test sVOG protocol polymorphic methods."""

    def test_get_config_commands(self, svog_protocol):
        """Test that config commands list is returned for sVOG."""
        commands = svog_protocol.get_config_commands()
        assert isinstance(commands, list)
        assert len(commands) > 0
        assert "get_device_ver" in commands
        assert "get_max_open" in commands

    def test_format_set_config(self, svog_protocol):
        """Test formatting set config operations for sVOG."""
        cmd, val = svog_protocol.format_set_config("max_open", "3000")
        assert cmd == "set_max_open"
        assert val == "3000"

    def test_format_set_config_unknown_param(self, svog_protocol):
        """Test formatting unknown config parameter returns None."""
        cmd, val = svog_protocol.format_set_config("unknown_param", "value")
        assert cmd is None
        assert val is None

    def test_update_config_from_response(self, svog_protocol):
        """Test updating config dict from sVOG response."""
        response = VOGResponse(
            response_type=ResponseType.CONFIG,
            keyword="configMaxOpen",
            value="3000",
            raw="configMaxOpen|3000",
        )
        config = {}
        svog_protocol.update_config_from_response(response, config)
        assert config["configMaxOpen"] == "3000"

    def test_get_extended_packet_data(self, svog_protocol, sample_svog_data_packet):
        """Test that sVOG returns empty extended data."""
        extended = svog_protocol.get_extended_packet_data(sample_svog_data_packet)
        assert extended == {}

    def test_format_csv_row(self, svog_protocol, sample_svog_data_packet):
        """Test CSV row formatting for sVOG returns list for csv.writer."""
        row = svog_protocol.format_csv_row(
            sample_svog_data_packet,
            label="test_label",
            record_time_unix=1700000000.123456,
            record_time_mono=12345.123456789,
        )
        # format_csv_row now returns a list for csv.writer
        assert isinstance(row, list)
        assert row[0] == 5  # trial_number
        assert row[1] == "VOG"  # module
        assert "SVOG_dev_ttyUSB0" in row[2]  # device_id
        assert row[3] == "test_label"  # label
        assert "1700000000" in row[4]  # record_time_unix
        assert row[6] == 3000  # shutter_open
        assert row[7] == 1500  # shutter_closed


# =============================================================================
# WVOGProtocol Tests
# =============================================================================


class TestWVOGProtocolProperties:
    """Test wVOG protocol properties."""

    def test_device_type(self, wvog_protocol):
        """Test device_type property returns 'wvog'."""
        assert wvog_protocol.device_type == "wvog"

    def test_supports_dual_lens(self, wvog_protocol):
        """Test that wVOG supports dual lens control."""
        assert wvog_protocol.supports_dual_lens is True

    def test_supports_battery(self, wvog_protocol):
        """Test that wVOG supports battery monitoring."""
        assert wvog_protocol.supports_battery is True

    def test_csv_header(self, wvog_protocol):
        """Test CSV header format for wVOG includes extended fields."""
        header = wvog_protocol.csv_header
        assert "trial" in header
        assert "module" in header
        assert "device_id" in header
        assert "shutter_open" in header
        assert "shutter_closed" in header
        # wVOG should have extended fields
        assert "shutter_total" in header
        assert "lens" in header
        assert "battery_percent" in header


class TestWVOGProtocolCommands:
    """Test wVOG command formatting."""

    def test_format_exp_start_command(self, wvog_protocol):
        """Test experiment start command formatting."""
        cmd = wvog_protocol.format_command("exp_start")
        assert cmd == b"exp>1\n"

    def test_format_exp_stop_command(self, wvog_protocol):
        """Test experiment stop command formatting."""
        cmd = wvog_protocol.format_command("exp_stop")
        assert cmd == b"exp>0\n"

    def test_format_trial_start_command(self, wvog_protocol):
        """Test trial start command formatting."""
        cmd = wvog_protocol.format_command("trial_start")
        assert cmd == b"trl>1\n"

    def test_format_trial_stop_command(self, wvog_protocol):
        """Test trial stop command formatting."""
        cmd = wvog_protocol.format_command("trial_stop")
        assert cmd == b"trl>0\n"

    def test_format_lens_open_a_command(self, wvog_protocol):
        """Test lens A open command (left eye)."""
        cmd = wvog_protocol.format_command("lens_open_a")
        assert cmd == b"a>1\n"

    def test_format_lens_close_a_command(self, wvog_protocol):
        """Test lens A close command (left eye)."""
        cmd = wvog_protocol.format_command("lens_close_a")
        assert cmd == b"a>0\n"

    def test_format_lens_open_b_command(self, wvog_protocol):
        """Test lens B open command (right eye)."""
        cmd = wvog_protocol.format_command("lens_open_b")
        assert cmd == b"b>1\n"

    def test_format_lens_close_b_command(self, wvog_protocol):
        """Test lens B close command (right eye)."""
        cmd = wvog_protocol.format_command("lens_close_b")
        assert cmd == b"b>0\n"

    def test_format_lens_open_x_command(self, wvog_protocol):
        """Test lens X open command (both eyes)."""
        cmd = wvog_protocol.format_command("lens_open_x")
        assert cmd == b"x>1\n"

    def test_format_lens_close_x_command(self, wvog_protocol):
        """Test lens X close command (both eyes)."""
        cmd = wvog_protocol.format_command("lens_close_x")
        assert cmd == b"x>0\n"

    def test_format_get_config_command(self, wvog_protocol):
        """Test get configuration command."""
        cmd = wvog_protocol.format_command("get_config")
        assert cmd == b"cfg\n"

    def test_format_get_battery_command(self, wvog_protocol):
        """Test get battery command."""
        cmd = wvog_protocol.format_command("get_battery")
        assert cmd == b"bat\n"

    def test_format_get_rtc_command(self, wvog_protocol):
        """Test get RTC command."""
        cmd = wvog_protocol.format_command("get_rtc")
        assert cmd == b"rtc\n"

    def test_format_set_rtc_command(self, wvog_protocol):
        """Test set RTC command with value."""
        cmd = wvog_protocol.format_command("set_rtc", "2025,12,2,1,14,30,0,0")
        assert cmd == b"rtc>2025,12,2,1,14,30,0,0\n"

    def test_format_unknown_command(self, wvog_protocol):
        """Test that unknown commands return empty bytes."""
        cmd = wvog_protocol.format_command("invalid_command")
        assert cmd == b""


class TestWVOGProtocolResponseParsing:
    """Test wVOG response parsing."""

    def test_parse_exp_response_start(self, wvog_protocol):
        """Test parsing experiment start response."""
        response = wvog_protocol.parse_response("exp>1")
        assert response is not None
        assert response.response_type == ResponseType.EXPERIMENT
        assert response.keyword == "exp"
        assert response.value == "1"

    def test_parse_exp_response_stop(self, wvog_protocol):
        """Test parsing experiment stop response."""
        response = wvog_protocol.parse_response("exp>0")
        assert response is not None
        assert response.response_type == ResponseType.EXPERIMENT
        assert response.value == "0"

    def test_parse_trial_response_start(self, wvog_protocol):
        """Test parsing trial start response."""
        response = wvog_protocol.parse_response("trl>1")
        assert response is not None
        assert response.response_type == ResponseType.TRIAL
        assert response.value == "1"

    def test_parse_stimulus_response_lens_a(self, wvog_protocol):
        """Test parsing lens A stimulus response."""
        response = wvog_protocol.parse_response("a>1")
        assert response is not None
        assert response.response_type == ResponseType.STIMULUS
        assert response.keyword == "a"
        assert response.data.get("state") == 1
        assert response.data.get("lens") == "A"

    def test_parse_stimulus_response_lens_b(self, wvog_protocol):
        """Test parsing lens B stimulus response."""
        response = wvog_protocol.parse_response("b>0")
        assert response is not None
        assert response.response_type == ResponseType.STIMULUS
        assert response.data.get("state") == 0
        assert response.data.get("lens") == "B"

    def test_parse_stimulus_response_lens_x(self, wvog_protocol):
        """Test parsing lens X (both) stimulus response."""
        response = wvog_protocol.parse_response("x>1")
        assert response is not None
        assert response.response_type == ResponseType.STIMULUS
        assert response.data.get("lens") == "X"

    def test_parse_battery_response(self, wvog_protocol):
        """Test parsing battery status response."""
        response = wvog_protocol.parse_response("bty>85")
        assert response is not None
        assert response.response_type == ResponseType.BATTERY
        assert response.keyword == "bty"
        assert response.data.get("percent") == 85

    def test_parse_battery_response_low(self, wvog_protocol):
        """Test parsing low battery status."""
        response = wvog_protocol.parse_response("bty>15")
        assert response is not None
        assert response.data.get("percent") == 15

    def test_parse_config_response(self, wvog_protocol):
        """Test parsing configuration response."""
        config_str = "cfg>clr:100,cls:1500,dbc:20,srt:1,opn:1500,dta:0,drk:0,typ:cycle"
        response = wvog_protocol.parse_response(config_str)
        assert response is not None
        assert response.response_type == ResponseType.CONFIG
        assert response.keyword == "cfg"

        config = response.data.get("config", {})
        assert config.get("clr") == "100"
        assert config.get("clear_opacity") == "100"
        assert config.get("cls") == "1500"
        assert config.get("close_time") == "1500"
        assert config.get("dbc") == "20"
        assert config.get("debounce") == "20"
        assert config.get("typ") == "cycle"
        assert config.get("experiment_type") == "cycle"

    def test_parse_rtc_response(self, wvog_protocol):
        """Test parsing RTC response."""
        response = wvog_protocol.parse_response("rtc>2025,12,2,1,14,30,0,0")
        assert response is not None
        assert response.response_type == ResponseType.RTC

        rtc = response.data.get("rtc", {})
        assert rtc.get("year") == 2025
        assert rtc.get("month") == 12
        assert rtc.get("day") == 2
        assert rtc.get("hour") == 14
        assert rtc.get("minute") == 30
        assert rtc.get("second") == 0

    def test_parse_data_response(self, wvog_protocol):
        """Test parsing data response keyword detection."""
        response = wvog_protocol.parse_response("dta>1,2000,1500,3500,X,85,1733150423")
        assert response is not None
        assert response.response_type == ResponseType.DATA
        assert response.keyword == "dta"

    def test_parse_empty_response(self, wvog_protocol):
        """Test parsing empty response returns None."""
        assert wvog_protocol.parse_response("") is None
        assert wvog_protocol.parse_response("   ") is None

    def test_parse_unknown_response(self, wvog_protocol):
        """Test parsing unknown response returns None."""
        assert wvog_protocol.parse_response("unknown>value") is None


class TestWVOGDataParsing:
    """Test wVOG data response parsing."""

    def test_parse_valid_full_data(self, wvog_protocol):
        """Test parsing valid wVOG data response with all fields."""
        packet = wvog_protocol.parse_data_response(
            "3,2000,1500,3500,A,85,1733150423",
            "WVOG_test"
        )
        assert packet is not None
        assert packet.device_id == "WVOG_test"
        assert packet.trial_number == 3
        assert packet.shutter_open == 2000
        assert packet.shutter_closed == 1500
        assert packet.shutter_total == 3500
        assert packet.lens == "A"
        assert packet.battery_percent == 85
        assert packet.device_unix_time == 1733150423

    def test_parse_data_lens_b(self, wvog_protocol):
        """Test parsing data with lens B."""
        packet = wvog_protocol.parse_data_response(
            "1,1000,1000,2000,B,90,1733150000",
            "WVOG_test"
        )
        assert packet is not None
        assert packet.lens == "B"

    def test_parse_data_lens_x(self, wvog_protocol):
        """Test parsing data with lens X (both)."""
        packet = wvog_protocol.parse_data_response(
            "2,1500,1500,3000,X,75,1733150000",
            "WVOG_test"
        )
        assert packet is not None
        assert packet.lens == "X"

    def test_parse_minimal_data(self, wvog_protocol):
        """Test parsing minimal data format (3 fields)."""
        packet = wvog_protocol.parse_data_response(
            "5,3000,1500",
            "WVOG_test"
        )
        assert packet is not None
        assert packet.trial_number == 5
        assert packet.shutter_open == 3000
        assert packet.shutter_closed == 1500
        # Defaults for missing fields
        assert packet.shutter_total == 0
        assert packet.lens == "X"
        assert packet.battery_percent == 0

    def test_parse_data_with_empty_fields(self, wvog_protocol):
        """Test parsing data with empty fields defaults to 0/X."""
        packet = wvog_protocol.parse_data_response(
            ",,1000,2000,,50,",
            "WVOG_test"
        )
        assert packet is not None
        assert packet.trial_number == 0
        assert packet.shutter_open == 0
        assert packet.shutter_closed == 1000
        assert packet.lens == "X"  # Empty becomes X

    def test_parse_insufficient_fields(self, wvog_protocol):
        """Test parsing data with too few fields returns None."""
        packet = wvog_protocol.parse_data_response("5,3000", "WVOG_test")
        assert packet is None

    def test_parse_invalid_data(self, wvog_protocol):
        """Test parsing invalid data returns None."""
        packet = wvog_protocol.parse_data_response("abc,def,ghi", "WVOG_test")
        assert packet is None


class TestWVOGPolymorphicMethods:
    """Test wVOG protocol polymorphic methods."""

    def test_get_config_commands(self, wvog_protocol):
        """Test that config commands list returns single command for wVOG."""
        commands = wvog_protocol.get_config_commands()
        assert isinstance(commands, list)
        assert len(commands) == 1
        assert commands[0] == "get_config"

    def test_format_set_config(self, wvog_protocol):
        """Test formatting set config operations for wVOG."""
        cmd, val = wvog_protocol.format_set_config("clr", "100")
        assert cmd == "set_config"
        assert val == "clr,100"

    def test_update_config_from_response(self, wvog_protocol):
        """Test updating config dict from wVOG response."""
        response = VOGResponse(
            response_type=ResponseType.CONFIG,
            keyword="cfg",
            value="clr:100,cls:1500",
            raw="cfg>clr:100,cls:1500",
            data={"config": {"clr": "100", "clear_opacity": "100", "cls": "1500", "close_time": "1500"}},
        )
        config = {}
        wvog_protocol.update_config_from_response(response, config)
        assert config["clr"] == "100"
        assert config["cls"] == "1500"

    def test_get_extended_packet_data(self, wvog_protocol, sample_wvog_data_packet):
        """Test that wVOG returns extended data fields."""
        extended = wvog_protocol.get_extended_packet_data(sample_wvog_data_packet)
        assert extended["shutter_total"] == 3500
        assert extended["lens"] == "A"
        assert extended["battery_percent"] == 85
        assert extended["device_unix_time"] == 1733150423

    def test_format_csv_row(self, wvog_protocol, sample_wvog_data_packet):
        """Test CSV row formatting for wVOG returns list with extended fields."""
        row = wvog_protocol.format_csv_row(
            sample_wvog_data_packet,
            label="test_label",
            record_time_unix=1700000000.123456,
            record_time_mono=12345.123456789,
        )
        # format_csv_row now returns a list for csv.writer
        assert isinstance(row, list)
        assert row[0] == 3  # trial_number
        assert row[1] == "VOG"  # module
        assert "WVOG_dev_ttyACM0" in row[2]  # device_id
        assert row[3] == "test_label"  # label
        assert row[6] == 2000  # shutter_open
        assert row[7] == 1500  # shutter_closed
        assert row[8] == 3500  # shutter_total
        assert row[9] == "A"  # lens
        assert row[10] == 85  # battery_percent


# =============================================================================
# Lens Switching Tests (wVOG)
# =============================================================================


class TestWVOGLensSwitching:
    """Test wVOG dual lens control functionality."""

    def test_all_lens_commands_exist(self, wvog_protocol):
        """Test that all lens control commands exist."""
        commands = wvog_protocol.get_command_keys()
        # Open commands
        assert "lens_open_a" in commands
        assert "lens_open_b" in commands
        assert "lens_open_x" in commands
        # Close commands
        assert "lens_close_a" in commands
        assert "lens_close_b" in commands
        assert "lens_close_x" in commands

    def test_lens_response_parsing_tracks_which_lens(self, wvog_protocol):
        """Test that lens responses track which lens was affected."""
        response_a = wvog_protocol.parse_response("a>1")
        response_b = wvog_protocol.parse_response("b>1")
        response_x = wvog_protocol.parse_response("x>1")

        assert response_a.data.get("lens") == "A"
        assert response_b.data.get("lens") == "B"
        assert response_x.data.get("lens") == "X"

    def test_data_packet_lens_field_variations(self, wvog_protocol):
        """Test that data packets correctly parse different lens values."""
        packet_a = wvog_protocol.parse_data_response("1,1000,1000,2000,A,80,0", "test")
        packet_b = wvog_protocol.parse_data_response("1,1000,1000,2000,B,80,0", "test")
        packet_x = wvog_protocol.parse_data_response("1,1000,1000,2000,X,80,0", "test")

        assert packet_a.lens == "A"
        assert packet_b.lens == "B"
        assert packet_x.lens == "X"


# =============================================================================
# Battery Monitoring Tests (wVOG)
# =============================================================================


class TestWVOGBatteryMonitoring:
    """Test wVOG battery monitoring functionality."""

    def test_battery_response_parsing_full_charge(self, wvog_protocol):
        """Test parsing battery at full charge."""
        response = wvog_protocol.parse_response("bty>100")
        assert response is not None
        assert response.data.get("percent") == 100

    def test_battery_response_parsing_low_battery(self, wvog_protocol):
        """Test parsing low battery status."""
        response = wvog_protocol.parse_response("bty>10")
        assert response is not None
        assert response.data.get("percent") == 10

    def test_battery_response_parsing_critical(self, wvog_protocol):
        """Test parsing critical battery status."""
        response = wvog_protocol.parse_response("bty>5")
        assert response is not None
        assert response.data.get("percent") == 5

    def test_battery_response_parsing_invalid(self, wvog_protocol):
        """Test parsing invalid battery response."""
        response = wvog_protocol.parse_response("bty>invalid")
        assert response is not None
        assert response.data.get("percent") == 0  # Defaults to 0 on parse error

    def test_battery_in_data_packet(self, wvog_protocol):
        """Test that battery percentage is included in data packets."""
        packet = wvog_protocol.parse_data_response("1,1000,1000,2000,X,75,1733150000", "test")
        assert packet is not None
        assert packet.battery_percent == 75

    def test_get_battery_command_exists(self, wvog_protocol):
        """Test that get_battery command is available."""
        assert wvog_protocol.has_command("get_battery")
        cmd = wvog_protocol.format_command("get_battery")
        assert cmd == b"bat\n"


# =============================================================================
# Mock Device Tests
# =============================================================================


class TestMockVOGDevice:
    """Test mock VOG device functionality."""

    def test_mock_svog_device_creation(self, mock_svog_device):
        """Test mock sVOG device is created with correct settings."""
        assert mock_svog_device.device_type == "svog"
        assert mock_svog_device.config.baudrate == 115200

    def test_mock_wvog_device_creation(self, mock_wvog_device):
        """Test mock wVOG device is created with correct settings."""
        assert mock_wvog_device.device_type == "wvog"
        assert mock_wvog_device.config.baudrate == 57600

    def test_mock_device_open_close(self, mock_svog_device):
        """Test mock device open/close operations."""
        mock_svog_device.open()
        assert mock_svog_device.is_open is True

        mock_svog_device.close()
        assert mock_svog_device.is_open is False

    def test_mock_device_write_logging(self, mock_svog_device):
        """Test that mock device logs written data."""
        mock_svog_device.open()
        mock_svog_device.write(b">do_expStart|<<\n")

        write_log = mock_svog_device.get_write_log()
        assert len(write_log) == 1
        assert write_log[0] == b">do_expStart|<<\n"

    def test_mock_svog_simulate_shutter_event(self, mock_svog_device):
        """Test simulating sVOG shutter event."""
        mock_svog_device.open()
        response = mock_svog_device.simulate_shutter_event(
            open_ms=2000,
            closed_ms=1000,
        )
        # sVOG format: data|trial,open,closed
        assert b"data|" in response
        assert b"2000" in response
        assert b"1000" in response

    def test_mock_wvog_simulate_shutter_event(self, mock_wvog_device):
        """Test simulating wVOG shutter event."""
        mock_wvog_device.open()
        response = mock_wvog_device.simulate_shutter_event(
            open_ms=1500,
            closed_ms=1500,
            lens="A",
            battery_percent=85,
        )
        # wVOG format: dta>trial,open,closed,total,lens,battery,unix
        assert b"dta>" in response
        assert b"1500" in response
        assert b"A" in response
        assert b"85" in response


# =============================================================================
# Device Type Tests
# =============================================================================


class TestVOGDeviceType:
    """Test VOGDeviceType enum."""

    def test_svog_type(self):
        """Test sVOG device type."""
        assert VOGDeviceType.SVOG.value == "sVOG"

    def test_wvog_usb_type(self):
        """Test wVOG USB device type."""
        assert VOGDeviceType.WVOG_USB.value == "wVOG_USB"

    def test_wvog_wireless_type(self):
        """Test wVOG wireless device type."""
        assert VOGDeviceType.WVOG_WIRELESS.value == "wVOG_Wireless"


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestProtocolErrorHandling:
    """Test protocol error handling."""

    def test_svog_unknown_command_returns_empty(self, svog_protocol):
        """Test that sVOG returns empty bytes for unknown commands."""
        cmd = svog_protocol.format_command("nonexistent_command")
        assert cmd == b""

    def test_wvog_unknown_command_returns_empty(self, wvog_protocol):
        """Test that wVOG returns empty bytes for unknown commands."""
        cmd = wvog_protocol.format_command("nonexistent_command")
        assert cmd == b""

    def test_svog_malformed_response_returns_none(self, svog_protocol):
        """Test that sVOG returns None for malformed responses."""
        assert svog_protocol.parse_response("malformed") is None
        assert svog_protocol.parse_response("no_pipe_char") is None
        assert svog_protocol.parse_response("") is None

    def test_wvog_malformed_response_returns_none(self, wvog_protocol):
        """Test that wVOG returns None for malformed responses."""
        assert wvog_protocol.parse_response("malformed") is None
        assert wvog_protocol.parse_response("") is None

    def test_svog_corrupt_data_parsing(self, svog_protocol):
        """Test parsing corrupt data values."""
        # Non-numeric values
        result = svog_protocol.parse_data_response("abc,def,ghi", "test")
        assert result is None

    def test_wvog_corrupt_data_parsing(self, wvog_protocol):
        """Test parsing corrupt wVOG data values."""
        # Non-numeric values
        result = wvog_protocol.parse_data_response("abc,def,ghi,jkl,X,80,0", "test")
        assert result is None

    def test_svog_partial_data_parsing(self, svog_protocol):
        """Test parsing partial/incomplete sVOG data."""
        # Only 2 fields instead of 3
        result = svog_protocol.parse_data_response("5,3000", "test")
        assert result is None

    def test_wvog_partial_data_parsing(self, wvog_protocol):
        """Test parsing partial/incomplete wVOG data."""
        # Only 2 fields instead of minimum 3
        result = wvog_protocol.parse_data_response("5,3000", "test")
        assert result is None


# =============================================================================
# RTC Tests (wVOG)
# =============================================================================


class TestWVOGRTC:
    """Test wVOG RTC (Real-Time Clock) functionality."""

    def test_parse_rtc_full_response(self, wvog_protocol):
        """Test parsing complete RTC response."""
        response = wvog_protocol.parse_response("rtc>2025,12,25,4,10,30,45,123")
        assert response is not None

        rtc = response.data.get("rtc", {})
        assert rtc["year"] == 2025
        assert rtc["month"] == 12
        assert rtc["day"] == 25
        assert rtc["dow"] == 4  # Day of week
        assert rtc["hour"] == 10
        assert rtc["minute"] == 30
        assert rtc["second"] == 45
        assert rtc["subsecond"] == 123

    def test_parse_rtc_partial_response(self, wvog_protocol):
        """Test parsing partial RTC response."""
        response = wvog_protocol.parse_response("rtc>2025,6,15")
        assert response is not None

        rtc = response.data.get("rtc", {})
        assert rtc["year"] == 2025
        assert rtc["month"] == 6
        assert rtc["day"] == 15
        # Missing fields should not be present or be 0
        assert rtc.get("hour", 0) == 0

    def test_parse_rtc_empty_response(self, wvog_protocol):
        """Test parsing empty RTC response."""
        response = wvog_protocol.parse_response("rtc>")
        assert response is not None
        rtc = response.data.get("rtc", {})
        assert rtc == {}


# =============================================================================
# Configuration Parsing Tests
# =============================================================================


class TestWVOGConfigParsing:
    """Test wVOG configuration string parsing."""

    def test_parse_full_config_string(self, wvog_protocol):
        """Test parsing complete configuration string."""
        config_str = "cfg>clr:100,cls:1500,dbc:20,srt:1,opn:1500,dta:0,drk:0,typ:cycle"
        response = wvog_protocol.parse_response(config_str)

        config = response.data.get("config", {})

        # Check both short and long keys
        assert config["clr"] == "100"
        assert config["clear_opacity"] == "100"

        assert config["cls"] == "1500"
        assert config["close_time"] == "1500"

        assert config["dbc"] == "20"
        assert config["debounce"] == "20"

        assert config["srt"] == "1"
        assert config["start_state"] == "1"

        assert config["opn"] == "1500"
        assert config["open_time"] == "1500"

        assert config["drk"] == "0"
        assert config["dark_opacity"] == "0"

        assert config["typ"] == "cycle"
        assert config["experiment_type"] == "cycle"

    def test_parse_partial_config_string(self, wvog_protocol):
        """Test parsing partial configuration string."""
        config_str = "cfg>clr:75,typ:peek"
        response = wvog_protocol.parse_response(config_str)

        config = response.data.get("config", {})
        assert config["clr"] == "75"
        assert config["typ"] == "peek"

    def test_parse_empty_config_string(self, wvog_protocol):
        """Test parsing empty configuration string."""
        response = wvog_protocol.parse_response("cfg>")
        config = response.data.get("config", {})
        assert config == {}


# =============================================================================
# CSV Format Validation Tests
# =============================================================================


class TestCSVFormatValidation:
    """Test CSV format validation for both sVOG and wVOG."""

    def test_svog_csv_header_column_count(self, svog_protocol):
        """Test sVOG CSV header has correct number of columns."""
        header = svog_protocol.csv_header
        columns = header.split(",")
        assert len(columns) == 8  # trial,module,device_id,label,unix,mono,open,closed

    def test_wvog_csv_header_column_count(self, wvog_protocol):
        """Test wVOG CSV header has correct number of columns."""
        header = wvog_protocol.csv_header
        columns = header.split(",")
        assert len(columns) == 11  # +shutter_total,lens,battery_percent

    def test_svog_csv_row_matches_header(self, svog_protocol, sample_svog_data_packet):
        """Test that sVOG CSV row has same column count as header."""
        header = svog_protocol.csv_header
        row = svog_protocol.format_csv_row(
            sample_svog_data_packet,
            label="test",
            record_time_unix=1700000000.0,
            record_time_mono=12345.0,
        )

        header_cols = len(header.split(","))
        # format_csv_row now returns a list
        row_cols = len(row)
        assert header_cols == row_cols

    def test_wvog_csv_row_matches_header(self, wvog_protocol, sample_wvog_data_packet):
        """Test that wVOG CSV row has same column count as header."""
        header = wvog_protocol.csv_header
        row = wvog_protocol.format_csv_row(
            sample_wvog_data_packet,
            label="test",
            record_time_unix=1700000000.0,
            record_time_mono=12345.0,
        )

        header_cols = len(header.split(","))
        # format_csv_row now returns a list
        row_cols = len(row)
        assert header_cols == row_cols

    def test_svog_csv_row_preserves_precision(self, svog_protocol, sample_svog_data_packet):
        """Test that timestamps preserve required precision."""
        row = svog_protocol.format_csv_row(
            sample_svog_data_packet,
            label="test",
            record_time_unix=1700000000.123456,
            record_time_mono=12345.123456789,
        )

        # Row is now a list, check string elements for precision
        # Unix time should have at least 6 decimal places (index 4)
        assert "1700000000.123456" in row[4]
        # Mono time should have 9 decimal places (index 5)
        assert "12345.123456789" in row[5]

    def test_wvog_csv_row_preserves_precision(self, wvog_protocol, sample_wvog_data_packet):
        """Test that wVOG timestamps preserve required precision."""
        row = wvog_protocol.format_csv_row(
            sample_wvog_data_packet,
            label="test",
            record_time_unix=1700000000.123456,
            record_time_mono=12345.123456789,
        )

        # Row is now a list, check string elements for precision
        assert "1700000000.123456" in row[4]
        assert "12345.123456789" in row[5]


# =============================================================================
# Integration-style Protocol Tests
# =============================================================================


class TestProtocolRoundTrip:
    """Test round-trip command/response scenarios."""

    def test_svog_experiment_flow(self, svog_protocol):
        """Test sVOG experiment start/stop command and response cycle."""
        # Format commands
        start_cmd = svog_protocol.format_command("exp_start")
        assert start_cmd == b">do_expStart|<<\n"

        # Parse expected response
        response = svog_protocol.parse_response("expStart")
        assert response.response_type == ResponseType.EXPERIMENT

        stop_cmd = svog_protocol.format_command("exp_stop")
        assert stop_cmd == b">do_expStop|<<\n"

        response = svog_protocol.parse_response("expStop")
        assert response.response_type == ResponseType.EXPERIMENT

    def test_wvog_experiment_flow(self, wvog_protocol):
        """Test wVOG experiment start/stop command and response cycle."""
        # Format commands
        start_cmd = wvog_protocol.format_command("exp_start")
        assert start_cmd == b"exp>1\n"

        # Parse expected response
        response = wvog_protocol.parse_response("exp>1")
        assert response.response_type == ResponseType.EXPERIMENT

        stop_cmd = wvog_protocol.format_command("exp_stop")
        assert stop_cmd == b"exp>0\n"

        response = wvog_protocol.parse_response("exp>0")
        assert response.response_type == ResponseType.EXPERIMENT

    def test_svog_data_capture_flow(self, svog_protocol):
        """Test sVOG data capture and parsing flow."""
        # Simulate receiving data after trial
        response = svog_protocol.parse_response("data|5,3000,1500")
        assert response.response_type == ResponseType.DATA

        packet = svog_protocol.parse_data_response(response.value, "SVOG_test")
        assert packet.trial_number == 5
        assert packet.shutter_open == 3000
        assert packet.shutter_closed == 1500

    def test_wvog_data_capture_flow(self, wvog_protocol):
        """Test wVOG data capture and parsing flow."""
        # Simulate receiving data after trial
        response = wvog_protocol.parse_response("dta>3,2000,1500,3500,A,85,1733150423")
        assert response.response_type == ResponseType.DATA

        packet = wvog_protocol.parse_data_response(response.value, "WVOG_test")
        assert packet.trial_number == 3
        assert packet.shutter_open == 2000
        assert packet.shutter_closed == 1500
        assert packet.shutter_total == 3500
        assert packet.lens == "A"
        assert packet.battery_percent == 85
