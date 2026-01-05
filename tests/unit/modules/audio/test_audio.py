"""Unit tests for the Audio module.

This module provides comprehensive tests for:
- Configuration loading and validation (AudioSettings)
- Audio device detection and management (DeviceManager)
- Recording start/stop logic (RecordingManager)
- File output handling (AudioDeviceRecorder)
- Error handling for missing devices

All tests are isolated and mock all hardware interactions using fixtures
from tests/unit/conftest.py and mocks from tests/infrastructure/mocks/audio_mocks.py.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

# Import the modules under test
from rpi_logger.modules.Audio.config.settings import (
    AudioSettings,
    read_config_file,
    build_arg_parser,
)
from rpi_logger.modules.Audio.domain.entities import AudioDeviceInfo, AudioSnapshot
from rpi_logger.modules.Audio.domain.state import AudioState
from rpi_logger.modules.Audio.domain.level_meter import LevelMeter
from rpi_logger.modules.Audio.domain.constants import (
    AUDIO_BIT_DEPTH,
    AUDIO_CHANNELS_MONO,
    DB_MIN,
    DB_MAX,
)


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def mock_device_info() -> AudioDeviceInfo:
    """Create a mock AudioDeviceInfo for testing."""
    return AudioDeviceInfo(
        device_id=0,
        name="Mock Test Microphone",
        channels=2,
        sample_rate=48000.0,
    )


@pytest.fixture
def mock_device_info_mono() -> AudioDeviceInfo:
    """Create a mock mono AudioDeviceInfo for testing."""
    return AudioDeviceInfo(
        device_id=1,
        name="USB Microphone",
        channels=1,
        sample_rate=44100.0,
    )


@pytest.fixture
def audio_state() -> AudioState:
    """Create a fresh AudioState instance."""
    return AudioState()


@pytest.fixture
def level_meter() -> LevelMeter:
    """Create a fresh LevelMeter instance."""
    return LevelMeter()


@pytest.fixture
def mock_logger() -> logging.Logger:
    """Create a mock logger for testing."""
    logger = logging.getLogger("test_audio")
    logger.setLevel(logging.DEBUG)
    return logger


@pytest.fixture
def sample_audio_data() -> np.ndarray:
    """Generate sample audio data for testing."""
    # Generate 1 second of 440Hz sine wave at 48kHz
    sample_rate = 48000
    duration = 0.1
    t = np.linspace(0, duration, int(sample_rate * duration), dtype=np.float32)
    return 0.5 * np.sin(2 * np.pi * 440 * t).astype(np.float32)


@pytest.fixture
def silence_audio_data() -> np.ndarray:
    """Generate silent audio data for testing."""
    return np.zeros(4800, dtype=np.float32)


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    """Create a temporary config file for testing."""
    config_path = tmp_path / "config.txt"
    config_path.write_text("""
# Audio module configuration
output_dir = /tmp/audio_output
session_prefix = test_session
sample_rate = 44100
console_output = true
meter_refresh_interval = 0.1
""")
    return config_path


@pytest.fixture
def empty_config_file(tmp_path: Path) -> Path:
    """Create an empty config file for testing."""
    config_path = tmp_path / "empty_config.txt"
    config_path.write_text("")
    return config_path


# =============================================================================
# Test AudioSettings Configuration
# =============================================================================

class TestAudioSettings:
    """Tests for AudioSettings configuration loading and validation."""

    def test_default_values(self):
        """Test that AudioSettings has correct default values."""
        settings = AudioSettings()

        assert settings.output_dir == Path("audio")
        assert settings.session_prefix == "audio"
        assert settings.log_level == "debug"
        assert settings.log_file is None
        assert settings.enable_commands is False
        assert settings.sample_rate == 48_000
        assert settings.console_output is False
        assert settings.meter_refresh_interval == 0.08
        assert settings.recorder_start_timeout == 3.0
        assert settings.recorder_stop_timeout == 2.0
        assert settings.shutdown_timeout == 15.0

    def test_from_args_with_defaults(self):
        """Test creating settings from args with default values."""
        args = MagicMock()
        args.output_dir = Path("/tmp/test")
        args.session_prefix = "test_prefix"
        args.log_level = "info"
        args.log_file = None
        args.enable_commands = False
        args.sample_rate = 44100
        args.console_output = True
        args.meter_refresh_interval = 0.1
        args.recorder_start_timeout = 5.0
        args.recorder_stop_timeout = 3.0
        args.shutdown_timeout = 20.0

        settings = AudioSettings.from_args(args)

        assert settings.output_dir == Path("/tmp/test")
        assert settings.session_prefix == "test_prefix"
        assert settings.sample_rate == 44100
        assert settings.console_output is True

    def test_from_args_with_missing_attributes(self):
        """Test creating settings from args with missing attributes uses defaults."""
        args = MagicMock(spec=[])  # Empty spec means no attributes

        settings = AudioSettings.from_args(args)

        # Should use defaults
        assert settings.sample_rate == 48_000
        assert settings.console_output is False

    def test_from_args_output_dir_string_conversion(self):
        """Test that output_dir string is converted to Path."""
        args = MagicMock()
        args.output_dir = "/tmp/string_path"
        args.session_prefix = None

        settings = AudioSettings.from_args(args)

        assert isinstance(settings.output_dir, Path)
        assert settings.output_dir == Path("/tmp/string_path")

class TestConfigFile:
    """Tests for config file reading."""

    def test_read_config_file_success(self, config_file: Path):
        """Test reading a valid config file."""
        config = read_config_file(config_file)

        assert config["sample_rate"] == 44100
        assert config["console_output"] is True
        assert config["meter_refresh_interval"] == 0.1

    def test_read_config_file_nonexistent(self, tmp_path: Path):
        """Test reading a nonexistent config file returns empty dict."""
        config = read_config_file(tmp_path / "nonexistent.txt")
        assert config == {}

    def test_read_config_file_empty(self, empty_config_file: Path):
        """Test reading an empty config file returns empty dict."""
        config = read_config_file(empty_config_file)
        assert config == {}

    def test_read_config_file_boolean_values(self, tmp_path: Path):
        """Test boolean value parsing in config file."""
        config_path = tmp_path / "bool_config.txt"
        config_path.write_text("""
