"""Unit tests for DRT (Detection Response Task) module.

This module tests:
- DRTConfig configuration loading and defaults
- Protocol constants for sDRT and wDRT
- Serial transport communication (mocked)
- Handler response processing for sDRT and wDRT
- Data logging and CSV output format validation
- Stimulus timing and reaction time calculation
- Battery monitoring (wDRT only)
- Error handling and edge cases

All tests are fully isolated with no hardware dependencies.
"""

from __future__ import annotations

import asyncio
import csv
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# =============================================================================
# Async Test Helper
# =============================================================================

def run_async(coro):
    """Run async coroutine synchronously for testing."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# =============================================================================
# Configuration Tests
# =============================================================================

class TestDRTConfig:
    """Tests for DRTConfig typed configuration class."""

    def test_default_values(self):
        """Test DRTConfig default values are correctly set."""
        from rpi_logger.modules.DRT.config import DRTConfig

        config = DRTConfig()

        assert config.display_name == "DRT"
        assert config.enabled is False
        assert config.output_dir == Path("drt_data")
        assert config.session_prefix == "drt"
        assert config.log_level == "info"
        assert config.console_output is False
        assert config.device_vid == 0x239A
        assert config.device_pid == 0x801E
        assert config.baudrate == 9600
        assert config.auto_start_recording is False
        assert config.gui_show_session_output is True

    def test_window_defaults(self):
        """Test window position/size defaults."""
        from rpi_logger.modules.DRT.config import DRTConfig

        config = DRTConfig()

        assert config.window_x == 0
        assert config.window_y == 0
        assert config.window_width == 800
        assert config.window_height == 600
        assert config.window_geometry == ""

    def test_to_dict_returns_all_fields(self):
        """Test that to_dict exports all configuration fields."""
        from rpi_logger.modules.DRT.config import DRTConfig

        config = DRTConfig()
        config_dict = config.to_dict()

        assert isinstance(config_dict, dict)
        assert "display_name" in config_dict
        assert "enabled" in config_dict
        assert "output_dir" in config_dict
        assert "device_vid" in config_dict
        assert "device_pid" in config_dict
        assert "baudrate" in config_dict
        assert "window_x" in config_dict

    def test_from_preferences_with_none_returns_defaults(self):
        """Test that from_preferences with None prefs returns defaults."""
        from rpi_logger.modules.DRT.config import DRTConfig

        # Mock preferences that return None for all values
        mock_prefs = MagicMock()
        mock_prefs.get.return_value = None

        config = DRTConfig.from_preferences(mock_prefs)

        assert config.display_name == "DRT"
        assert config.baudrate == 9600

    def test_apply_args_override(self):
        """Test that CLI arguments override config values."""
        from rpi_logger.modules.DRT.config import DRTConfig

        config = DRTConfig()

        # Create mock args object
        mock_args = MagicMock()
        mock_args.output_dir = Path("/tmp/custom_output")
        mock_args.session_prefix = "custom_prefix"
        mock_args.log_level = "debug"
        mock_args.baudrate = 115200

        result = config._apply_args_override(mock_args)

        assert result.output_dir == Path("/tmp/custom_output")
        assert result.session_prefix == "custom_prefix"
        assert result.log_level == "debug"
        assert result.baudrate == 115200

    def test_apply_args_override_ignores_none_values(self):
        """Test that None args values don't override config."""
        from rpi_logger.modules.DRT.config import DRTConfig

        config = DRTConfig(baudrate=9600)

        mock_args = MagicMock()
        mock_args.baudrate = None

        result = config._apply_args_override(mock_args)

        assert result.baudrate == 9600  # Original value preserved


class TestConfigLoader:
    """Tests for the DRTConfig dataclass defaults."""

    def test_defaults_structure(self):
        """Test that DRTConfig has expected default attributes."""
        from rpi_logger.modules.DRT.config import DRTConfig

        config = DRTConfig()
        assert hasattr(config, "enabled")
        assert hasattr(config, "device_vid")
        assert hasattr(config, "device_pid")
        assert hasattr(config, "baudrate")
        assert hasattr(config, "output_dir")

    def test_default_vid_pid_values(self):
        """Test USB VID/PID default values."""
        from rpi_logger.modules.DRT.config import DRTConfig

        config = DRTConfig()
        assert config.device_vid == 0x239A
        assert config.device_pid == 0x801E
        assert config.baudrate == 9600


# =============================================================================
# Protocol Tests
# =============================================================================

class TestSDRTProtocol:
    """Tests for sDRT protocol constants and command structure."""

    def test_sdrt_commands_defined(self):
        """Test that all required sDRT commands are defined."""
        from rpi_logger.modules.DRT.drt_core.protocols import SDRT_COMMANDS

        assert "start" in SDRT_COMMANDS
        assert "stop" in SDRT_COMMANDS
        assert "stim_on" in SDRT_COMMANDS
        assert "stim_off" in SDRT_COMMANDS
        assert "get_config" in SDRT_COMMANDS
        assert "set_lowerISI" in SDRT_COMMANDS
        assert "set_upperISI" in SDRT_COMMANDS
        assert "set_stimDur" in SDRT_COMMANDS
        assert "set_intensity" in SDRT_COMMANDS

    def test_sdrt_command_strings(self):
        """Test sDRT command string values."""
        from rpi_logger.modules.DRT.drt_core.protocols import SDRT_COMMANDS

        assert SDRT_COMMANDS["start"] == "exp_start"
        assert SDRT_COMMANDS["stop"] == "exp_stop"
        assert SDRT_COMMANDS["stim_on"] == "stim_on"
        assert SDRT_COMMANDS["stim_off"] == "stim_off"

    def test_sdrt_responses_defined(self):
        """Test that sDRT response types are defined."""
        from rpi_logger.modules.DRT.drt_core.protocols import SDRT_RESPONSES

        assert "clk" in SDRT_RESPONSES
        assert "trl" in SDRT_RESPONSES
        assert "end" in SDRT_RESPONSES
        assert "stm" in SDRT_RESPONSES
        assert "cfg" in SDRT_RESPONSES

    def test_sdrt_response_mappings(self):
        """Test sDRT response key to type mappings."""
        from rpi_logger.modules.DRT.drt_core.protocols import SDRT_RESPONSES

        assert SDRT_RESPONSES["clk"] == "click"
        assert SDRT_RESPONSES["trl"] == "trial"
        assert SDRT_RESPONSES["end"] == "end"
        assert SDRT_RESPONSES["stm"] == "stimulus"
        assert SDRT_RESPONSES["cfg"] == "config"

    def test_sdrt_line_ending(self):
        """Test sDRT uses correct line ending."""
        from rpi_logger.modules.DRT.drt_core.protocols import SDRT_LINE_ENDING

        assert SDRT_LINE_ENDING == "\n\r"

    def test_sdrt_csv_header_fields(self):
        """Test sDRT CSV header contains required fields."""
        from rpi_logger.modules.DRT.drt_core.protocols import SDRT_CSV_HEADER

        assert "trial" in SDRT_CSV_HEADER
        assert "module" in SDRT_CSV_HEADER
        assert "device_id" in SDRT_CSV_HEADER
        assert "label" in SDRT_CSV_HEADER
        assert "record_time_unix" in SDRT_CSV_HEADER
        assert "record_time_mono" in SDRT_CSV_HEADER
        assert "device_time_unix" in SDRT_CSV_HEADER
        assert "device_time_offset" in SDRT_CSV_HEADER
        assert "responses" in SDRT_CSV_HEADER
        assert "reaction_time_ms" in SDRT_CSV_HEADER
        # sDRT does NOT have battery_percent
        assert "battery_percent" not in SDRT_CSV_HEADER

    def test_sdrt_iso_preset_values(self):
        """Test sDRT ISO standard preset values."""
        from rpi_logger.modules.DRT.drt_core.protocols import SDRT_ISO_PRESET

        assert SDRT_ISO_PRESET["lowerISI"] == 3000  # 3 seconds
        assert SDRT_ISO_PRESET["upperISI"] == 5000  # 5 seconds
        assert SDRT_ISO_PRESET["stimDur"] == 1000   # 1 second
        assert SDRT_ISO_PRESET["intensity"] == 255  # Max intensity


