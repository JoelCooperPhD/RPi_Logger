"""Comprehensive unit tests for EyeTracker (Pupil Labs Neon) module.

Tests cover:
1. Configuration loading and validation
2. Device connection (mocked network/API)
3. Gaze data stream parsing
4. IMU data stream parsing
5. Events data handling
6. Multiple CSV output streams
7. Calibration commands
8. Error handling

All tests are isolated and use mocks for network connections.

Note: Async tests use asyncio.run() wrapper to work without pytest-asyncio.
If pytest-asyncio is available, the @pytest.mark.asyncio decorator can be used.
"""

from __future__ import annotations

import asyncio
import csv
import io
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest


def run_async(coro):
    """Run async coroutine synchronously for testing."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# =============================================================================
# Test Data Fixtures
# =============================================================================

@pytest.fixture
def mock_gaze_data():
    """Create mock gaze data for testing."""
    from tests.infrastructure.mocks.network_mocks import MockGazeData

    timestamp = time.time()
    return MockGazeData(
        timestamp_unix_seconds=timestamp,
        timestamp_unix_ns=int(timestamp * 1e9),
        worn=True,
        x=0.5,
        y=0.5,
        pupil_diameter_left=4.0,
        pupil_diameter_right=4.2,
    )


@pytest.fixture
def mock_imu_data():
    """Create mock IMU data for testing."""
    from tests.infrastructure.mocks.network_mocks import MockIMUData

    timestamp = time.time()
    return MockIMUData(
        timestamp_unix_seconds=timestamp,
        timestamp_unix_ns=int(timestamp * 1e9),
        gyro_data={'x': 0.01, 'y': -0.02, 'z': 0.005},
        accel_data={'x': 0.1, 'y': -0.05, 'z': -9.81},
        quaternion={'w': 1.0, 'x': 0.0, 'y': 0.0, 'z': 0.0},
        temperature=25.5,
    )


@pytest.fixture
def mock_eye_event():
    """Create mock eye event for testing."""
    from tests.infrastructure.mocks.network_mocks import MockEyeEvent

    timestamp = time.time()
    return MockEyeEvent(
        timestamp_unix_seconds=timestamp,
        timestamp_unix_ns=int(timestamp * 1e9),
        type="fixation",
        event_type="fixation",
        confidence=0.95,
        duration=0.25,
        start_time_ns=int((timestamp - 0.25) * 1e9),
        end_time_ns=int(timestamp * 1e9),
        start_gaze_x=0.48,
        start_gaze_y=0.52,
        end_gaze_x=0.50,
        end_gaze_y=0.50,
        mean_gaze_x=0.49,
        mean_gaze_y=0.51,
    )


@pytest.fixture
def mock_pupil_api():
    """Create mock Pupil Labs API for testing."""
    from tests.infrastructure.mocks.network_mocks import MockPupilNeonAPI, MockDeviceInfo

    device = MockDeviceInfo(
        serial="TEST001",
        name="Test Neon",
        ip="192.168.1.100",
        port=8080,
    )
    return MockPupilNeonAPI(device=device)


@pytest.fixture
def tracker_config():
    """Create a TrackerConfig for testing."""
    from rpi_logger.modules.EyeTracker.tracker_core.config.tracker_config import TrackerConfig
    return TrackerConfig(
        fps=10.0,
        resolution=(800, 600),
        output_dir="test_recordings",
        preview_fps=10.0,
        eyes_fps=30.0,
    )


@pytest.fixture
def temp_recording_dir(tmp_path):
    """Create a temporary recording directory."""
    recording_dir = tmp_path / "recordings"
    recording_dir.mkdir()
    return recording_dir


# =============================================================================
# Configuration Tests
# =============================================================================

class TestEyeTrackerConfig:
    """Tests for EyeTrackerConfig loading and validation."""

    def test_default_config_values(self):
        """Test that default config has expected values."""
        from rpi_logger.modules.EyeTracker.config import EyeTrackerConfig

        config = EyeTrackerConfig()

        assert config.display_name == "EyeTracker-Neon"
        assert config.enabled is True
        assert config.target_fps == 10.0
        assert config.eyes_fps == 30.0
        assert config.resolution_width == 1280
        assert config.resolution_height == 720
        assert config.discovery_timeout == 5.0

    def test_config_resolution_property(self):
        """Test resolution property returns tuple."""
        from rpi_logger.modules.EyeTracker.config import EyeTrackerConfig

        config = EyeTrackerConfig(resolution_width=1920, resolution_height=1080)

        assert config.resolution == (1920, 1080)

    def test_config_to_dict(self):
        """Test config serialization to dictionary."""
        from rpi_logger.modules.EyeTracker.config import EyeTrackerConfig

        config = EyeTrackerConfig()
        config_dict = config.to_dict()

        assert isinstance(config_dict, dict)
        assert "display_name" in config_dict
        assert "target_fps" in config_dict
        assert config_dict["display_name"] == "EyeTracker-Neon"

    def test_config_overlay_color(self):
        """Test overlay color configuration."""
        from rpi_logger.modules.EyeTracker.config import EyeTrackerConfig

        config = EyeTrackerConfig()

        assert config.overlay_color == (255, 255, 255)
        assert isinstance(config.overlay_color, tuple)
        assert len(config.overlay_color) == 3

    def test_config_gaze_color(self):
        """Test gaze color configuration."""
        from rpi_logger.modules.EyeTracker.config import EyeTrackerConfig

        config = EyeTrackerConfig()

        assert config.gaze_color_worn == (255, 0, 0)

    def test_config_stream_settings(self):
        """Test stream enable settings."""
        from rpi_logger.modules.EyeTracker.config import EyeTrackerConfig

        config = EyeTrackerConfig()

        assert config.stream_video_enabled is True
        assert config.stream_gaze_enabled is True
        assert config.stream_eyes_enabled is True
        assert config.stream_imu_enabled is True
        assert config.stream_events_enabled is True


class TestTrackerConfig:
    """Tests for TrackerConfig (internal config)."""

    def test_default_values(self, tracker_config):
        """Test default TrackerConfig values."""
        assert tracker_config.fps == 10.0
        assert tracker_config.resolution == (800, 600)
        assert tracker_config.preview_fps == 10.0

    def test_preview_height_calculation(self):
        """Test that preview height is calculated from aspect ratio."""
        from rpi_logger.modules.EyeTracker.tracker_core.config.tracker_config import TrackerConfig

        config = TrackerConfig(
            resolution=(1600, 1200),
            preview_width=400,
        )

        # 1200/1600 = 0.75 aspect ratio, so 400 * 0.75 = 300
        assert config.preview_height == 300

    def test_recording_skip_factor(self, tracker_config):
        """Test recording skip factor calculation."""
        # With 10 fps and 30 fps source, should skip every 3rd frame
        assert tracker_config.recording_skip_factor() == 3

    def test_preview_skip_factor(self, tracker_config):
        """Test preview skip factor calculation."""
        assert tracker_config.preview_skip_factor() == 3

    def test_eyes_recording_skip_factor(self, tracker_config):
        """Test eyes camera skip factor calculation."""
        # With 30 fps eyes recording and 200 fps source
        factor = tracker_config.eyes_recording_skip_factor()
        assert factor == 7  # round(200/30) = 7

    def test_skip_factor_minimum(self):
        """Test that skip factor is at least 1."""
        from rpi_logger.modules.EyeTracker.tracker_core.config.tracker_config import TrackerConfig

        config = TrackerConfig(fps=60.0)  # Higher than source
        assert config.recording_skip_factor() >= 1


# =============================================================================
# Device Manager Tests
# =============================================================================

class TestDeviceManager:
    """Tests for DeviceManager connection handling."""

    def test_initial_state(self):
        """Test DeviceManager initial state."""
        with patch.dict('sys.modules', {'pupil_labs.realtime_api.device': MagicMock()}):
            from rpi_logger.modules.EyeTracker.tracker_core.device_manager import DeviceManager

            manager = DeviceManager()

            assert manager.device is None
            assert manager.device_ip is None
            assert manager.device_port is None
            assert manager.is_connected is False

    def test_is_connected_false_without_device(self):
        """Test is_connected returns False without device."""
        with patch.dict('sys.modules', {'pupil_labs.realtime_api.device': MagicMock()}):
            from rpi_logger.modules.EyeTracker.tracker_core.device_manager import DeviceManager

            manager = DeviceManager()
            manager.device = MagicMock()
            manager.device_ip = None  # No IP

            assert manager.is_connected is False

    def test_is_connected_true_with_device_and_ip(self):
        """Test is_connected returns True with device and IP."""
        with patch.dict('sys.modules', {'pupil_labs.realtime_api.device': MagicMock()}):
            from rpi_logger.modules.EyeTracker.tracker_core.device_manager import DeviceManager

            manager = DeviceManager()
            manager.device = MagicMock()
            manager.device_ip = "192.168.1.100"

            assert manager.is_connected is True

    def test_get_stream_urls_without_device_raises(self):
        """Test get_stream_urls raises without device."""
        with patch.dict('sys.modules', {'pupil_labs.realtime_api.device': MagicMock()}):
            from rpi_logger.modules.EyeTracker.tracker_core.device_manager import DeviceManager

            manager = DeviceManager()

            with pytest.raises(RuntimeError, match="No device connected"):
                manager.get_stream_urls()

    def test_default_stream_urls(self):
        """Test default stream URL generation."""
        with patch.dict('sys.modules', {'pupil_labs.realtime_api.device': MagicMock()}):
            from rpi_logger.modules.EyeTracker.tracker_core.device_manager import DeviceManager

            manager = DeviceManager()
            manager.device = MagicMock()
            manager.device_ip = "192.168.1.100"

            urls = manager.get_stream_urls()

            assert "video" in urls
            assert "gaze" in urls
            assert "192.168.1.100" in urls["video"]

    def test_audio_stream_param(self):
        """Test audio stream parameter configuration."""
        with patch.dict('sys.modules', {'pupil_labs.realtime_api.device': MagicMock()}):
            from rpi_logger.modules.EyeTracker.tracker_core.device_manager import DeviceManager

            manager = DeviceManager()
            manager.audio_stream_param = "audio=custom"
            manager.device = MagicMock()
            manager.device_ip = "192.168.1.100"

            urls = manager.get_stream_urls()

            assert "audio" in urls
            assert "audio=custom" in urls["audio"]

    def test_cleanup(self):
        """Test device cleanup."""
        async def _test():
            with patch.dict('sys.modules', {'pupil_labs.realtime_api.device': MagicMock()}):
                from rpi_logger.modules.EyeTracker.tracker_core.device_manager import DeviceManager

                manager = DeviceManager()
                mock_device = AsyncMock()
                manager.device = mock_device
                manager.device_ip = "192.168.1.100"

                await manager.cleanup()

                mock_device.close.assert_called_once()
                assert manager.device is None
                assert manager.device_ip is None

        run_async(_test())


# =============================================================================
# Stream Handler Tests
# =============================================================================

class TestStreamHandler:
    """Tests for StreamHandler data stream management."""

    def test_initial_state(self):
        """Test StreamHandler initial state."""
        from rpi_logger.modules.EyeTracker.tracker_core.stream_handler import StreamHandler

        handler = StreamHandler()

        assert handler.running is False
        assert handler.last_frame is None
        assert handler.last_gaze is None
        assert handler.last_imu is None
        assert handler.camera_frames == 0

    def test_running_flag_update(self):
        """Test running flag updates based on task states."""
        from rpi_logger.modules.EyeTracker.tracker_core.stream_handler import StreamHandler

        handler = StreamHandler()
        handler._video_task_active = True
        handler._update_running_flag()

        assert handler.running is True

        handler._video_task_active = False
        handler._update_running_flag()

        assert handler.running is False

    def test_get_latest_methods(self):
        """Test get_latest methods return stored values."""
        from rpi_logger.modules.EyeTracker.tracker_core.stream_handler import StreamHandler

        handler = StreamHandler()
        handler.last_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        handler.last_gaze = {"x": 0.5, "y": 0.5}
        handler.last_imu = {"accel": [0, 0, -9.81]}

        assert handler.get_latest_frame() is not None
        assert handler.get_latest_gaze() == {"x": 0.5, "y": 0.5}
        assert handler.get_latest_imu() == {"accel": [0, 0, -9.81]}

    def test_camera_fps_tracker(self):
        """Test camera FPS tracking."""
        from rpi_logger.modules.EyeTracker.tracker_core.stream_handler import StreamHandler

        handler = StreamHandler()

        # Add some frames
        for _ in range(5):
            handler.camera_fps_tracker.add_frame()

        fps = handler.get_camera_fps()
        assert fps >= 0  # FPS might be 0 with fast successive calls

    def test_set_listeners(self):
        """Test setting IMU and event listeners."""
        from rpi_logger.modules.EyeTracker.tracker_core.stream_handler import StreamHandler

        handler = StreamHandler()

        def imu_callback(data):
            pass

        def event_callback(data):
            pass

        handler.set_imu_listener(imu_callback)
        handler.set_event_listener(event_callback)

        assert handler.imu_listener is imu_callback
        assert handler.event_listener is event_callback

    def test_dropped_frames_property(self):
        """Test dropped frames counter."""
        from rpi_logger.modules.EyeTracker.tracker_core.stream_handler import StreamHandler

        handler = StreamHandler()
        handler._dropped_frames = 5

        assert handler.dropped_frames == 5

    def test_drain_queues(self):
        """Test queue draining."""
        from rpi_logger.modules.EyeTracker.tracker_core.stream_handler import StreamHandler

        handler = StreamHandler()

        # Add items to a queue
        for i in range(3):
            handler._gaze_queue.put_nowait({"gaze": i})

        handler._drain_queues()

        assert handler._gaze_queue.empty()

    def test_stop_streaming(self):
        """Test stop_streaming clears state."""
        async def _test():
            from rpi_logger.modules.EyeTracker.tracker_core.stream_handler import StreamHandler

            handler = StreamHandler()
            handler._video_task_active = True
            handler._gaze_task_active = True
            handler.running = True

            await handler.stop_streaming()

            assert handler.running is False
            assert handler._video_task_active is False
            assert handler._gaze_task_active is False

        run_async(_test())


class TestFramePacket:
    """Tests for FramePacket data structure."""

    def test_frame_packet_creation(self):
        """Test FramePacket creation."""
        from rpi_logger.modules.EyeTracker.tracker_core.stream_handler import FramePacket

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        packet = FramePacket(
            image=frame,
            received_monotonic=time.perf_counter(),
            timestamp_unix_seconds=time.time(),
            camera_frame_index=1,
        )

        assert packet.image is frame
        assert packet.camera_frame_index == 1
        assert packet.wait_ms == 0.0


class TestEyesFramePacket:
    """Tests for EyesFramePacket data structure."""

    def test_eyes_frame_packet_creation(self):
        """Test EyesFramePacket creation."""
        from rpi_logger.modules.EyeTracker.tracker_core.stream_handler import EyesFramePacket

        frame = np.zeros((192, 384, 3), dtype=np.uint8)
        timestamp = time.time()
        packet = EyesFramePacket(
            image=frame,
            received_monotonic=time.perf_counter(),
            timestamp_unix_seconds=timestamp,
            timestamp_unix_ns=int(timestamp * 1e9),
            frame_index=1,
        )

        assert packet.image.shape == (192, 384, 3)
        assert packet.frame_index == 1


# =============================================================================
# Gaze Data Tests
# =============================================================================

class TestGazeDataParsing:
    """Tests for gaze data parsing and handling."""

    def test_mock_gaze_data_structure(self, mock_gaze_data):
        """Test mock gaze data has expected attributes."""
        assert hasattr(mock_gaze_data, "timestamp_unix_seconds")
        assert hasattr(mock_gaze_data, "worn")
        assert hasattr(mock_gaze_data, "x")
        assert hasattr(mock_gaze_data, "y")
        assert hasattr(mock_gaze_data, "pupil_diameter_left")
        assert hasattr(mock_gaze_data, "pupil_diameter_right")

    def test_gaze_coordinates_range(self, mock_gaze_data):
        """Test gaze coordinates are in valid range."""
        assert 0.0 <= mock_gaze_data.x <= 1.0
        assert 0.0 <= mock_gaze_data.y <= 1.0

    def test_gaze_per_eye_coordinates(self, mock_gaze_data):
        """Test per-eye coordinate properties."""
        left = mock_gaze_data.left
        right = mock_gaze_data.right

        assert hasattr(left, 'x')
        assert hasattr(left, 'y')
        assert hasattr(right, 'x')
        assert hasattr(right, 'y')

    def test_gaze_worn_flag(self, mock_gaze_data):
        """Test worn flag boolean."""
        assert isinstance(mock_gaze_data.worn, bool)
        assert mock_gaze_data.worn is True

    def test_pupil_diameter_values(self, mock_gaze_data):
        """Test pupil diameter values are reasonable."""
        assert 2.0 <= mock_gaze_data.pupil_diameter_left <= 8.0
        assert 2.0 <= mock_gaze_data.pupil_diameter_right <= 8.0


# =============================================================================
# IMU Data Tests
# =============================================================================

class TestIMUDataParsing:
    """Tests for IMU data parsing and handling."""

    def test_mock_imu_data_structure(self, mock_imu_data):
        """Test mock IMU data has expected attributes."""
        assert hasattr(mock_imu_data, "timestamp_unix_seconds")
        assert hasattr(mock_imu_data, "gyro_data")
        assert hasattr(mock_imu_data, "accel_data")
        assert hasattr(mock_imu_data, "quaternion")
        assert hasattr(mock_imu_data, "temperature")

    def test_gyro_data_format(self, mock_imu_data):
        """Test gyro data is dictionary with x, y, z."""
        gyro = mock_imu_data.gyro_data
        assert isinstance(gyro, dict)
        assert 'x' in gyro
        assert 'y' in gyro
        assert 'z' in gyro

    def test_accel_data_format(self, mock_imu_data):
        """Test accel data is dictionary with x, y, z."""
        accel = mock_imu_data.accel_data
        assert isinstance(accel, dict)
        assert 'x' in accel
        assert 'y' in accel
        assert 'z' in accel

    def test_quaternion_format(self, mock_imu_data):
        """Test quaternion has w, x, y, z components."""
        quat = mock_imu_data.quaternion
        assert isinstance(quat, dict)
        assert 'w' in quat
        assert 'x' in quat
        assert 'y' in quat
        assert 'z' in quat

    def test_gravity_in_accel(self, mock_imu_data):
        """Test accelerometer shows gravity in z-axis."""
        accel = mock_imu_data.accel_data
        # Should be approximately -9.81 m/s^2
        assert accel['z'] == pytest.approx(-9.81, abs=0.5)


# =============================================================================
# Events Data Tests
# =============================================================================

class TestEventsDataHandling:
    """Tests for eye events data handling."""

    def test_mock_event_structure(self, mock_eye_event):
        """Test mock eye event has expected attributes."""
        assert hasattr(mock_eye_event, "timestamp_unix_seconds")
        assert hasattr(mock_eye_event, "type")
        assert hasattr(mock_eye_event, "event_type")
        assert hasattr(mock_eye_event, "confidence")
        assert hasattr(mock_eye_event, "duration")

    def test_event_type_values(self, mock_eye_event):
        """Test event type is valid."""
        valid_types = ["fixation", "saccade", "blink"]
        assert mock_eye_event.type in valid_types

    def test_event_confidence_range(self, mock_eye_event):
        """Test confidence is in valid range."""
        assert 0.0 <= mock_eye_event.confidence <= 1.0

    def test_event_timing(self, mock_eye_event):
        """Test event timing fields."""
        assert mock_eye_event.start_time_ns < mock_eye_event.end_time_ns
        assert mock_eye_event.duration > 0

    def test_event_gaze_coordinates(self, mock_eye_event):
        """Test event gaze coordinates are present."""
        assert hasattr(mock_eye_event, "start_gaze_x")
        assert hasattr(mock_eye_event, "start_gaze_y")
        assert hasattr(mock_eye_event, "end_gaze_x")
        assert hasattr(mock_eye_event, "end_gaze_y")
        assert hasattr(mock_eye_event, "mean_gaze_x")
        assert hasattr(mock_eye_event, "mean_gaze_y")


# =============================================================================
# Recording Manager Tests
# =============================================================================

class TestRecordingManager:
    """Tests for RecordingManager CSV output handling."""

    def test_initial_state(self, tracker_config, temp_recording_dir):
        """Test RecordingManager initial state."""
        # Patch video encoder to avoid ffmpeg dependency
        with patch('rpi_logger.modules.EyeTracker.tracker_core.recording.manager.VideoEncoder'):
            from rpi_logger.modules.EyeTracker.tracker_core.recording.manager import RecordingManager

            tracker_config.output_dir = str(temp_recording_dir)
            manager = RecordingManager(tracker_config)

            assert manager.is_recording is False
            assert manager.recorded_frame_count == 0
            assert manager.world_video_filename is None

    def test_start_experiment(self, tracker_config, temp_recording_dir):
        """Test starting a new experiment."""
        with patch('rpi_logger.modules.EyeTracker.tracker_core.recording.manager.VideoEncoder'):
            from rpi_logger.modules.EyeTracker.tracker_core.recording.manager import RecordingManager

            tracker_config.output_dir = str(temp_recording_dir)
            manager = RecordingManager(tracker_config)

            experiment_dir = manager.start_experiment("test_experiment")

            assert experiment_dir.exists()
            assert "test_experiment" in str(experiment_dir)
            assert manager.current_experiment_dir is not None

    def test_start_experiment_sanitizes_label(self, tracker_config, temp_recording_dir):
        """Test experiment label sanitization."""
        with patch('rpi_logger.modules.EyeTracker.tracker_core.recording.manager.VideoEncoder'):
            from rpi_logger.modules.EyeTracker.tracker_core.recording.manager import RecordingManager

            tracker_config.output_dir = str(temp_recording_dir)
            manager = RecordingManager(tracker_config)

            experiment_dir = manager.start_experiment("Test Label with Spaces!")

            # Should convert spaces and special chars
            assert "test-label-with-spaces" in str(experiment_dir).lower()

    def test_get_stats(self, tracker_config, temp_recording_dir):
        """Test get_stats returns expected structure."""
        with patch('rpi_logger.modules.EyeTracker.tracker_core.recording.manager.VideoEncoder'):
            from rpi_logger.modules.EyeTracker.tracker_core.recording.manager import RecordingManager

            tracker_config.output_dir = str(temp_recording_dir)
            manager = RecordingManager(tracker_config)

            stats = manager.get_stats()

            assert "is_recording" in stats
            assert "world_frames_written" in stats
            assert "gaze_samples_written" in stats
            assert "imu_samples_written" in stats
            assert "event_samples_written" in stats

    def test_fmt_helper(self, tracker_config, temp_recording_dir):
        """Test _fmt helper for CSV formatting."""
        with patch('rpi_logger.modules.EyeTracker.tracker_core.recording.manager.VideoEncoder'):
            from rpi_logger.modules.EyeTracker.tracker_core.recording.manager import RecordingManager

            tracker_config.output_dir = str(temp_recording_dir)
            manager = RecordingManager(tracker_config)

            assert manager._fmt(None) == ""
            assert manager._fmt(42) == "42"
            assert manager._fmt(3.14159) == "3.14159"
            assert manager._fmt("text") == "text"

    def test_extract_xyz(self, tracker_config, temp_recording_dir):
        """Test _extract_xyz helper."""
        with patch('rpi_logger.modules.EyeTracker.tracker_core.recording.manager.VideoEncoder'):
            from rpi_logger.modules.EyeTracker.tracker_core.recording.manager import RecordingManager

            tracker_config.output_dir = str(temp_recording_dir)
            manager = RecordingManager(tracker_config)

            # Test with dict
            result = manager._extract_xyz({'x': 1.0, 'y': 2.0, 'z': 3.0})
            assert result == ['1', '2', '3']

            # Test with None
            result = manager._extract_xyz(None)
            assert result == ['', '', '']

    def test_extract_quat(self, tracker_config, temp_recording_dir):
        """Test _extract_quat helper."""
        with patch('rpi_logger.modules.EyeTracker.tracker_core.recording.manager.VideoEncoder'):
            from rpi_logger.modules.EyeTracker.tracker_core.recording.manager import RecordingManager

            tracker_config.output_dir = str(temp_recording_dir)
            manager = RecordingManager(tracker_config)

            # Test with dict
            result = manager._extract_quat({'w': 1.0, 'x': 0.0, 'y': 0.0, 'z': 0.0})
            assert result == ['1', '0', '0', '0']

            # Test with None
            result = manager._extract_quat(None)
            assert result == ['', '', '', '']


class TestRecordingManagerCSVOutput:
    """Tests for CSV output formatting."""

    def test_gaze_csv_line_composition(self, tracker_config, temp_recording_dir, mock_gaze_data):
        """Test gaze CSV line composition."""
        with patch('rpi_logger.modules.EyeTracker.tracker_core.recording.manager.VideoEncoder'):
            from rpi_logger.modules.EyeTracker.tracker_core.recording.manager import RecordingManager

            tracker_config.output_dir = str(temp_recording_dir)
            manager = RecordingManager(tracker_config)
            manager._current_trial_number = 1

            line = manager._compose_gaze_line(mock_gaze_data, time.time(), time.perf_counter())

            # Should be comma-separated values
            assert "," in line
            fields = line.strip().split(",")

            # Should have all expected fields
            assert len(fields) > 10

    def test_csv_line_helper(self, tracker_config, temp_recording_dir):
        """Test _csv_line helper."""
        with patch('rpi_logger.modules.EyeTracker.tracker_core.recording.manager.VideoEncoder'):
            from rpi_logger.modules.EyeTracker.tracker_core.recording.manager import RecordingManager

            tracker_config.output_dir = str(temp_recording_dir)
            manager = RecordingManager(tracker_config)

            fields = ["field1", "field2", "field with, comma"]
            line = manager._csv_line(fields)

            # Should properly escape comma in field
            assert '"field with, comma"' in line
            assert line.endswith("\n")


# =============================================================================
# AsyncCSVWriter Tests
# =============================================================================

class TestAsyncCSVWriter:
    """Tests for AsyncCSVWriter."""

    def test_start_creates_file(self, tmp_path):
        """Test that start creates the file."""
        async def _test():
            from rpi_logger.modules.EyeTracker.tracker_core.recording.async_csv_writer import AsyncCSVWriter

            csv_path = tmp_path / "test.csv"
            writer = AsyncCSVWriter(header="col1,col2,col3")

            await writer.start(csv_path)
            assert csv_path.exists()
            await writer.stop()

        run_async(_test())

    def test_writes_header(self, tmp_path):
        """Test that header is written."""
        async def _test():
            from rpi_logger.modules.EyeTracker.tracker_core.recording.async_csv_writer import AsyncCSVWriter

            csv_path = tmp_path / "test.csv"
            writer = AsyncCSVWriter(header="col1,col2,col3")

            await writer.start(csv_path)
            await writer.stop()

            content = csv_path.read_text()
            assert content.startswith("col1,col2,col3")

        run_async(_test())

    def test_enqueue_lines(self, tmp_path):
        """Test enqueueing lines for writing."""
        async def _test():
            from rpi_logger.modules.EyeTracker.tracker_core.recording.async_csv_writer import AsyncCSVWriter

            csv_path = tmp_path / "test.csv"
            writer = AsyncCSVWriter(header="col1,col2")

            await writer.start(csv_path)
            writer.enqueue("val1,val2\n")
            writer.enqueue("val3,val4\n")
            await writer.stop()

            content = csv_path.read_text()
            assert "val1,val2" in content
            assert "val3,val4" in content

        run_async(_test())

    def test_path_property(self, tmp_path):
        """Test path property returns file path."""
        async def _test():
            from rpi_logger.modules.EyeTracker.tracker_core.recording.async_csv_writer import AsyncCSVWriter

            csv_path = tmp_path / "test.csv"
            writer = AsyncCSVWriter()

            await writer.start(csv_path)
            assert writer.path == csv_path
            await writer.stop()

        run_async(_test())

    def test_cleanup(self, tmp_path):
        """Test cleanup calls stop."""
        async def _test():
            from rpi_logger.modules.EyeTracker.tracker_core.recording.async_csv_writer import AsyncCSVWriter

            csv_path = tmp_path / "test.csv"
            writer = AsyncCSVWriter()

            await writer.start(csv_path)
            await writer.cleanup()

            # Should not raise on second cleanup
            await writer.cleanup()

        run_async(_test())


# =============================================================================
# GazeTracker Tests
# =============================================================================

class TestGazeTracker:
    """Tests for GazeTracker main class."""

    def test_initial_state(self, tracker_config):
        """Test GazeTracker initial state."""
        from rpi_logger.modules.EyeTracker.tracker_core.gaze_tracker import GazeTracker
        from rpi_logger.modules.EyeTracker.tracker_core.device_manager import DeviceManager
        from rpi_logger.modules.EyeTracker.tracker_core.stream_handler import StreamHandler

        with patch('rpi_logger.modules.EyeTracker.tracker_core.gaze_tracker.RecordingManager'), \
             patch('rpi_logger.modules.EyeTracker.tracker_core.gaze_tracker.FrameProcessor'):

            device_manager = MagicMock()
            stream_handler = MagicMock()
            frame_processor = MagicMock()
            recording_manager = MagicMock()

            tracker = GazeTracker(
                tracker_config,
                device_manager=device_manager,
                stream_handler=stream_handler,
                frame_processor=frame_processor,
                recording_manager=recording_manager,
            )

            assert tracker.running is False
            assert tracker.frame_count == 0
            assert tracker.display_enabled is True
            assert tracker.is_paused is False

    def test_pause_resume(self, tracker_config):
        """Test pause and resume functionality."""
        async def _test():
            from rpi_logger.modules.EyeTracker.tracker_core.gaze_tracker import GazeTracker

            with patch('rpi_logger.modules.EyeTracker.tracker_core.gaze_tracker.RecordingManager'), \
                 patch('rpi_logger.modules.EyeTracker.tracker_core.gaze_tracker.FrameProcessor'):

                tracker = GazeTracker(
                    tracker_config,
                    device_manager=MagicMock(),
                    stream_handler=MagicMock(),
                    frame_processor=MagicMock(),
                    recording_manager=MagicMock(),
                )

                assert tracker.is_paused is False

                await tracker.pause()
                assert tracker.is_paused is True

                # Pausing again should be no-op
                await tracker.pause()
                assert tracker.is_paused is True

                await tracker.resume()
                assert tracker.is_paused is False

                # Resuming again should be no-op
                await tracker.resume()
                assert tracker.is_paused is False

        run_async(_test())

    def test_reduced_processing_mode(self, tracker_config):
        """Test reduced processing mode setting."""
        from rpi_logger.modules.EyeTracker.tracker_core.gaze_tracker import GazeTracker

        with patch('rpi_logger.modules.EyeTracker.tracker_core.gaze_tracker.RecordingManager'), \
             patch('rpi_logger.modules.EyeTracker.tracker_core.gaze_tracker.FrameProcessor'):

            tracker = GazeTracker(
                tracker_config,
                device_manager=MagicMock(),
                stream_handler=MagicMock(),
                frame_processor=MagicMock(),
                recording_manager=MagicMock(),
            )

            assert tracker.is_reduced_processing is False

            tracker.set_reduced_processing(True)
            assert tracker.is_reduced_processing is True

            tracker.set_reduced_processing(False)
            assert tracker.is_reduced_processing is False

    def test_display_fps_tracking(self, tracker_config):
        """Test display FPS tracking."""
        from rpi_logger.modules.EyeTracker.tracker_core.gaze_tracker import GazeTracker

        with patch('rpi_logger.modules.EyeTracker.tracker_core.gaze_tracker.RecordingManager'), \
             patch('rpi_logger.modules.EyeTracker.tracker_core.gaze_tracker.FrameProcessor'):

            tracker = GazeTracker(
                tracker_config,
                device_manager=MagicMock(),
                stream_handler=MagicMock(),
                frame_processor=MagicMock(),
                recording_manager=MagicMock(),
            )

            # Initial FPS should be 0
            assert tracker.get_display_fps() == 0.0

            # Add some frames
            for _ in range(5):
                tracker._display_fps_tracker.add_frame()

            fps = tracker.get_display_fps()
            assert fps >= 0


# =============================================================================
# TrackerHandler Tests
# =============================================================================

class TestTrackerHandler:
    """Tests for TrackerHandler coordinator."""

    def test_initial_state(self, tracker_config):
        """Test TrackerHandler initial state."""
        from rpi_logger.modules.EyeTracker.tracker_core.tracker_handler import TrackerHandler

        device_manager = MagicMock()
        stream_handler = MagicMock()
        frame_processor = MagicMock()
        recording_manager = MagicMock()

        handler = TrackerHandler(
            tracker_config,
            device_manager,
            stream_handler,
            frame_processor,
            recording_manager,
        )

        assert handler.gaze_tracker is None
        assert handler._run_task is None

    def test_ensure_tracker_creates_tracker(self, tracker_config):
        """Test ensure_tracker creates GazeTracker."""
        from rpi_logger.modules.EyeTracker.tracker_core.tracker_handler import TrackerHandler

        with patch('rpi_logger.modules.EyeTracker.tracker_core.tracker_handler.GazeTracker') as MockTracker:
            device_manager = MagicMock()
            stream_handler = MagicMock()
            frame_processor = MagicMock()
            recording_manager = MagicMock()

            handler = TrackerHandler(
                tracker_config,
                device_manager,
                stream_handler,
                frame_processor,
                recording_manager,
            )

            tracker = handler.ensure_tracker(display_enabled=True)

            MockTracker.assert_called_once()
            assert handler.gaze_tracker is not None

    def test_ensure_tracker_reuses_existing(self, tracker_config):
        """Test ensure_tracker reuses existing tracker."""
        from rpi_logger.modules.EyeTracker.tracker_core.tracker_handler import TrackerHandler

        with patch('rpi_logger.modules.EyeTracker.tracker_core.tracker_handler.GazeTracker') as MockTracker:
            mock_tracker = MagicMock()
            MockTracker.return_value = mock_tracker

            handler = TrackerHandler(
                tracker_config,
                MagicMock(),
                MagicMock(),
                MagicMock(),
                MagicMock(),
            )

            tracker1 = handler.ensure_tracker(display_enabled=True)
            tracker2 = handler.ensure_tracker(display_enabled=False)

            # Should only create once
            assert MockTracker.call_count == 1
            assert tracker1 is tracker2

    def test_is_paused_without_tracker(self, tracker_config):
        """Test is_paused returns False without tracker."""
        from rpi_logger.modules.EyeTracker.tracker_core.tracker_handler import TrackerHandler

        handler = TrackerHandler(
            tracker_config,
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )

        assert handler.is_paused() is False

    def test_get_display_frame_without_tracker(self, tracker_config):
        """Test get_display_frame returns None without tracker."""
        from rpi_logger.modules.EyeTracker.tracker_core.tracker_handler import TrackerHandler

        handler = TrackerHandler(
            tracker_config,
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )

        assert handler.get_display_frame() is None

    def test_get_display_fps_without_tracker(self, tracker_config):
        """Test get_display_fps returns 0 without tracker."""
        from rpi_logger.modules.EyeTracker.tracker_core.tracker_handler import TrackerHandler

        handler = TrackerHandler(
            tracker_config,
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )

        assert handler.get_display_fps() == 0.0


# =============================================================================
# Mock API Tests
# =============================================================================

class TestMockPupilNeonAPI:
    """Tests for MockPupilNeonAPI functionality."""

    def test_api_initialization(self, mock_pupil_api):
        """Test API initialization."""
        assert mock_pupil_api.device is not None
        assert mock_pupil_api.gaze_rate == 200.0
        assert mock_pupil_api.video_rate == 30.0

    def test_connect(self, mock_pupil_api):
        """Test connect method."""
        async def _test():
            await mock_pupil_api.connect()
            # Should complete without error

        run_async(_test())

    def test_start_stop_streaming(self, mock_pupil_api):
        """Test start and stop streaming."""
        mock_pupil_api.start_streaming()
        assert mock_pupil_api._streaming is True

        mock_pupil_api.stop_streaming()
        assert mock_pupil_api._streaming is False

    def test_receive_gaze_yields_data(self, mock_pupil_api):
        """Test receive_gaze yields gaze data."""
        async def _test():
            mock_pupil_api.start_streaming()

            count = 0
            async for gaze in mock_pupil_api.receive_gaze():
                assert hasattr(gaze, "x")
                assert hasattr(gaze, "y")
                count += 1
                if count >= 2:
                    mock_pupil_api.stop_streaming()
                    break

        run_async(_test())

    def test_receive_imu_yields_data(self, mock_pupil_api):
        """Test receive_imu yields IMU data."""
        async def _test():
            mock_pupil_api.start_streaming()

            count = 0
            async for imu in mock_pupil_api.receive_imu():
                assert hasattr(imu, "gyro_data")
                assert hasattr(imu, "accel_data")
                count += 1
                if count >= 2:
                    mock_pupil_api.stop_streaming()
                    break

        run_async(_test())


class TestMockDiscovery:
    """Tests for MockDiscovery device discovery."""

    def test_discover_returns_devices(self):
        """Test discover returns device list."""
        async def _test():
            from tests.infrastructure.mocks.network_mocks import MockDiscovery, MockDeviceInfo

            devices = [
                MockDeviceInfo(serial="DEV001"),
                MockDeviceInfo(serial="DEV002"),
            ]
            discovery = MockDiscovery(devices=devices)

            found = await discovery.discover(timeout=1.0)

            assert len(found) == 2
            assert found[0].serial == "DEV001"
            assert found[1].serial == "DEV002"

        run_async(_test())


class TestMockDeviceInfo:
    """Tests for MockDeviceInfo."""

    def test_device_info_attributes(self):
        """Test MockDeviceInfo attributes."""
        from tests.infrastructure.mocks.network_mocks import MockDeviceInfo

        device = MockDeviceInfo(
            serial="TEST123",
            name="Test Device",
            ip="10.0.0.50",
            port=9000,
        )

        assert device.serial == "TEST123"
        assert device.name == "Test Device"
        assert device.phone_ip == "10.0.0.50"

    def test_stream_urls(self):
        """Test stream URL generation."""
        from tests.infrastructure.mocks.network_mocks import MockDeviceInfo

        device = MockDeviceInfo(ip="192.168.1.100", port=8080)

        world_url = device.direct_world_sensor_url()
        eyes_url = device.direct_eyes_sensor_url()

        assert "192.168.1.100" in world_url
        assert "world" in world_url
        assert "eyes" in eyes_url


# =============================================================================
# Error Handling Tests
# =============================================================================

class TestErrorHandling:
    """Tests for error handling in various components."""

    def test_device_manager_cleanup_error_handling(self):
        """Test DeviceManager cleanup handles errors gracefully."""
        with patch.dict('sys.modules', {'pupil_labs.realtime_api.device': MagicMock()}):
            from rpi_logger.modules.EyeTracker.tracker_core.device_manager import DeviceManager

            manager = DeviceManager()
            mock_device = AsyncMock()
            mock_device.close.side_effect = Exception("Close failed")
            manager.device = mock_device
            manager.device_ip = "192.168.1.100"

            # Should not raise despite exception in close
            asyncio.run(manager.cleanup())

            # Should still reset state
            assert manager.device is None
            assert manager.device_ip is None

    def test_stream_handler_enqueue_full_queue(self):
        """Test stream handler handles full queue."""
        from rpi_logger.modules.EyeTracker.tracker_core.stream_handler import StreamHandler

        handler = StreamHandler()
        handler._gaze_queue = asyncio.Queue(maxsize=2)

        # Fill the queue
        handler._gaze_queue.put_nowait("item1")
        handler._gaze_queue.put_nowait("item2")

        # Should not raise - drops old item
        handler._enqueue_latest(handler._gaze_queue, "item3", stream_name="gaze")

        # Queue should still have 2 items with newest
        assert handler._gaze_queue.qsize() == 2
        assert handler._dropped_gaze == 1

    def test_csv_writer_enqueue_without_start_raises(self):
        """Test CSV writer raises if enqueue called before start."""
        from rpi_logger.modules.EyeTracker.tracker_core.recording.async_csv_writer import AsyncCSVWriter

        writer = AsyncCSVWriter()

        with pytest.raises(RuntimeError, match="not started"):
            writer.enqueue("line\n")


# =============================================================================
# Integration-like Unit Tests (Still Mocked)
# =============================================================================

class TestDataFlowIntegration:
    """Tests for data flow between components (mocked integration)."""

    def test_gaze_data_to_recording_manager(self, tracker_config, temp_recording_dir, mock_gaze_data):
        """Test gaze data flows to recording manager."""
        with patch('rpi_logger.modules.EyeTracker.tracker_core.recording.manager.VideoEncoder'):
            from rpi_logger.modules.EyeTracker.tracker_core.recording.manager import RecordingManager

            tracker_config.output_dir = str(temp_recording_dir)
            manager = RecordingManager(tracker_config)

            # Mock the writer
            manager._is_recording = True
            manager._gaze_writer = MagicMock()
            manager._current_trial_number = 1

            manager.write_gaze_sample(mock_gaze_data)

            manager._gaze_writer.enqueue.assert_called_once()
            assert manager._gaze_samples_written == 1

    def test_imu_data_to_recording_manager(self, tracker_config, temp_recording_dir, mock_imu_data):
        """Test IMU data flows to recording manager."""
        with patch('rpi_logger.modules.EyeTracker.tracker_core.recording.manager.VideoEncoder'):
            from rpi_logger.modules.EyeTracker.tracker_core.recording.manager import RecordingManager

            tracker_config.output_dir = str(temp_recording_dir)
            manager = RecordingManager(tracker_config)

            # Mock the writer
            manager._is_recording = True
            manager._imu_writer = MagicMock()
            manager._current_trial_number = 1

            manager.write_imu_sample(mock_imu_data)

            manager._imu_writer.enqueue.assert_called_once()
            assert manager._imu_samples_written == 1

    def test_event_data_to_recording_manager(self, tracker_config, temp_recording_dir, mock_eye_event):
        """Test event data flows to recording manager."""
        with patch('rpi_logger.modules.EyeTracker.tracker_core.recording.manager.VideoEncoder'):
            from rpi_logger.modules.EyeTracker.tracker_core.recording.manager import RecordingManager

            tracker_config.output_dir = str(temp_recording_dir)
            manager = RecordingManager(tracker_config)

            # Mock the writer
            manager._is_recording = True
            manager._event_writer = MagicMock()
            manager._current_trial_number = 1

            manager.write_event_sample(mock_eye_event)

            manager._event_writer.enqueue.assert_called_once()
            assert manager._event_samples_written == 1

    def test_write_methods_no_op_when_not_recording(self, tracker_config, temp_recording_dir, mock_gaze_data):
        """Test write methods are no-ops when not recording."""
        with patch('rpi_logger.modules.EyeTracker.tracker_core.recording.manager.VideoEncoder'):
            from rpi_logger.modules.EyeTracker.tracker_core.recording.manager import RecordingManager

            tracker_config.output_dir = str(temp_recording_dir)
            manager = RecordingManager(tracker_config)

            # Not recording
            assert manager._is_recording is False

            manager.write_gaze_sample(mock_gaze_data)
            manager.write_imu_sample(MagicMock())
            manager.write_event_sample(MagicMock())

            # Should not have written anything
            assert manager._gaze_samples_written == 0
            assert manager._imu_samples_written == 0
            assert manager._event_samples_written == 0


# =============================================================================
# RollingFPS Tests
# =============================================================================

class TestRollingFPS:
    """Tests for RollingFPS utility class."""

    def test_initial_fps_zero(self):
        """Test initial FPS is zero."""
        from rpi_logger.modules.EyeTracker.tracker_core.rolling_fps import RollingFPS

        fps_tracker = RollingFPS(window_seconds=5.0)
        assert fps_tracker.get_fps() == 0.0

    def test_add_frame(self):
        """Test adding frames."""
        from rpi_logger.modules.EyeTracker.tracker_core.rolling_fps import RollingFPS

        fps_tracker = RollingFPS(window_seconds=5.0)

        # Add multiple frames
        for _ in range(10):
            fps_tracker.add_frame()

        fps = fps_tracker.get_fps()
        # Should have some FPS now (exact value depends on timing)
        assert fps >= 0

    def test_reset(self):
        """Test reset clears frame history."""
        from rpi_logger.modules.EyeTracker.tracker_core.rolling_fps import RollingFPS

        fps_tracker = RollingFPS(window_seconds=5.0)

        # Add some frames
        for _ in range(5):
            fps_tracker.add_frame()

        fps_tracker.reset()

        # FPS should be 0 after reset
        assert fps_tracker.get_fps() == 0.0