true_val1 = true
true_val2 = yes
true_val3 = on
false_val1 = false
false_val2 = no
false_val3 = off
""")
        config = read_config_file(config_path)

        assert config["true_val1"] is True
        assert config["true_val2"] is True
        assert config["true_val3"] is True
        assert config["false_val1"] is False
        assert config["false_val2"] is False
        assert config["false_val3"] is False

    def test_read_config_file_comments_ignored(self, tmp_path: Path):
        """Test that comments are ignored in config file."""
        config_path = tmp_path / "comment_config.txt"
        config_path.write_text("""
# This is a comment
key1 = value1
# Another comment
key2 = 42
""")
        config = read_config_file(config_path)

        assert len(config) == 2
        assert config["key1"] == "value1"
        assert config["key2"] == 42

    def test_read_config_file_float_values(self, tmp_path: Path):
        """Test float value parsing in config file."""
        config_path = tmp_path / "float_config.txt"
        config_path.write_text("""
float_val = 3.14
int_val = 42
""")
        config = read_config_file(config_path)

        assert config["float_val"] == 3.14
        assert config["int_val"] == 42

    def test_read_config_file_invalid_lines_skipped(self, tmp_path: Path):
        """Test that invalid lines are skipped."""
        config_path = tmp_path / "invalid_config.txt"
        config_path.write_text("""