class TestWDRTProtocol:
    """Tests for wDRT protocol constants and command structure."""

    def test_wdrt_commands_defined(self):
        """Test that all required wDRT commands are defined."""
        from rpi_logger.modules.DRT.drt_core.protocols import WDRT_COMMANDS

        assert "start" in WDRT_COMMANDS
        assert "stop" in WDRT_COMMANDS
        assert "stim_on" in WDRT_COMMANDS
        assert "stim_off" in WDRT_COMMANDS
        assert "get_config" in WDRT_COMMANDS
        assert "get_battery" in WDRT_COMMANDS
        assert "set_rtc" in WDRT_COMMANDS
        assert "iso" in WDRT_COMMANDS

    def test_wdrt_command_strings(self):
        """Test wDRT command string values."""
        from rpi_logger.modules.DRT.drt_core.protocols import WDRT_COMMANDS

        assert WDRT_COMMANDS["start"] == "trl>1"
        assert WDRT_COMMANDS["stop"] == "trl>0"
        assert WDRT_COMMANDS["stim_on"] == "dev>1"
        assert WDRT_COMMANDS["stim_off"] == "dev>0"
        assert WDRT_COMMANDS["get_battery"] == "get_bat>"
        assert WDRT_COMMANDS["iso"] == "dev>iso"

    def test_wdrt_responses_defined(self):
        """Test that wDRT response types are defined."""
        from rpi_logger.modules.DRT.drt_core.protocols import WDRT_RESPONSES

        assert "cfg" in WDRT_RESPONSES
        assert "stm" in WDRT_RESPONSES
        assert "bty" in WDRT_RESPONSES
        assert "exp" in WDRT_RESPONSES
        assert "trl" in WDRT_RESPONSES
        assert "rt" in WDRT_RESPONSES
        assert "clk" in WDRT_RESPONSES
        assert "dta" in WDRT_RESPONSES

    def test_wdrt_response_mappings(self):
        """Test wDRT response key to type mappings."""
        from rpi_logger.modules.DRT.drt_core.protocols import WDRT_RESPONSES

        assert WDRT_RESPONSES["bty"] == "battery"
        assert WDRT_RESPONSES["exp"] == "experiment"
        assert WDRT_RESPONSES["dta"] == "data"
        assert WDRT_RESPONSES["rt"] == "reaction_time"

    def test_wdrt_line_ending(self):
        """Test wDRT uses correct line ending."""
        from rpi_logger.modules.DRT.drt_core.protocols import WDRT_LINE_ENDING

        assert WDRT_LINE_ENDING == "\n"

    def test_wdrt_csv_header_fields(self):
        """Test wDRT CSV header contains required fields including battery."""
        from rpi_logger.modules.DRT.drt_core.protocols import WDRT_CSV_HEADER

        assert "trial" in WDRT_CSV_HEADER
        assert "module" in WDRT_CSV_HEADER
        assert "device_id" in WDRT_CSV_HEADER
        assert "label" in WDRT_CSV_HEADER
        assert "record_time_unix" in WDRT_CSV_HEADER
        assert "record_time_mono" in WDRT_CSV_HEADER
        assert "device_time_unix" in WDRT_CSV_HEADER
        assert "device_time_offset" in WDRT_CSV_HEADER
        assert "responses" in WDRT_CSV_HEADER
        assert "reaction_time_ms" in WDRT_CSV_HEADER
        # wDRT DOES have battery_percent
        assert "battery_percent" in WDRT_CSV_HEADER

    def test_wdrt_config_params_mapping(self):
        """Test wDRT config parameter name mappings."""
        from rpi_logger.modules.DRT.drt_core.protocols import WDRT_CONFIG_PARAMS

        assert WDRT_CONFIG_PARAMS["ONTM"] == "stimDur"
        assert WDRT_CONFIG_PARAMS["ISIH"] == "upperISI"
        assert WDRT_CONFIG_PARAMS["ISIL"] == "lowerISI"
        assert WDRT_CONFIG_PARAMS["DBNC"] == "debounce"
        assert WDRT_CONFIG_PARAMS["SPCT"] == "intensity"


class TestSharedProtocolConstants:
    """Tests for shared protocol constants."""

    def test_response_delimiter(self):
        """Test response delimiter is defined."""
        from rpi_logger.modules.DRT.drt_core.protocols import RESPONSE_DELIMITER

        assert RESPONSE_DELIMITER == ">"

    def test_timeout_values(self):
        """Test default timeout values."""
        from rpi_logger.modules.DRT.drt_core.protocols import (
            DEFAULT_READ_TIMEOUT,
            DEFAULT_WRITE_TIMEOUT,
        )

        assert DEFAULT_READ_TIMEOUT == 1.0
        assert DEFAULT_WRITE_TIMEOUT == 0.1

    def test_rt_timeout_value(self):
        """Test reaction time timeout value."""
        from rpi_logger.modules.DRT.drt_core.protocols import RT_TIMEOUT_VALUE

        assert RT_TIMEOUT_VALUE == -1


# =============================================================================
# Device Types Tests
# =============================================================================