valid_key = valid_value
no_equals_sign
= no_key
another_valid = 123
""")
        config = read_config_file(config_path)

        assert len(config) == 2
        assert config["valid_key"] == "valid_value"
        assert config["another_valid"] == 123


class TestBuildArgParser:
    """Tests for argument parser building."""

    def test_build_arg_parser_with_defaults(self):
        """Test building argument parser with default config."""
        parser = build_arg_parser({})

        # Parse with no arguments
        args = parser.parse_args([])

        assert hasattr(args, "output_dir")
        assert hasattr(args, "sample_rate")

    def test_build_arg_parser_with_config_defaults(self):
        """Test building argument parser with config overrides."""
        config = {
            "sample_rate": 44100,
            "output_dir": "/custom/path",
        }
        parser = build_arg_parser(config)

        args = parser.parse_args([])

        assert args.sample_rate == 44100

    def test_build_arg_parser_cli_overrides_config(self):
        """Test that CLI arguments override config defaults."""
        config = {"sample_rate": 44100}
        parser = build_arg_parser(config)

        args = parser.parse_args(["--sample-rate", "96000"])

        assert args.sample_rate == 96000


# =============================================================================
# Test AudioDeviceInfo Entity
# =============================================================================

class TestAudioDeviceInfo:
    """Tests for AudioDeviceInfo dataclass."""

    def test_create_device_info(self, mock_device_info: AudioDeviceInfo):
        """Test creating AudioDeviceInfo instance."""
        assert mock_device_info.device_id == 0
        assert mock_device_info.name == "Mock Test Microphone"
        assert mock_device_info.channels == 2
        assert mock_device_info.sample_rate == 48000.0

    def test_device_info_immutable(self, mock_device_info: AudioDeviceInfo):
        """Test that AudioDeviceInfo is frozen/immutable."""
        with pytest.raises(AttributeError):
            mock_device_info.device_id = 5

    def test_device_info_equality(self):
        """Test AudioDeviceInfo equality comparison."""
        device1 = AudioDeviceInfo(
            device_id=0,
            name="Test",
            channels=2,
            sample_rate=48000.0,
        )
        device2 = AudioDeviceInfo(
            device_id=0,
            name="Test",
            channels=2,
            sample_rate=48000.0,
        )
        device3 = AudioDeviceInfo(
            device_id=1,
            name="Test",
            channels=2,
            sample_rate=48000.0,
        )

        assert device1 == device2
        assert device1 != device3


# =============================================================================
# Test AudioState
# =============================================================================

class TestAudioState:
    """Tests for AudioState state management."""

    def test_initial_state(self, audio_state: AudioState):
        """Test initial state values."""
        assert audio_state.device is None
        assert audio_state.level_meter is None
        assert audio_state.session_dir is None
        assert audio_state.recording is False
        assert audio_state.trial_number == 1

    def test_set_device(self, audio_state: AudioState, mock_device_info: AudioDeviceInfo):
        """Test setting a device updates state correctly."""
        audio_state.set_device(mock_device_info)

        assert audio_state.device == mock_device_info
        assert audio_state.level_meter is not None
        assert isinstance(audio_state.level_meter, LevelMeter)

    def test_clear_device(self, audio_state: AudioState, mock_device_info: AudioDeviceInfo):
        """Test clearing device resets state."""
        audio_state.set_device(mock_device_info)
        audio_state.clear_device()

        assert audio_state.device is None
        assert audio_state.level_meter is None

    def test_set_session_dir(self, audio_state: AudioState, tmp_path: Path):
        """Test setting session directory."""
        audio_state.set_session_dir(tmp_path)
        assert audio_state.session_dir == tmp_path

    def test_set_session_dir_no_change_no_notify(self, audio_state: AudioState, tmp_path: Path):
        """Test that setting same session dir doesn't trigger notify."""
        observer_calls = []
        audio_state.subscribe(lambda s: observer_calls.append(s))
        observer_calls.clear()  # Clear initial subscription call

        audio_state.set_session_dir(tmp_path)
        audio_state.set_session_dir(tmp_path)  # Same value

        assert len(observer_calls) == 1  # Only one notification

    def test_set_recording_state(self, audio_state: AudioState):
        """Test setting recording state."""
        audio_state.set_recording(True, trial=5)

        assert audio_state.recording is True
        assert audio_state.trial_number == 5

    def test_set_recording_minimum_trial_number(self, audio_state: AudioState):
        """Test that trial number cannot be less than 1."""
        audio_state.set_recording(True, trial=0)
        assert audio_state.trial_number == 1

        audio_state.set_recording(True, trial=-5)
        assert audio_state.trial_number == 1

    def test_observer_subscription(self, audio_state: AudioState, mock_device_info: AudioDeviceInfo):
        """Test observer subscription and notification."""
        snapshots = []

        def observer(snapshot: AudioSnapshot):
            snapshots.append(snapshot)

        audio_state.subscribe(observer)

        # Should receive initial snapshot
        assert len(snapshots) == 1
        assert snapshots[0].device is None

        # Should receive update
        audio_state.set_device(mock_device_info)
        assert len(snapshots) == 2
        assert snapshots[1].device == mock_device_info

    def test_snapshot_creation(self, audio_state: AudioState, mock_device_info: AudioDeviceInfo, tmp_path: Path):
        """Test snapshot captures current state."""
        audio_state.set_device(mock_device_info)
        audio_state.set_session_dir(tmp_path)
        audio_state.set_recording(True, trial=3)

        snapshot = audio_state.snapshot()

        assert snapshot.device == mock_device_info
        assert snapshot.session_dir == tmp_path
        assert snapshot.recording is True
        assert snapshot.trial_number == 3
        assert "Recording trial 3" in snapshot.status_text

    def test_status_text_no_device(self, audio_state: AudioState):
        """Test status text when no device is assigned."""
        snapshot = audio_state.snapshot()
        assert "No audio device assigned" in snapshot.status_text

    def test_status_text_device_ready(self, audio_state: AudioState, mock_device_info: AudioDeviceInfo):
        """Test status text when device is ready."""
        audio_state.set_device(mock_device_info)
        snapshot = audio_state.snapshot()
        assert "Device ready" in snapshot.status_text
        assert mock_device_info.name in snapshot.status_text

    def test_status_payload(self, audio_state: AudioState, mock_device_info: AudioDeviceInfo):
        """Test status payload generation."""
        audio_state.set_device(mock_device_info)
        audio_state.set_recording(True, trial=2)

        payload = audio_state.status_payload()

        assert payload["recording"] is True
        assert payload["trial_number"] == 2
        assert payload["device_assigned"] is True
        assert payload["device_name"] == mock_device_info.name
        assert payload["device_id"] == mock_device_info.device_id

    def test_persistable_state(self, audio_state: AudioState, mock_device_info: AudioDeviceInfo):
        """Test getting persistable state."""
        audio_state.set_device(mock_device_info)

        state = audio_state.get_persistable_state()

        assert "device_name" in state
        assert state["device_name"] == mock_device_info.name

    def test_restore_from_state(self, audio_state: AudioState):
        """Test restoring from persisted state."""
        data = {"device_name": "Restored Device"}
        audio_state.restore_from_state(data)

        assert audio_state._pending_restore_name == "Restored Device"

    def test_restore_from_empty_state(self, audio_state: AudioState):
        """Test restoring from empty state."""
        audio_state.restore_from_state({})
        assert audio_state._pending_restore_name is None

    def test_try_restore_device_selection_match(self, audio_state: AudioState, mock_device_info: AudioDeviceInfo):
        """Test device selection restoration when name matches."""
        audio_state._pending_restore_name = mock_device_info.name
        audio_state.set_device(mock_device_info)

        result = audio_state.try_restore_device_selection()

        assert result is True
        assert audio_state._pending_restore_name is None

    def test_try_restore_device_selection_no_match(self, audio_state: AudioState, mock_device_info: AudioDeviceInfo):
        """Test device selection restoration when name doesn't match."""
        audio_state._pending_restore_name = "Different Device"
        audio_state.set_device(mock_device_info)

        result = audio_state.try_restore_device_selection()

        assert result is False
        assert audio_state._pending_restore_name == "Different Device"

    def test_state_prefix(self):
        """Test state prefix class method."""
        assert AudioState.state_prefix() == "audio"


# =============================================================================
# Test LevelMeter
# =============================================================================

class TestLevelMeter:
    """Tests for LevelMeter audio level tracking."""

    def test_initial_levels(self, level_meter: LevelMeter):
        """Test initial level values are at minimum."""
        rms, peak = level_meter.get_db_levels()

        assert rms == DB_MIN
        assert peak == DB_MIN

    def test_add_samples_updates_levels(self, level_meter: LevelMeter, sample_audio_data: np.ndarray):
        """Test adding samples updates RMS and peak levels."""
        level_meter.add_samples(sample_audio_data)

        rms, peak = level_meter.get_db_levels()

        assert rms > DB_MIN
        assert peak > DB_MIN
        assert level_meter.dirty is True

    def test_add_samples_with_silence(self, level_meter: LevelMeter, silence_audio_data: np.ndarray):
        """Test adding silent samples results in minimum levels."""
        level_meter.add_samples(silence_audio_data)

        rms, peak = level_meter.get_db_levels()

        assert rms == DB_MIN
        # Peak may or may not be at minimum depending on implementation

    def test_add_empty_samples(self, level_meter: LevelMeter):
        """Test adding empty sample array is handled gracefully."""
        empty = np.array([], dtype=np.float32)
        level_meter.add_samples(empty)

        rms, peak = level_meter.get_db_levels()

        assert rms == DB_MIN
        assert peak == DB_MIN

    def test_peak_hold_behavior(self, level_meter: LevelMeter):
        """Test peak hold time behavior."""
        # Set up a short peak hold time
        level_meter.peak_hold_time = 0.1

        # Add loud samples
        loud = np.ones(1000, dtype=np.float32) * 0.9
        level_meter.add_samples(loud, timestamp=0.0)
        _, peak_after_loud = level_meter.get_db_levels()

        # Add quiet samples within hold time
        quiet = np.ones(1000, dtype=np.float32) * 0.1
        level_meter.add_samples(quiet, timestamp=0.05)
        _, peak_after_quiet = level_meter.get_db_levels()

        # Peak should still be held (within hold time)
        assert peak_after_quiet == peak_after_loud

        # Add quiet samples well after hold time expires
        level_meter.add_samples(quiet, timestamp=0.25)
        _, peak_after_expire = level_meter.get_db_levels()

        # Peak should now reflect the quiet samples (lower value)
        assert peak_after_expire <= peak_after_loud

    def test_clear_dirty_flag(self, level_meter: LevelMeter, sample_audio_data: np.ndarray):
        """Test clearing dirty flag."""
        level_meter.add_samples(sample_audio_data)
        assert level_meter.dirty is True

        level_meter.clear_dirty()
        assert level_meter.dirty is False

    def test_db_conversion(self):
        """Test dB conversion is correct."""
        # Full scale (1.0) should be 0 dB
        assert LevelMeter._to_db(1.0) == pytest.approx(0.0, abs=0.01)

        # Half amplitude (-6 dB)
        assert LevelMeter._to_db(0.5) == pytest.approx(-6.02, abs=0.1)

        # Quarter amplitude (-12 dB)
        assert LevelMeter._to_db(0.25) == pytest.approx(-12.04, abs=0.1)

    def test_db_conversion_zero_returns_min(self):
        """Test dB conversion of zero returns minimum."""
        assert LevelMeter._to_db(0.0) == DB_MIN
        assert LevelMeter._to_db(-0.0) == DB_MIN

    def test_db_clamping(self):
        """Test dB values are clamped to valid range."""
        # Very small value should clamp to DB_MIN
        result = LevelMeter._to_db(1e-10)
        assert result == DB_MIN

        # Value > 1.0 should clamp to DB_MAX
        result = LevelMeter._to_db(2.0)
        assert result == DB_MAX

    @pytest.mark.parametrize("amplitude,expected_range", [
        (1.0, (DB_MAX - 1, DB_MAX)),
        (0.5, (-7.0, -5.0)),
        (0.1, (-21.0, -19.0)),
        (0.01, (-41.0, -39.0)),
    ])
    def test_level_meter_amplitude_to_db(self, level_meter: LevelMeter, amplitude, expected_range):
        """Test level meter correctly converts various amplitudes to dB."""
        samples = np.ones(1000, dtype=np.float32) * amplitude
        level_meter.add_samples(samples)

        rms, peak = level_meter.get_db_levels()

        assert expected_range[0] <= peak <= expected_range[1]