class TestDRTDeviceTypes:
    """Tests for DRT device type enumeration."""

    def test_device_types_defined(self):
        """Test all device types are defined."""
        from rpi_logger.modules.DRT.drt_core.device_types import DRTDeviceType

        assert hasattr(DRTDeviceType, "SDRT")
        assert hasattr(DRTDeviceType, "WDRT_USB")
        assert hasattr(DRTDeviceType, "WDRT_WIRELESS")

    def test_device_type_values(self):
        """Test device type enum values."""
        from rpi_logger.modules.DRT.drt_core.device_types import DRTDeviceType

        assert DRTDeviceType.SDRT.value == "DRT"
        assert DRTDeviceType.WDRT_USB.value == "wDRT_USB"
        assert DRTDeviceType.WDRT_WIRELESS.value == "wDRT_Wireless"

    def test_device_types_are_distinct(self):
        """Test all device types are distinct."""
        from rpi_logger.modules.DRT.drt_core.device_types import DRTDeviceType

        types = [DRTDeviceType.SDRT, DRTDeviceType.WDRT_USB, DRTDeviceType.WDRT_WIRELESS]
        values = [t.value for t in types]
        assert len(values) == len(set(values))  # All unique


# =============================================================================
# Mock DRT Device Tests
# =============================================================================

class TestMockDRTDevice:
    """Tests for MockDRTDevice from serial_mocks."""

    def test_mock_drt_device_creation_sdrt(self, mock_drt_device):
        """Test MockDRTDevice creation for sDRT."""
        assert mock_drt_device.device_type == "sdrt"
        assert mock_drt_device.config.baudrate == 115200

    def test_mock_drt_device_creation_wdrt(self):
        """Test MockDRTDevice creation for wDRT."""
        from tests.infrastructure.mocks.serial_mocks import MockDRTDevice

        device = MockDRTDevice(device_type="wdrt")
        assert device.device_type == "wdrt"
        assert device.config.baudrate == 57600

    def test_mock_drt_serial_interface(self, mock_drt_device):
        """Test MockDRTDevice implements serial interface."""
        mock_drt_device.open()

        assert mock_drt_device.is_open is True
        assert hasattr(mock_drt_device, "read")
        assert hasattr(mock_drt_device, "readline")
        assert hasattr(mock_drt_device, "write")

        mock_drt_device.close()
        assert mock_drt_device.is_open is False

    def test_mock_drt_write_log(self, mock_drt_device):
        """Test MockDRTDevice logs written data."""
        mock_drt_device.open()
        mock_drt_device.write(b"exp_start\n\r")

        write_log = mock_drt_device.get_write_log()
        assert len(write_log) == 1
        assert write_log[0] == b"exp_start\n\r"

    def test_mock_drt_simulate_trial_sdrt(self, mock_drt_device):
        """Test sDRT trial data simulation."""
        response = mock_drt_device.simulate_trial(
            reaction_time_ms=250,
            responses=1,
        )

        assert b"trl>" in response
        assert b"250" in response
        assert b"1" in response

    def test_mock_drt_simulate_trial_wdrt(self):
        """Test wDRT trial data simulation with battery."""
        from tests.infrastructure.mocks.serial_mocks import MockDRTDevice

        device = MockDRTDevice(device_type="wdrt")
        response = device.simulate_trial(
            reaction_time_ms=300,
            responses=2,
            battery_percent=75,
        )

        assert b"dta>" in response
        assert b"300" in response
        assert b"2" in response
        assert b"75" in response

    def test_mock_drt_simulate_timeout(self, mock_drt_device):
        """Test timeout trial simulation."""
        response = mock_drt_device.simulate_timeout()

        assert b"-1" in response  # RT_TIMEOUT_VALUE
        assert b",0," in response  # 0 responses

    def test_mock_drt_response_handlers_sdrt(self, mock_drt_device):
        """Test sDRT command response handlers."""
        mock_drt_device.open()

        # Write start command, expect expStart response
        mock_drt_device.write(b"exp_start")

        # Read the response
        response = mock_drt_device.readline()
        assert b"expStart" in response

    def test_mock_drt_response_handlers_wdrt(self):
        """Test wDRT command response handlers."""
        from tests.infrastructure.mocks.serial_mocks import MockDRTDevice

        device = MockDRTDevice(device_type="wdrt")
        device.open()

        device.write(b"trl>1")

        response = device.readline()
        assert b"trl>1" in response


# =============================================================================
# Data Logger Tests
# =============================================================================