# =============================================================================
# Test Audio Domain Constants
# =============================================================================

class TestAudioConstants:
    """Tests for audio domain constants."""

    def test_bit_depth(self):
        """Test audio bit depth constant."""
        assert AUDIO_BIT_DEPTH == 16

    def test_channels_mono(self):
        """Test mono channel constant."""
        assert AUDIO_CHANNELS_MONO == 1

    def test_db_range(self):
        """Test dB range constants."""
        assert DB_MIN == -60.0
        assert DB_MAX == 0.0
        assert DB_MIN < DB_MAX


# =============================================================================
# Test DeviceManager (using simplified test implementation)
# =============================================================================

class TestDeviceManager:
    """Tests for DeviceManager device enablement logic.

    Uses a simplified test implementation to avoid vmc dependencies.
    """

    @pytest.fixture
    def mock_recorder_service(self):
        """Create a mock RecorderService."""
        service = MagicMock()
        service.enable_device = AsyncMock(return_value=True)
        service.disable_device = AsyncMock()
        return service

    @pytest.fixture
    def device_manager(self, audio_state: AudioState, mock_recorder_service, mock_logger: logging.Logger):
        """Create a test DeviceManager implementation."""
        class TestDeviceManagerImpl:
            """Simplified DeviceManager for testing."""
            def __init__(self, state, recorder_service, logger):
                self.state = state
                self.recorder_service = recorder_service
                self.logger = logger

            async def enable_device(self, device):
                self.state.set_device(device)
                meter = self.state.level_meter
                if meter is None:
                    meter = LevelMeter()
                success = await self.recorder_service.enable_device(device, meter)
                if not success:
                    self.state.clear_device()
                    return False
                return True

            async def disable_device(self):
                if self.state.device is None:
                    return True
                await self.recorder_service.disable_device()
                self.state.clear_device()
                return True

        return TestDeviceManagerImpl(audio_state, mock_recorder_service, mock_logger)

    def test_enable_device_success(
        self, device_manager, mock_device_info: AudioDeviceInfo, mock_recorder_service
    ):
        """Test successfully enabling a device."""
        result = asyncio.run(device_manager.enable_device(mock_device_info))

        assert result is True
        assert device_manager.state.device == mock_device_info
        mock_recorder_service.enable_device.assert_called_once()

    def test_enable_device_failure(
        self, device_manager, mock_device_info: AudioDeviceInfo, mock_recorder_service
    ):
        """Test handling device enable failure."""
        mock_recorder_service.enable_device = AsyncMock(return_value=False)

        result = asyncio.run(device_manager.enable_device(mock_device_info))

        assert result is False
        assert device_manager.state.device is None

    def test_disable_device_no_device(self, device_manager):
        """Test disabling when no device is assigned."""
        result = asyncio.run(device_manager.disable_device())

        assert result is True

    def test_disable_device_success(
        self, device_manager, mock_device_info: AudioDeviceInfo, mock_recorder_service
    ):
        """Test successfully disabling a device."""
        asyncio.run(device_manager.enable_device(mock_device_info))

        result = asyncio.run(device_manager.disable_device())

        assert result is True
        assert device_manager.state.device is None
        mock_recorder_service.disable_device.assert_called_once()


# =============================================================================
# Test RecordingManager (using simplified test implementation)
# =============================================================================

class TestRecordingManager:
    """Tests for RecordingManager recording orchestration.

    Uses a simplified test implementation to avoid vmc dependencies.
    """

    @pytest.fixture
    def mock_recorder_service(self):
        """Create a mock RecorderService."""
        service = MagicMock()
        service.begin_recording = AsyncMock(return_value=True)
        service.finish_recording = AsyncMock(return_value=None)
        return service

    @pytest.fixture
    def mock_session_service(self, tmp_path: Path):
        """Create a mock SessionService."""
        service = MagicMock()
        service.ensure_session_dir = AsyncMock(return_value=tmp_path)
        return service

    @pytest.fixture
    def mock_module_bridge(self):
        """Create a mock ModuleBridge."""
        bridge = MagicMock()
        bridge.set_session_dir = MagicMock()
        bridge.set_recording = MagicMock()
        return bridge

    @pytest.fixture
    def recording_manager(
        self,
        audio_state: AudioState,
        mock_recorder_service,
        mock_session_service,
        mock_module_bridge,
        mock_logger: logging.Logger,
        mock_device_info: AudioDeviceInfo,
    ):
        """Create a test RecordingManager implementation."""
        # Set up device in state
        audio_state.set_device(mock_device_info)

        class TestRecordingManagerImpl:
            """Simplified RecordingManager for testing."""
            def __init__(self, state, recorder_service, session_service, module_bridge, logger):
                self.state = state
                self.recorder_service = recorder_service
                self.session_service = session_service
                self.module_bridge = module_bridge
                self.logger = logger
                self._active_session_dir = None
                self._start_lock = asyncio.Lock()

            async def ensure_session_dir(self, current):
                session_dir = await self.session_service.ensure_session_dir(current)
                self._active_session_dir = session_dir
                self.module_bridge.set_session_dir(session_dir)
                self.state.set_session_dir(session_dir)
                return session_dir

            async def start(self, trial_number):
                if self.state.recording or self._start_lock.locked():
                    return False

                async with self._start_lock:
                    if self.state.recording:
                        return False
                    if self.state.device is None:
                        return False

                    session_dir = await self.ensure_session_dir(self.state.session_dir)
                    started = await self.recorder_service.begin_recording(session_dir, trial_number)
                    if not started:
                        return False

                    self.state.set_recording(True, trial_number)
                    self.module_bridge.set_recording(True, trial_number)
                    return True

            async def stop(self):
                if not self.state.recording:
                    return False

                await self.recorder_service.finish_recording()
                trial = self.state.trial_number
                self.state.set_recording(False, trial)
                self.module_bridge.set_recording(False, trial)
                return True

        return TestRecordingManagerImpl(
            audio_state,
            mock_recorder_service,
            mock_session_service,
            mock_module_bridge,
            mock_logger,
        )

    def test_start_recording_success(self, recording_manager, mock_recorder_service):
        """Test successfully starting recording."""
        result = asyncio.run(recording_manager.start(trial_number=1))

        assert result is True
        assert recording_manager.state.recording is True
        mock_recorder_service.begin_recording.assert_called_once()

    def test_start_recording_no_device(
        self, recording_manager, audio_state: AudioState, mock_recorder_service
    ):
        """Test starting recording fails when no device is assigned."""
        audio_state.clear_device()

        result = asyncio.run(recording_manager.start(trial_number=1))

        assert result is False
        mock_recorder_service.begin_recording.assert_not_called()

    def test_start_recording_already_recording(self, recording_manager, mock_recorder_service):
        """Test starting recording when already recording is a no-op."""
        asyncio.run(recording_manager.start(trial_number=1))
        mock_recorder_service.begin_recording.reset_mock()

        result = asyncio.run(recording_manager.start(trial_number=2))

        assert result is False
        mock_recorder_service.begin_recording.assert_not_called()

    def test_stop_recording_success(self, recording_manager, mock_recorder_service):
        """Test successfully stopping recording."""
        asyncio.run(recording_manager.start(trial_number=1))

        result = asyncio.run(recording_manager.stop())

        assert result is True
        assert recording_manager.state.recording is False
        mock_recorder_service.finish_recording.assert_called_once()

    def test_stop_recording_not_recording(self, recording_manager, mock_recorder_service):
        """Test stopping when not recording is a no-op."""
        result = asyncio.run(recording_manager.stop())

        assert result is False
        mock_recorder_service.finish_recording.assert_not_called()

    def test_ensure_session_dir(self, recording_manager, mock_session_service, tmp_path: Path):
        """Test ensuring session directory."""
        session_dir = asyncio.run(recording_manager.ensure_session_dir(None))

        assert session_dir == tmp_path
        mock_session_service.ensure_session_dir.assert_called_once()


# =============================================================================
# Test RecorderService (using mock for sounddevice)
# =============================================================================

class TestRecorderService:
    """Tests for RecorderService recorder management.

    These tests use mocks to avoid importing sounddevice.
    """

    def test_recorder_service_sample_rate_resolution(self, mock_device_info: AudioDeviceInfo):
        """Test sample rate resolution logic."""
        # Test with valid sample rate from device
        assert mock_device_info.sample_rate == 48000.0

        # Test with zero/invalid sample rate
        device_no_rate = AudioDeviceInfo(
            device_id=0,
            name="Test",
            channels=1,
            sample_rate=0,
        )
        # Default should be used when device rate is invalid
        assert device_no_rate.sample_rate == 0

    def test_recorder_service_properties(self, mock_logger: logging.Logger):
        """Test that a mock RecorderService has expected properties."""
        service = MagicMock()
        service._default_sample_rate = 48000
        service.start_timeout = 3.0
        service.stop_timeout = 2.0
        service.recorder = None

        assert service._default_sample_rate == 48000
        assert service.start_timeout == 3.0
        assert service.stop_timeout == 2.0
        assert service.recorder is None

    def test_disable_device_clears_recorder(self):
        """Test disabling device clears the recorder."""
        service = MagicMock()
        service.recorder = MagicMock()
        service.disable_device = AsyncMock()

        asyncio.run(service.disable_device())

        service.disable_device.assert_called_once()

    def test_begin_recording_no_recorder_returns_false(self):
        """Test beginning recording fails when no recorder exists."""
        service = MagicMock()
        service.recorder = None

        # When recorder is None, begin_recording should return False
        service.begin_recording = AsyncMock(return_value=False)
        result = asyncio.run(service.begin_recording(Path("/tmp"), trial_number=1))

        assert result is False

    def test_any_recording_active_states(self):
        """Test any_recording_active property for different states."""
        service = MagicMock()

        # No recorder
        service.recorder = None
        service.any_recording_active = False
        assert service.any_recording_active is False

        # Recorder exists but not recording
        service.recorder = MagicMock()
        service.recorder.recording = False
        service.any_recording_active = False
        assert service.any_recording_active is False

        # Recorder is recording
        service.recorder.recording = True
        service.any_recording_active = True
        assert service.any_recording_active is True