class TestDRTDataLogger:
    """Tests for DRTDataLogger CSV output."""

    @pytest.fixture
    def data_logger_sdrt(self, tmp_path):
        """Create an sDRT data logger with temp directory."""
        from rpi_logger.modules.DRT.drt_core.data_logger import DRTDataLogger

        return DRTDataLogger(
            output_dir=tmp_path,
            device_id="/dev/ttyACM0",
            device_type="sdrt",
        )

    @pytest.fixture
    def data_logger_wdrt(self, tmp_path):
        """Create a wDRT data logger with temp directory."""
        from rpi_logger.modules.DRT.drt_core.data_logger import DRTDataLogger

        return DRTDataLogger(
            output_dir=tmp_path,
            device_id="/dev/ttyACM1",
            device_type="wdrt",
        )

    def test_csv_header_sdrt(self, data_logger_sdrt):
        """Test sDRT CSV header format."""
        from rpi_logger.modules.DRT.drt_core.protocols import SDRT_CSV_HEADER

        assert data_logger_sdrt.csv_header == SDRT_CSV_HEADER

    def test_csv_header_wdrt(self, data_logger_wdrt):
        """Test wDRT CSV header format."""
        from rpi_logger.modules.DRT.drt_core.protocols import WDRT_CSV_HEADER

        assert data_logger_wdrt.csv_header == WDRT_CSV_HEADER

    def test_sanitize_device_id_via_shared_function(self, data_logger_sdrt):
        """Test that device ID sanitization uses the shared sanitize_device_id function."""
        from rpi_logger.modules.base.storage_utils import sanitize_device_id
        # Should convert /dev/ttyACM0 to dev_ttyacm0
        sanitized = sanitize_device_id(data_logger_sdrt.device_id)
        assert "/" not in sanitized
        assert "\\" not in sanitized
        assert sanitized == "dev_ttyacm0"

    def test_format_device_id_sdrt(self, data_logger_sdrt):
        """Test device ID formatting for sDRT."""
        device_id = data_logger_sdrt._format_device_id_for_csv()
        assert device_id.startswith("DRT_")

    def test_format_device_id_wdrt(self, data_logger_wdrt):
        """Test device ID formatting for wDRT."""
        device_id = data_logger_wdrt._format_device_id_for_csv()
        assert device_id.startswith("wDRT_")

    def test_start_recording_creates_file(self, data_logger_sdrt, tmp_path):
        """Test that start_recording creates CSV file."""
        data_logger_sdrt.start_recording(trial_number=1)

        assert data_logger_sdrt.filepath is not None
        assert data_logger_sdrt.filepath.exists()
        assert data_logger_sdrt.filepath.suffix == ".csv"

        data_logger_sdrt.stop_recording()

    def test_start_recording_writes_header(self, data_logger_sdrt, tmp_path):
        """Test that start_recording writes CSV header."""
        data_logger_sdrt.start_recording(trial_number=1)
        filepath = data_logger_sdrt.filepath  # Save before stop clears it
        data_logger_sdrt.stop_recording()

        content = filepath.read_text()
        lines = content.strip().split("\n")

        assert len(lines) >= 1
        assert "trial" in lines[0]
        assert "module" in lines[0]

    def test_log_trial_sdrt_format(self, data_logger_sdrt, tmp_path):
        """Test sDRT trial logging format."""
        data_logger_sdrt.start_recording(trial_number=1)

        trial_data = {
            "timestamp": 12345,
            "trial_number": 1,
            "reaction_time": 250,
        }
        result = data_logger_sdrt.log_trial(trial_data, click_count=1)
        filepath = data_logger_sdrt.filepath  # Save before stop clears it
        data_logger_sdrt.stop_recording()

        assert result is True

        # Read and parse CSV
        with open(filepath, "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 1
        row = rows[0]
        assert row["trial"] == "1"
        assert row["module"] == "DRT"
        assert "DRT_" in row["device_id"]
        assert row["reaction_time_ms"] == "250"
        assert row["responses"] == "1"

    def test_log_trial_wdrt_format_with_battery(self, data_logger_wdrt, tmp_path):
        """Test wDRT trial logging format includes battery."""
        data_logger_wdrt.start_recording(trial_number=1)

        trial_data = {
            "timestamp": 12345,
            "trial_number": 1,
            "reaction_time": 300,
            "clicks": 2,
            "battery": 85,
            "device_utc": 1704499200,
        }
        result = data_logger_wdrt.log_trial(trial_data)
        filepath = data_logger_wdrt.filepath  # Save before stop clears it
        data_logger_wdrt.stop_recording()

        assert result is True

        # Read and parse CSV
        with open(filepath, "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 1
        row = rows[0]
        assert row["trial"] == "1"
        assert row["module"] == "DRT"
        assert "wDRT_" in row["device_id"]
        assert row["reaction_time_ms"] == "300"
        assert row["responses"] == "2"
        assert row["battery_percent"] == "85"

    def test_log_trial_with_label(self, data_logger_sdrt, tmp_path):
        """Test trial logging includes label/condition."""
        data_logger_sdrt.set_trial_label("baseline")
        data_logger_sdrt.start_recording(trial_number=1)

        trial_data = {
            "timestamp": 12345,
            "trial_number": 1,
            "reaction_time": 250,
        }
        data_logger_sdrt.log_trial(trial_data, click_count=1)
        filepath = data_logger_sdrt.filepath  # Save before stop clears it
        data_logger_sdrt.stop_recording()

        with open(filepath, "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert rows[0]["label"] == "baseline"

    def test_log_trial_timeout_value(self, data_logger_sdrt, tmp_path):
        """Test logging timeout (no response) trial."""
        from rpi_logger.modules.DRT.drt_core.protocols import RT_TIMEOUT_VALUE

        data_logger_sdrt.start_recording(trial_number=1)

        trial_data = {
            "timestamp": 12345,
            "trial_number": 1,
            "reaction_time": RT_TIMEOUT_VALUE,
        }
        data_logger_sdrt.log_trial(trial_data, click_count=0)
        filepath = data_logger_sdrt.filepath  # Save before stop clears it
        data_logger_sdrt.stop_recording()

        with open(filepath, "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert rows[0]["reaction_time_ms"] == "-1"
        assert rows[0]["responses"] == "0"

    def test_stop_recording_closes_file(self, data_logger_sdrt, tmp_path):
        """Test stop_recording closes the file handle."""
        data_logger_sdrt.start_recording(trial_number=1)
        assert data_logger_sdrt._csv_file is not None

        data_logger_sdrt.stop_recording()
        assert data_logger_sdrt._csv_file is None

    def test_stop_recording_clears_label(self, data_logger_sdrt, tmp_path):
        """Test stop_recording clears trial label."""
        data_logger_sdrt.set_trial_label("test_condition")
        data_logger_sdrt.start_recording(trial_number=1)
        data_logger_sdrt.stop_recording()

        assert data_logger_sdrt._trial_label == ""

    def test_multiple_trials_single_file(self, data_logger_sdrt, tmp_path):
        """Test multiple trials are logged to same file."""
        data_logger_sdrt.start_recording(trial_number=1)

        for i in range(5):
            trial_data = {
                "timestamp": 12345 + i * 1000,
                "trial_number": i + 1,
                "reaction_time": 200 + i * 10,
            }
            data_logger_sdrt.log_trial(trial_data, click_count=1)

        filepath = data_logger_sdrt.filepath  # Save before stop clears it
        data_logger_sdrt.stop_recording()

        with open(filepath, "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 5
        assert rows[0]["trial"] == "1"
        assert rows[4]["trial"] == "5"

    def test_log_trial_without_start_fails(self, tmp_path):
        """Test logging without start_recording fails gracefully."""
        from rpi_logger.modules.DRT.drt_core.data_logger import DRTDataLogger

        # Create logger with no output dir
        logger = DRTDataLogger(
            output_dir=None,
            device_id="/dev/ttyACM0",
            device_type="sdrt",
        )

        trial_data = {"timestamp": 12345, "trial_number": 1, "reaction_time": 250}
        result = logger.log_trial(trial_data)

        assert result is False

    def test_record_time_fields_populated(self, data_logger_sdrt, tmp_path):
        """Test record_time_unix and record_time_mono are populated."""
        data_logger_sdrt.start_recording(trial_number=1)

        trial_data = {
            "timestamp": 12345,
            "trial_number": 1,
            "reaction_time": 250,
        }
        data_logger_sdrt.log_trial(trial_data, click_count=1)
        filepath = data_logger_sdrt.filepath  # Save before stop clears it
        data_logger_sdrt.stop_recording()

        with open(filepath, "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        row = rows[0]
        # Should have valid unix timestamp (roughly current time)
        unix_time = float(row["record_time_unix"])
        assert unix_time > 1704000000  # After Jan 1, 2024

        # Should have valid monotonic timestamp
        mono_time = float(row["record_time_mono"])
        assert mono_time > 0


# =============================================================================
# Handler Response Processing Tests
# =============================================================================

class TestSDRTHandlerResponseProcessing:
    """Tests for sDRT handler response parsing."""

    @pytest.fixture
    def mock_transport(self):
        """Create a mock transport for testing."""
        transport = AsyncMock()
        transport.is_connected = True
        transport.write_line = AsyncMock(return_value=True)
        transport.read_line = AsyncMock(return_value=None)
        return transport

    @pytest.fixture
    def sdrt_handler(self, mock_transport, tmp_path):
        """Create an sDRT handler with mock transport."""
        from rpi_logger.modules.DRT.drt_core.handlers.sdrt_handler import SDRTHandler

        handler = SDRTHandler(
            device_id="/dev/ttyACM0",
            output_dir=tmp_path,
            transport=mock_transport,
        )
        return handler

    def test_handler_device_type(self, sdrt_handler):
        """Test handler reports correct device type."""
        from rpi_logger.modules.DRT.drt_core.device_types import DRTDeviceType

        assert sdrt_handler.device_type == DRTDeviceType.SDRT

    def test_process_click_response(self, sdrt_handler):
        """Test processing click response."""
        # Device sends cumulative click count
        sdrt_handler._process_response("clk>5")

        assert sdrt_handler._device_click_count == 5

    def test_process_trial_response(self, sdrt_handler):
        """Test processing trial response."""
        # Format: trl>timestamp,trial_number,reaction_time
        sdrt_handler._process_response("trl>12345,1,250")

        assert sdrt_handler._buffered_trial_data is not None
        assert sdrt_handler._buffered_trial_data["timestamp"] == 12345
        assert sdrt_handler._buffered_trial_data["trial_number"] == 1
        assert sdrt_handler._buffered_trial_data["reaction_time"] == 250

    def test_process_stimulus_on_response(self, sdrt_handler):
        """Test processing stimulus ON response."""
        sdrt_handler._process_response("stm>1")

        assert sdrt_handler._stimulus_on is True

    def test_process_stimulus_off_response(self, sdrt_handler):
        """Test processing stimulus OFF response."""
        sdrt_handler._stimulus_on = True
        sdrt_handler._process_response("stm>0")

        assert sdrt_handler._stimulus_on is False

    def test_process_invalid_response_ignored(self, sdrt_handler):
        """Test that invalid responses are ignored."""
        # No delimiter
        sdrt_handler._process_response("invalid_response")

        # Unknown key
        sdrt_handler._process_response("xyz>123")

        # Empty response
        sdrt_handler._process_response("")

        # Should not raise any exceptions

    def test_process_malformed_trial_ignored(self, sdrt_handler):
        """Test malformed trial response is handled."""
        # Too few parts
        sdrt_handler._process_response("trl>12345")

        assert sdrt_handler._buffered_trial_data is None

    def test_click_count_per_trial_calculation(self, sdrt_handler):
        """Test per-trial click count calculation from device cumulative count."""
        # Trial 1 starts - baseline is 0
        sdrt_handler._device_click_count = 0
        sdrt_handler._trial_start_click_count = 0
        sdrt_handler._process_response("stm>1")  # Stimulus ON - trial start

        # Device sends cumulative click during trial
        sdrt_handler._process_response("clk>3")

        assert sdrt_handler._device_click_count == 3
        assert sdrt_handler._click_count == 3  # Per-trial count

        # Stimulus OFF - end of trial 1
        sdrt_handler._process_response("stm>0")

        # Trial 2 starts
        sdrt_handler._process_response("stm>1")

        # Now baseline should be 3 (from previous trial)
        assert sdrt_handler._trial_start_click_count == 3

        # More clicks during trial 2
        sdrt_handler._process_response("clk>5")  # Cumulative = 5

        assert sdrt_handler._click_count == 2  # 5 - 3 = 2 per-trial clicks


class TestWDRTHandlerResponseProcessing:
    """Tests for wDRT handler response parsing."""

    @pytest.fixture
    def mock_transport(self):
        """Create a mock transport for testing."""
        transport = AsyncMock()
        transport.is_connected = True
        transport.write_line = AsyncMock(return_value=True)
        transport.read_line = AsyncMock(return_value=None)
        return transport

    @pytest.fixture
    def wdrt_handler(self, mock_transport, tmp_path):
        """Create a wDRT USB handler with mock transport."""
        from rpi_logger.modules.DRT.drt_core.handlers.wdrt_usb_handler import WDRTUSBHandler

        handler = WDRTUSBHandler(
            device_id="/dev/ttyACM0",
            output_dir=tmp_path,
            transport=mock_transport,
        )
        return handler

    def test_handler_device_type(self, wdrt_handler):
        """Test handler reports correct device type."""
        from rpi_logger.modules.DRT.drt_core.device_types import DRTDeviceType

        assert wdrt_handler.device_type == DRTDeviceType.WDRT_USB

    def test_process_battery_response(self, wdrt_handler):
        """Test processing battery response."""
        wdrt_handler._process_response("bty>85")

        assert wdrt_handler._battery_percent == 85
        assert wdrt_handler.battery_percent == 85

    def test_process_experiment_response(self, wdrt_handler):
        """Test processing experiment state response."""
        wdrt_handler._process_response("exp>1")
        assert wdrt_handler._recording is True

        wdrt_handler._process_response("exp>0")
        assert wdrt_handler._recording is False

    def test_process_data_packet(self, wdrt_handler, tmp_path):
        """Test processing combined data packet."""
        wdrt_handler._recording = True
        wdrt_handler._data_logger.start_recording(1)

        # Format: dta>block_ms,trial_n,clicks,rt,battery,device_utc
        wdrt_handler._process_response("dta>5000,1,2,300,85,1704499200")

        assert wdrt_handler._battery_percent == 85
        assert wdrt_handler._device_utc == 1704499200
        assert wdrt_handler._trial_number == 1

        wdrt_handler._data_logger.stop_recording()

    def test_process_click_response_wdrt(self, wdrt_handler):
        """Test wDRT click response (per-trial count, not cumulative)."""
        wdrt_handler._process_response("clk>3")

        # wDRT sends per-trial click count directly
        assert wdrt_handler._click_count == 3

    def test_process_reaction_time_response(self, wdrt_handler):
        """Test processing standalone reaction time response."""
        # This tests the rt> response handling
        wdrt_handler._process_response("rt>275")
        # Should dispatch event but not store in handler state
        # (reaction time is typically part of data packet)

    def test_battery_percent_property(self, wdrt_handler):
        """Test battery_percent property returns last known value."""
        assert wdrt_handler.battery_percent is None

        wdrt_handler._battery_percent = 75
        assert wdrt_handler.battery_percent == 75


# =============================================================================
# Handler Command Tests (using run_async helper)
# =============================================================================

class TestSDRTHandlerCommands:
    """Tests for sDRT handler commands."""

    @pytest.fixture
    def mock_transport(self):
        """Create a mock transport for testing."""
        transport = AsyncMock()
        transport.is_connected = True
        transport.write_line = AsyncMock(return_value=True)
        transport.read_line = AsyncMock(return_value=None)
        return transport

    @pytest.fixture
    def sdrt_handler(self, mock_transport, tmp_path):
        """Create an sDRT handler with mock transport."""
        from rpi_logger.modules.DRT.drt_core.handlers.sdrt_handler import SDRTHandler

        return SDRTHandler(
            device_id="/dev/ttyACM0",
            output_dir=tmp_path,
            transport=mock_transport,
        )

    def test_send_start_command(self, sdrt_handler, mock_transport):
        """Test sending start experiment command."""
        result = run_async(sdrt_handler.send_command("start"))

        assert result is True
        mock_transport.write_line.assert_called_once()
        call_args = mock_transport.write_line.call_args
        assert "exp_start" in call_args[0][0]

    def test_send_stop_command(self, sdrt_handler, mock_transport):
        """Test sending stop experiment command."""
        result = run_async(sdrt_handler.send_command("stop"))

        assert result is True
        call_args = mock_transport.write_line.call_args
        assert "exp_stop" in call_args[0][0]

    def test_send_stimulus_on_command(self, sdrt_handler, mock_transport):
        """Test sending stimulus on command."""
        result = run_async(sdrt_handler.set_stimulus(on=True))

        assert result is True
        call_args = mock_transport.write_line.call_args
        assert "stim_on" in call_args[0][0]

    def test_send_stimulus_off_command(self, sdrt_handler, mock_transport):
        """Test sending stimulus off command."""
        result = run_async(sdrt_handler.set_stimulus(on=False))

        assert result is True
        call_args = mock_transport.write_line.call_args
        assert "stim_off" in call_args[0][0]

    def test_send_command_with_value(self, sdrt_handler, mock_transport):
        """Test sending command with value parameter."""
        result = run_async(sdrt_handler.send_command("set_lowerISI", "3000"))

        assert result is True
        call_args = mock_transport.write_line.call_args
        assert "set_lowerISI 3000" in call_args[0][0]

    def test_send_unknown_command_fails(self, sdrt_handler, mock_transport):
        """Test that unknown commands fail."""
        result = run_async(sdrt_handler.send_command("unknown_command"))

        assert result is False
        mock_transport.write_line.assert_not_called()

    def test_start_experiment_resets_state(self, sdrt_handler, mock_transport):
        """Test start_experiment resets handler state."""
        sdrt_handler._click_count = 10
        sdrt_handler._device_click_count = 10

        run_async(sdrt_handler.start_experiment())

        assert sdrt_handler._click_count == 0
        assert sdrt_handler._device_click_count == 0
        assert sdrt_handler._recording is True

    def test_stop_experiment_sets_state(self, sdrt_handler, mock_transport):
        """Test stop_experiment sets recording state."""
        sdrt_handler._recording = True

        run_async(sdrt_handler.stop_experiment())

        assert sdrt_handler._recording is False

    def test_set_iso_params(self, sdrt_handler, mock_transport):
        """Test setting ISO standard parameters."""
        result = run_async(sdrt_handler.set_iso_params())

        assert result is True
        # Should have called write_line multiple times for each parameter
        assert mock_transport.write_line.call_count >= 1


class TestWDRTHandlerCommands:
    """Tests for wDRT handler commands."""

    @pytest.fixture
    def mock_transport(self):
        """Create a mock transport for testing."""
        transport = AsyncMock()
        transport.is_connected = True
        transport.write_line = AsyncMock(return_value=True)
        transport.read_line = AsyncMock(return_value=None)
        return transport

    @pytest.fixture
    def wdrt_handler(self, mock_transport, tmp_path):
        """Create a wDRT USB handler with mock transport."""
        from rpi_logger.modules.DRT.drt_core.handlers.wdrt_usb_handler import WDRTUSBHandler

        return WDRTUSBHandler(
            device_id="/dev/ttyACM0",
            output_dir=tmp_path,
            transport=mock_transport,
        )

    def test_send_start_command(self, wdrt_handler, mock_transport):
        """Test sending start command."""
        result = run_async(wdrt_handler.send_command("start"))

        assert result is True
        call_args = mock_transport.write_line.call_args
        assert "trl>1" in call_args[0][0]

    def test_send_stop_command(self, wdrt_handler, mock_transport):
        """Test sending stop command."""
        result = run_async(wdrt_handler.send_command("stop"))

        assert result is True
        call_args = mock_transport.write_line.call_args
        assert "trl>0" in call_args[0][0]

    def test_send_get_battery_command(self, wdrt_handler, mock_transport):
        """Test sending get battery command."""
        run_async(wdrt_handler.send_command("get_battery"))

        call_args = mock_transport.write_line.call_args
        assert "get_bat>" in call_args[0][0]

    def test_set_iso_params_wdrt(self, wdrt_handler, mock_transport):
        """Test wDRT ISO params uses single command."""
        result = run_async(wdrt_handler.set_iso_params())

        assert result is True
        call_args = mock_transport.write_line.call_args
        assert "dev>iso" in call_args[0][0]

    def test_sync_rtc(self, wdrt_handler, mock_transport):
        """Test RTC sync command."""
        result = run_async(wdrt_handler.sync_rtc())

        assert result is True
        call_args = mock_transport.write_line.call_args
        assert "set_rtc>" in call_args[0][0]

    def test_set_config_param(self, wdrt_handler, mock_transport):
        """Test setting individual config parameter."""
        result = run_async(wdrt_handler.set_config_param("stimDur", 1000))

        assert result is True
        call_args = mock_transport.write_line.call_args
        assert "set>" in call_args[0][0]
        assert "ONTM" in call_args[0][0]  # stimDur maps to ONTM
        assert "1000" in call_args[0][0]


# =============================================================================
# Transport Tests
# =============================================================================

class TestUSBTransport:
    """Tests for USBTransport serial communication (mocked)."""

    def test_transport_initialization(self):
        """Test USBTransport initialization."""
        from rpi_logger.modules.DRT.drt_core.transports.usb_transport import USBTransport

        transport = USBTransport(
            port="/dev/ttyACM0",
            baudrate=115200,
        )

        assert transport.port == "/dev/ttyACM0"
        assert transport.baudrate == 115200
        assert transport.is_connected is False

    def test_transport_default_timeouts(self):
        """Test USBTransport default timeout values."""
        from rpi_logger.modules.DRT.drt_core.transports.usb_transport import USBTransport
        from rpi_logger.modules.DRT.drt_core.protocols import (
            DEFAULT_READ_TIMEOUT,
            DEFAULT_WRITE_TIMEOUT,
        )

        transport = USBTransport(port="/dev/ttyACM0", baudrate=9600)

        assert transport.read_timeout == DEFAULT_READ_TIMEOUT
        assert transport.write_timeout == DEFAULT_WRITE_TIMEOUT

    def test_connect_success(self, patch_serial):
        """Test successful connection."""
        from rpi_logger.modules.DRT.drt_core.transports.usb_transport import USBTransport

        transport = USBTransport(port="/dev/ttyACM0", baudrate=9600)

        result = run_async(transport.connect())

        assert result is True
        assert transport.is_connected is True

    def test_connect_failure(self, patch_serial):
        """Test connection failure."""
        import serial
        from rpi_logger.modules.DRT.drt_core.transports.usb_transport import USBTransport

        patch_serial.side_effect = serial.SerialException("Port not found")

        transport = USBTransport(port="/dev/ttyNONEXIST", baudrate=9600)

        result = run_async(transport.connect())

        assert result is False
        assert transport.is_connected is False

    def test_disconnect(self, patch_serial):
        """Test disconnection."""
        from rpi_logger.modules.DRT.drt_core.transports.usb_transport import USBTransport

        transport = USBTransport(port="/dev/ttyACM0", baudrate=9600)
        run_async(transport.connect())
        run_async(transport.disconnect())

        assert transport.is_connected is False

    def test_write_when_not_connected(self, patch_serial):
        """Test write fails when not connected."""
        from rpi_logger.modules.DRT.drt_core.transports.usb_transport import USBTransport

        transport = USBTransport(port="/dev/ttyACM0", baudrate=9600)

        result = run_async(transport.write(b"test"))

        assert result is False

    def test_read_line_when_not_connected(self, patch_serial):
        """Test read_line returns None when not connected."""
        from rpi_logger.modules.DRT.drt_core.transports.usb_transport import USBTransport

        transport = USBTransport(port="/dev/ttyACM0", baudrate=9600)

        result = run_async(transport.read_line())

        assert result is None


# =============================================================================
# Error Handling Tests
# =============================================================================

class TestErrorHandling:
    """Tests for error handling in DRT components."""

    def test_data_logger_handles_io_error(self, tmp_path):
        """Test data logger handles file I/O errors gracefully."""
        from rpi_logger.modules.DRT.drt_core.data_logger import DRTDataLogger

        # Create logger with non-writable directory
        logger = DRTDataLogger(
            output_dir=Path("/nonexistent/path"),
            device_id="/dev/ttyACM0",
            device_type="sdrt",
        )

        # Should not raise, just return False
        trial_data = {"timestamp": 12345, "trial_number": 1, "reaction_time": 250}
        result = logger.log_trial(trial_data)

        assert result is False

    def test_handler_processes_malformed_response(self, tmp_path):
        """Test handler doesn't crash on malformed responses."""
        from rpi_logger.modules.DRT.drt_core.handlers.sdrt_handler import SDRTHandler

        transport = AsyncMock()
        transport.is_connected = True

        handler = SDRTHandler(
            device_id="/dev/ttyACM0",
            output_dir=tmp_path,
            transport=transport,
        )

        # Various malformed responses - should not raise
        handler._process_response("")
        handler._process_response("no_delimiter")
        handler._process_response(">empty_key")
        handler._process_response("trl>not,enough,parts")
        handler._process_response("clk>not_a_number")

    def test_handler_handles_missing_transport(self, tmp_path):
        """Test handler handles missing transport."""
        from rpi_logger.modules.DRT.drt_core.handlers.sdrt_handler import SDRTHandler

        handler = SDRTHandler(
            device_id="/dev/ttyACM0",
            output_dir=tmp_path,
            transport=None,
        )

        assert handler.is_connected is False

    def test_data_logger_reopens_file_if_closed(self, tmp_path):
        """Test data logger reopens file if unexpectedly closed."""
        from rpi_logger.modules.DRT.drt_core.data_logger import DRTDataLogger

        logger = DRTDataLogger(
            output_dir=tmp_path,
            device_id="/dev/ttyACM0",
            device_type="sdrt",
        )

        logger.start_recording(1)
        filepath = logger.filepath

        # Simulate file being closed unexpectedly
        logger._csv_file.close()
        logger._csv_file = None

        # Should reopen and log successfully
        trial_data = {"timestamp": 12345, "trial_number": 1, "reaction_time": 250}
        result = logger.log_trial(trial_data)

        assert result is True

        logger.stop_recording()


# =============================================================================
# Base Handler Tests
# =============================================================================

class TestBaseDRTHandler:
    """Tests for BaseDRTHandler common functionality."""

    @pytest.fixture
    def mock_transport(self):
        """Create a mock transport."""
        transport = AsyncMock()
        transport.is_connected = True
        transport.connect = AsyncMock(return_value=True)
        transport.disconnect = AsyncMock()
        transport.write_line = AsyncMock(return_value=True)
        transport.read_line = AsyncMock(return_value=None)
        return transport

    @pytest.fixture
    def sdrt_handler(self, mock_transport, tmp_path):
        """Create an sDRT handler for testing base functionality."""
        from rpi_logger.modules.DRT.drt_core.handlers.sdrt_handler import SDRTHandler

        return SDRTHandler(
            device_id="/dev/ttyACM0",
            output_dir=tmp_path,
            transport=mock_transport,
        )

    def test_is_connected_property(self, sdrt_handler, mock_transport):
        """Test is_connected reflects transport state."""
        mock_transport.is_connected = True
        assert sdrt_handler.is_connected is True

        mock_transport.is_connected = False
        assert sdrt_handler.is_connected is False

    def test_is_running_property(self, sdrt_handler):
        """Test is_running reflects handler state."""
        assert sdrt_handler.is_running is False

        sdrt_handler._running = True
        assert sdrt_handler.is_running is True

    def test_is_recording_property(self, sdrt_handler):
        """Test is_recording reflects recording state."""
        assert sdrt_handler.is_recording is False

        sdrt_handler._recording = True
        assert sdrt_handler.is_recording is True

    def test_set_active_trial_number(self, sdrt_handler):
        """Test setting active trial number."""
        sdrt_handler.set_active_trial_number(5)
        assert sdrt_handler._active_trial_number == 5

    def test_set_active_trial_number_coerces_invalid(self, sdrt_handler):
        """Test invalid trial numbers are coerced to 1."""
        sdrt_handler.set_active_trial_number(0)
        assert sdrt_handler._active_trial_number == 1

        sdrt_handler.set_active_trial_number(-5)
        assert sdrt_handler._active_trial_number == 1

        sdrt_handler.set_active_trial_number("not_a_number")
        assert sdrt_handler._active_trial_number == 1

    def test_set_recording_state(self, sdrt_handler):
        """Test set_recording_state method."""
        sdrt_handler.set_recording_state(True, "test_condition")

        assert sdrt_handler._recording is True
        assert sdrt_handler._trial_label == "test_condition"
        assert sdrt_handler._click_count == 0
        assert sdrt_handler._trial_number == 0

    def test_set_recording_state_clears_label_on_stop(self, sdrt_handler):
        """Test label is cleared when recording stops."""
        sdrt_handler.set_recording_state(True, "test")
        sdrt_handler.set_recording_state(False)

        assert sdrt_handler._trial_label == ""

    def test_update_output_dir(self, sdrt_handler, tmp_path):
        """Test updating output directory."""
        new_dir = tmp_path / "new_output"
        new_dir.mkdir()

        sdrt_handler.update_output_dir(new_dir)

        assert sdrt_handler.output_dir == new_dir

    def test_start_creates_read_task(self, sdrt_handler):
        """Test start creates read loop task."""
        async def _test():
            await sdrt_handler.start()
            assert sdrt_handler._running is True
            assert sdrt_handler._read_task is not None
            await sdrt_handler.stop()
        run_async(_test())

    def test_stop_cancels_read_task(self, sdrt_handler):
        """Test stop cancels read loop task."""
        async def _test():
            await sdrt_handler.start()
            await sdrt_handler.stop()
            assert sdrt_handler._running is False
            assert sdrt_handler._read_task is None
        run_async(_test())

    def test_data_callback_invoked(self, sdrt_handler):
        """Test data callback is invoked on events."""
        callback_data: List[Dict[str, Any]] = []

        async def mock_callback(device_id: str, data_type: str, data: Dict[str, Any]):
            callback_data.append({"device_id": device_id, "type": data_type, "data": data})

        sdrt_handler.data_callback = mock_callback

        run_async(sdrt_handler._dispatch_data_event("click", {"count": 5}))

        assert len(callback_data) == 1
        assert callback_data[0]["type"] == "click"
        assert callback_data[0]["data"]["count"] == 5


# =============================================================================
# Reaction Time Calculation Tests
# =============================================================================

class TestReactionTimeCalculation:
    """Tests for reaction time value handling."""

    def test_valid_reaction_time_logged(self, tmp_path):
        """Test valid reaction times are logged correctly."""
        from rpi_logger.modules.DRT.drt_core.data_logger import DRTDataLogger

        logger = DRTDataLogger(
            output_dir=tmp_path,
            device_id="/dev/ttyACM0",
            device_type="sdrt",
        )
        logger.start_recording(1)

        # Test various valid reaction times
        test_times = [150, 200, 250, 300, 500, 1000]

        for i, rt in enumerate(test_times):
            trial_data = {
                "timestamp": 12345 + i * 1000,
                "trial_number": i + 1,
                "reaction_time": rt,
            }
            result = logger.log_trial(trial_data, click_count=1)
            assert result is True

        filepath = logger.filepath  # Save before stop clears it
        logger.stop_recording()

        # Verify logged values
        with open(filepath, "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        for i, row in enumerate(rows):
            assert int(row["reaction_time_ms"]) == test_times[i]

    def test_timeout_reaction_time_value(self, tmp_path):
        """Test timeout value (-1) is logged correctly."""
        from rpi_logger.modules.DRT.drt_core.data_logger import DRTDataLogger
        from rpi_logger.modules.DRT.drt_core.protocols import RT_TIMEOUT_VALUE

        logger = DRTDataLogger(
            output_dir=tmp_path,
            device_id="/dev/ttyACM0",
            device_type="sdrt",
        )
        logger.start_recording(1)

        trial_data = {
            "timestamp": 12345,
            "trial_number": 1,
            "reaction_time": RT_TIMEOUT_VALUE,  # -1
        }
        logger.log_trial(trial_data, click_count=0)
        filepath = logger.filepath  # Save before stop clears it
        logger.stop_recording()

        with open(filepath, "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert rows[0]["reaction_time_ms"] == "-1"


# =============================================================================
# Integration-style Tests (Still Unit Tests - Mocked)
# =============================================================================

class TestSDRTFullWorkflow:
    """Test complete sDRT workflow with mocked components."""

    @pytest.fixture
    def mock_transport(self):
        """Create a mock transport."""
        transport = AsyncMock()
        transport.is_connected = True
        transport.write_line = AsyncMock(return_value=True)
        transport.read_line = AsyncMock(return_value=None)
        return transport

    def test_full_trial_workflow(self, mock_transport, tmp_path):
        """Test complete trial workflow: start -> stimulus -> response -> data."""
        from rpi_logger.modules.DRT.drt_core.handlers.sdrt_handler import SDRTHandler

        handler = SDRTHandler(
            device_id="/dev/ttyACM0",
            output_dir=tmp_path,
            transport=mock_transport,
        )

        events: List[Dict[str, Any]] = []

        async def capture_event(device_id: str, data_type: str, data: Dict[str, Any]):
            events.append({"type": data_type, "data": data})

        handler.data_callback = capture_event

        # Start experiment
        run_async(handler.start_experiment())
        assert handler.is_recording is True

        # Stimulus ON (trial starts)
        handler._process_response("stm>1")
        assert handler._stimulus_on is True

        # Click during stimulus
        handler._process_response("clk>1")

        # Trial data arrives
        handler._process_response("trl>12345,1,250")
        assert handler._buffered_trial_data is not None

        # Stimulus OFF (trial ends, data logged)
        handler._process_response("stm>0")
        assert handler._stimulus_on is False

        # Stop experiment
        run_async(handler.stop_experiment())
        assert handler.is_recording is False


class TestWDRTFullWorkflow:
    """Test complete wDRT workflow with mocked components."""

    @pytest.fixture
    def mock_transport(self):
        """Create a mock transport."""
        transport = AsyncMock()
        transport.is_connected = True
        transport.write_line = AsyncMock(return_value=True)
        transport.read_line = AsyncMock(return_value=None)
        return transport

    def test_full_trial_workflow_with_battery(self, mock_transport, tmp_path):
        """Test complete wDRT workflow including battery monitoring."""
        from rpi_logger.modules.DRT.drt_core.handlers.wdrt_usb_handler import WDRTUSBHandler

        handler = WDRTUSBHandler(
            device_id="/dev/ttyACM0",
            output_dir=tmp_path,
            transport=mock_transport,
        )

        events: List[Dict[str, Any]] = []

        async def capture_event(device_id: str, data_type: str, data: Dict[str, Any]):
            events.append({"type": data_type, "data": data})

        handler.data_callback = capture_event

        # Check battery before starting
        handler._process_response("bty>92")
        assert handler.battery_percent == 92

        # Start experiment
        run_async(handler.start_experiment())
        assert handler.is_recording is True

        # Data packet (includes trial data and battery)
        # Format: dta>block_ms,trial_n,clicks,rt,battery,device_utc
        handler._process_response("dta>5000,1,1,275,91,1704499200")

        assert handler.battery_percent == 91
        assert handler._trial_number == 1

        # Stop experiment
        run_async(handler.stop_experiment())


# =============================================================================
# Run configuration for standalone execution
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