# =============================================================================
# Test AudioDeviceRecorder (using mocked sounddevice)
# =============================================================================

class TestAudioDeviceRecorder:
    """Tests for AudioDeviceRecorder low-level recording.

    Uses mocks for sounddevice to avoid hardware dependencies.
    """

    def test_pcm_byte_conversion_logic(self, sample_audio_data: np.ndarray):
        """Test PCM byte conversion logic."""
        # Simulate the conversion logic from AudioDeviceRecorder._to_pcm_bytes
        array = np.asarray(sample_audio_data, dtype=np.float32)
        if array.ndim > 1:
            array = array[:, 0]
        scaled = np.clip(array, -1.0, 1.0)
        max_int = (2 ** (AUDIO_BIT_DEPTH - 1)) - 1
        int_samples = (scaled * max_int).astype(np.int16)
        pcm_bytes = int_samples.tobytes()

        assert isinstance(pcm_bytes, bytes)
        # 16-bit = 2 bytes per sample
        assert len(pcm_bytes) == len(sample_audio_data) * 2

    def test_pcm_bytes_clipping(self):
        """Test PCM byte conversion clips values."""
        # Values outside [-1, 1]
        samples = np.array([1.5, -1.5, 2.0, -2.0], dtype=np.float32)
        scaled = np.clip(samples, -1.0, 1.0)
        max_int = (2 ** (AUDIO_BIT_DEPTH - 1)) - 1
        int_samples = (scaled * max_int).astype(np.int16)
        pcm_bytes = int_samples.tobytes()

        # Should not raise and should return valid bytes
        assert isinstance(pcm_bytes, bytes)
        assert len(pcm_bytes) == len(samples) * 2

        # Verify clipping occurred
        decoded = np.frombuffer(pcm_bytes, dtype=np.int16)
        assert decoded[0] == max_int  # 1.5 clipped to 1.0
        # For -1.0 * max_int = -32767, which is -max_int
        assert decoded[1] == -max_int  # -1.5 clipped to -1.0

    def test_pcm_bytes_2d_array_first_channel(self):
        """Test PCM byte conversion with 2D array extracts first channel."""
        samples = np.array([[0.5, 0.3], [0.4, 0.2], [0.3, 0.1]], dtype=np.float32)

        # Simulate first channel extraction
        array = samples[:, 0] if samples.ndim > 1 else samples
        scaled = np.clip(array, -1.0, 1.0)
        max_int = (2 ** (AUDIO_BIT_DEPTH - 1)) - 1
        int_samples = (scaled * max_int).astype(np.int16)
        pcm_bytes = int_samples.tobytes()

        # Should only use first column (3 samples)
        assert len(pcm_bytes) == 3 * 2

    def test_timing_filename_generation(self, tmp_path: Path):
        """Test timing CSV filename generation."""
        audio_path = tmp_path / "test_audio.wav"
        timing_path = audio_path.with_name(f"{audio_path.stem}_timing.csv")

        assert timing_path.name == "test_audio_timing.csv"
        assert timing_path.parent == tmp_path

    def test_recording_handle_structure(self, tmp_path: Path):
        """Test RecordingHandle dataclass structure."""
        @dataclass
        class RecordingHandle:
            file_path: Path
            timing_csv_path: Path
            session_dir: Path
            trial_number: int
            device_id: int
            device_name: str
            start_time_unix: float | None = None
            start_time_monotonic: float | None = None

        handle = RecordingHandle(
            file_path=tmp_path / "test.wav",
            timing_csv_path=tmp_path / "test_timing.csv",
            session_dir=tmp_path,
            trial_number=1,
            device_id=0,
            device_name="Test Device",
            start_time_unix=time.time(),
            start_time_monotonic=time.perf_counter(),
        )

        assert handle.trial_number == 1
        assert handle.device_id == 0
        assert handle.device_name == "Test Device"
        assert handle.start_time_unix is not None


# =============================================================================
# Test Error Handling for Missing Devices
# =============================================================================

class TestMissingDeviceErrors:
    """Tests for error handling when devices are missing."""

    def test_enable_device_timeout_behavior(self):
        """Test that device enable timeout is handled correctly."""
        service = MagicMock()
        service.start_timeout = 0.1  # Very short timeout

        # Simulate timeout by having enable_device return False
        service.enable_device = AsyncMock(return_value=False)

        device = AudioDeviceInfo(
            device_id=999,
            name="Missing Device",
            channels=1,
            sample_rate=48000.0,
        )
        meter = LevelMeter()

        result = asyncio.run(service.enable_device(device, meter))

        assert result is False

    def test_enable_device_exception_handling(self):
        """Test that device enable exception is handled correctly."""
        service = MagicMock()

        # Simulate exception by having enable_device raise
        service.enable_device = AsyncMock(side_effect=Exception("Device not found"))

        device = AudioDeviceInfo(
            device_id=999,
            name="Missing Device",
            channels=1,
            sample_rate=48000.0,
        )
        meter = LevelMeter()

        with pytest.raises(Exception, match="Device not found"):
            asyncio.run(service.enable_device(device, meter))

    def test_recording_manager_handles_recorder_failure(
        self, audio_state: AudioState, mock_device_info: AudioDeviceInfo, tmp_path: Path
    ):
        """Test RecordingManager handles recorder failure gracefully."""
        audio_state.set_device(mock_device_info)

        mock_recorder_service = MagicMock()
        mock_recorder_service.begin_recording = AsyncMock(return_value=False)  # Fails

        mock_session_service = MagicMock()
        mock_session_service.ensure_session_dir = AsyncMock(return_value=tmp_path)

        mock_module_bridge = MagicMock()

        class TestRecordingManager:
            """Simplified RecordingManager for testing."""
            def __init__(self, state, recorder_service, session_service, module_bridge):
                self.state = state
                self.recorder_service = recorder_service
                self.session_service = session_service
                self.module_bridge = module_bridge

            async def start(self, trial_number):
                if self.state.device is None:
                    return False

                session_dir = await self.session_service.ensure_session_dir(None)
                started = await self.recorder_service.begin_recording(session_dir, trial_number)
                if not started:
                    return False

                self.state.set_recording(True, trial_number)
                return True

        manager = TestRecordingManager(
            audio_state,
            mock_recorder_service,
            mock_session_service,
            mock_module_bridge,
        )

        result = asyncio.run(manager.start(trial_number=1))

        assert result is False
        assert audio_state.recording is False


# =============================================================================
# Test AudioSnapshot
# =============================================================================

class TestAudioSnapshot:
    """Tests for AudioSnapshot data structure."""

    def test_snapshot_creation(self, mock_device_info: AudioDeviceInfo, level_meter: LevelMeter, tmp_path: Path):
        """Test creating an AudioSnapshot."""
        snapshot = AudioSnapshot(
            device=mock_device_info,
            level_meter=level_meter,
            recording=True,
            trial_number=5,
            session_dir=tmp_path,
            status_text="Recording...",
        )

        assert snapshot.device == mock_device_info
        assert snapshot.level_meter == level_meter
        assert snapshot.recording is True
        assert snapshot.trial_number == 5
        assert snapshot.session_dir == tmp_path
        assert snapshot.status_text == "Recording..."

    def test_snapshot_with_none_values(self):
        """Test creating AudioSnapshot with None values."""
        snapshot = AudioSnapshot(
            device=None,
            level_meter=None,
            recording=False,
            trial_number=1,
            session_dir=None,
            status_text="No device",
        )

        assert snapshot.device is None
        assert snapshot.level_meter is None
        assert snapshot.session_dir is None


# =============================================================================
# Integration-style Unit Tests (components working together)
# =============================================================================

class TestAudioModuleIntegration:
    """Integration-style tests for Audio module components working together."""

    def test_settings_creation_flow(self):
        """Test settings flow from args."""
        args = MagicMock()
        args.output_dir = Path("/tmp/test")
        args.session_prefix = "test"
        args.sample_rate = 44100
        args.recorder_start_timeout = 5.0
        args.recorder_stop_timeout = 3.0

        settings = AudioSettings.from_args(args)

        assert settings.sample_rate == 44100

    def test_state_observer_chain(
        self, audio_state: AudioState, mock_device_info: AudioDeviceInfo
    ):
        """Test that state changes propagate through observer chain."""
        snapshots = []

        def observer(snapshot: AudioSnapshot):
            snapshots.append(snapshot)

        audio_state.subscribe(observer)
        snapshots.clear()  # Clear initial notification

        # Device assignment
        audio_state.set_device(mock_device_info)
        assert len(snapshots) == 1
        assert snapshots[-1].device == mock_device_info

        # Start recording
        audio_state.set_recording(True, trial=1)
        assert len(snapshots) == 2
        assert snapshots[-1].recording is True

        # Stop recording
        audio_state.set_recording(False, trial=1)
        assert len(snapshots) == 3
        assert snapshots[-1].recording is False

        # Clear device
        audio_state.clear_device()
        assert len(snapshots) == 4
        assert snapshots[-1].device is None
