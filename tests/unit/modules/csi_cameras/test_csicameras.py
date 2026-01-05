"""Unit tests for CSICameras module.

This module provides comprehensive tests for the CSI camera functionality,
covering configuration loading, camera detection, frame capture, recording
logic, and error handling.

All tests are fully isolated with no real hardware access. Picamera2 and
other hardware interfaces are mocked.

Note: Async tests use asyncio.run() wrapper since pytest-asyncio is not installed.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

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
# Test Fixtures
# =============================================================================


@pytest.fixture
def mock_picamera2():
    """Create a mock Picamera2 class with realistic behavior."""
    mock_cam_instance = MagicMock()

    # Configure sensor modes
    mock_cam_instance.sensor_modes = [
        {
            "size": (1920, 1080),
            "fps": 30.0,
            "format": "SRGGB10",
            "bit_depth": 10,
            "exposure_limits": (114, 694422939),
            "crop_limits": (0, 0, 2028, 1520),
        },
        {
            "size": (1280, 720),
            "fps": 60.0,
            "format": "SRGGB10",
            "bit_depth": 10,
            "exposure_limits": (114, 347134494),
        },
        {
            "size": (640, 480),
            "fps": 90.0,
            "format": "SRGGB10",
            "bit_depth": 10,
        },
    ]

    # Configure camera controls (similar to real Picamera2)
    mock_cam_instance.camera_controls = {
        "AwbEnable": (True, True, True),
        "AwbMode": (0, 7, 0),
        "Brightness": (0.0, 1.0, 0.5),
        "Contrast": (0.0, 32.0, 1.0),
        "ExposureTime": (114, 694422939, 10000),
        "AnalogueGain": (1.0, 22.26, 1.0),
        "AeEnable": (False, True, True),
        "Saturation": (0.0, 32.0, 1.0),
        "Sharpness": (0.0, 16.0, 1.0),
        "FrameDurationLimits": (33333, 33333, 33333),
    }

    mock_cam_instance.camera_properties = {
        "Model": "imx296",
        "PixelArraySize": (1456, 1088),
    }

    mock_cam_instance.configure = MagicMock()
    mock_cam_instance.start = MagicMock()
    mock_cam_instance.stop = MagicMock()
    mock_cam_instance.close = MagicMock()
    mock_cam_instance.set_controls = MagicMock()

    # Setup capture_request to return a mock request
    mock_request = MagicMock()
    mock_request.get_metadata.return_value = {
        "SensorTimestamp": 123456789000,
        "ExposureTime": 10000,
    }
    # Return RGB888 frame data (height, width, 3)
    mock_request.make_array.return_value = np.zeros((1080, 1920, 3), dtype=np.uint8)
    mock_request.release = MagicMock()
    mock_cam_instance.capture_request.return_value = mock_request

    mock_picam2_class = MagicMock(return_value=mock_cam_instance)
    mock_picam2_class.global_camera_info = MagicMock(return_value=[
        {"Num": 0, "Model": "imx296"},
    ])
    mock_picam2_class.close_camera = MagicMock()

    return mock_picam2_class


@pytest.fixture
def mock_capabilities():
    """Create mock CameraCapabilities for testing."""
    from rpi_logger.modules.base.camera_types import (
        CameraCapabilities,
        CapabilityMode,
        CapabilitySource,
        ControlInfo,
        ControlType,
    )

    modes = [
        CapabilityMode(size=(1920, 1080), fps=30.0, pixel_format="RGB"),
        CapabilityMode(size=(1280, 720), fps=60.0, pixel_format="RGB"),
        CapabilityMode(size=(640, 480), fps=90.0, pixel_format="RGB"),
    ]

    controls = {
        "Brightness": ControlInfo(
            name="Brightness",
            control_type=ControlType.FLOAT,
            min_value=0.0,
            max_value=1.0,
            default_value=0.5,
            current_value=0.5,
        ),
        "Contrast": ControlInfo(
            name="Contrast",
            control_type=ControlType.FLOAT,
            min_value=0.0,
            max_value=32.0,
            default_value=1.0,
            current_value=1.0,
        ),
        "ExposureTime": ControlInfo(
            name="ExposureTime",
            control_type=ControlType.INTEGER,
            min_value=114,
            max_value=694422939,
            default_value=10000,
            current_value=10000,
        ),
        "AwbMode": ControlInfo(
            name="AwbMode",
            control_type=ControlType.ENUM,
            options=["Off", "Auto", "Incandescent", "Tungsten", "Fluorescent",
                     "Indoor", "Daylight", "Cloudy"],
            default_value=0,
            current_value=0,
        ),
    }

    return CameraCapabilities(
        modes=modes,
        default_preview_mode=modes[2],  # 640x480
        default_record_mode=modes[0],   # 1920x1080
        source=CapabilitySource.PROBE,
        controls=controls,
        limits={"exposure_min": 114, "exposure_max": 694422939},
    )


@pytest.fixture
def mock_camera_id():
    """Create mock CameraId for testing."""
    from rpi_logger.modules.base.camera_types import CameraId

    return CameraId(
        backend="picam",
        stable_id="0",
        friendly_name="IMX296 Global Shutter",
        dev_path="/dev/video0",
    )


@pytest.fixture
def mock_scoped_preferences():
    """Create mock ScopedPreferences for config testing."""
    mock_prefs = MagicMock()
    mock_prefs.snapshot.return_value = {
        "preview.resolution": "640x480",
        "preview.fps_cap": "30",
        "record.resolution": "1920x1080",
        "record.fps_cap": "30",
        "storage.base_path": "/tmp/csicameras",
        "logging.level": "DEBUG",
    }
    return mock_prefs


# =============================================================================
# Configuration Tests
# =============================================================================


class TestCSICamerasConfig:
    """Tests for CSICameras configuration loading and parsing."""

    def test_config_defaults(self):
        """Test that default configuration values are applied."""
        from rpi_logger.modules.CSICameras.config import (
            CSICamerasConfig,
            DEFAULT_CAPTURE_RESOLUTION,
            DEFAULT_CAPTURE_FPS,
            DEFAULT_PREVIEW_SIZE,
            DEFAULT_PREVIEW_FPS,
        )

        # Create config with no preferences
        config = CSICamerasConfig.from_preferences(None, None)

        assert config.preview.resolution == DEFAULT_PREVIEW_SIZE
        assert config.preview.fps_cap == DEFAULT_PREVIEW_FPS
        assert config.record.resolution == DEFAULT_CAPTURE_RESOLUTION
        assert config.record.fps_cap == DEFAULT_CAPTURE_FPS
        assert config.logging.level == "INFO"

    def test_config_from_preferences(self, mock_scoped_preferences):
        """Test that configuration is properly loaded from preferences."""
        from rpi_logger.modules.CSICameras.config import CSICamerasConfig

        config = CSICamerasConfig.from_preferences(mock_scoped_preferences, None)

        assert config.preview.resolution == (640, 480)
        assert config.preview.fps_cap == 30.0
        assert config.record.resolution == (1920, 1080)
        assert config.record.fps_cap == 30.0
        assert str(config.storage.base_path) == "/tmp/csicameras"
        assert config.logging.level == "DEBUG"

    def test_config_cli_overrides(self, mock_scoped_preferences):
        """Test that CLI arguments override preference values."""
        from rpi_logger.modules.CSICameras.config import CSICamerasConfig

        # Create mock args with overrides
        mock_args = MagicMock()
        mock_args.output_dir = "/custom/output"
        mock_args.log_level = "WARNING"

        config = CSICamerasConfig.from_preferences(mock_scoped_preferences, mock_args)

        assert str(config.storage.base_path) == "/custom/output"
        assert config.logging.level == "WARNING"

    def test_config_to_dict(self, mock_scoped_preferences):
        """Test that configuration can be exported to dictionary."""
        from rpi_logger.modules.CSICameras.config import CSICamerasConfig

        config = CSICamerasConfig.from_preferences(mock_scoped_preferences, None)
        config_dict = config.to_dict()

        assert "preview.resolution" in config_dict
        assert "record.resolution" in config_dict
        assert "storage.base_path" in config_dict
        assert config_dict["preview.resolution"] == "640x480"
        assert config_dict["record.resolution"] == "1920x1080"


class TestConfigParsing:
    """Tests for configuration value parsing helpers."""

    def test_parse_resolution_tuple(self):
        """Test parsing resolution from tuple."""
        from rpi_logger.modules.CSICameras.config import parse_resolution

        result = parse_resolution((1920, 1080), (0, 0))
        assert result == (1920, 1080)

    def test_parse_resolution_list(self):
        """Test parsing resolution from list."""
        from rpi_logger.modules.CSICameras.config import parse_resolution

        result = parse_resolution([1280, 720], (0, 0))
        assert result == (1280, 720)

    def test_parse_resolution_string(self):
        """Test parsing resolution from string."""
        from rpi_logger.modules.CSICameras.config import parse_resolution

        result = parse_resolution("640x480", (0, 0))
        assert result == (640, 480)

        result = parse_resolution("1920X1080", (0, 0))  # Case insensitive
        assert result == (1920, 1080)

    def test_parse_resolution_invalid_returns_default(self):
        """Test that invalid resolution returns default."""
        from rpi_logger.modules.CSICameras.config import parse_resolution

        default = (1280, 720)
        assert parse_resolution(None, default) == default
        assert parse_resolution("invalid", default) == default
        assert parse_resolution(123, default) == default


class TestPreviewSettings:
    """Tests for PreviewSettings dataclass."""

    def test_preview_settings_creation(self):
        """Test creating PreviewSettings with all fields."""
        from rpi_logger.modules.CSICameras.config import PreviewSettings

        settings = PreviewSettings(
            resolution=(640, 480),
            fps_cap=30.0,
            pixel_format="RGB",
            overlay=True,
            auto_start=False,
        )

        assert settings.resolution == (640, 480)
        assert settings.fps_cap == 30.0
        assert settings.pixel_format == "RGB"
        assert settings.overlay is True
        assert settings.auto_start is False


class TestRecordSettings:
    """Tests for RecordSettings dataclass."""

    def test_record_settings_creation(self):
        """Test creating RecordSettings with all fields."""
        from rpi_logger.modules.CSICameras.config import RecordSettings

        settings = RecordSettings(
            resolution=(1920, 1080),
            fps_cap=30.0,
            pixel_format="RGB",
            overlay=True,
        )

        assert settings.resolution == (1920, 1080)
        assert settings.fps_cap == 30.0


# =============================================================================
# Picamera2 Backend Probe Tests
# =============================================================================


class TestPicamBackendProbe:
    """Tests for Picamera2 backend probing functionality."""

    def test_probe_returns_capabilities(self, mock_picamera2):
        """Test that probe returns valid capabilities from Picamera2."""
        with patch.dict("sys.modules", {"picamera2": MagicMock(Picamera2=mock_picamera2)}):
            # Need to reload the module to pick up the mock
            from rpi_logger.modules.CSICameras.csi_core.backends import picam_backend

            # Patch Picamera2 at module level
            with patch.object(picam_backend, "Picamera2", mock_picamera2):
                caps = run_async(picam_backend.probe("0", logger=MagicMock()))

                assert caps is not None
                assert len(caps.modes) == 3
                assert caps.modes[0].size == (1920, 1080)
                assert caps.modes[0].fps == 30.0

    def test_probe_extracts_controls(self, mock_picamera2):
        """Test that probe extracts camera controls."""
        with patch.dict("sys.modules", {"picamera2": MagicMock(Picamera2=mock_picamera2)}):
            from rpi_logger.modules.CSICameras.csi_core.backends import picam_backend

            with patch.object(picam_backend, "Picamera2", mock_picamera2):
                caps = run_async(picam_backend.probe("0", logger=MagicMock()))

                assert caps is not None
                assert "Brightness" in caps.controls
                assert "ExposureTime" in caps.controls
                assert "AwbMode" in caps.controls

    def test_probe_handles_missing_picamera2(self):
        """Test that probe handles missing Picamera2 gracefully."""
        from rpi_logger.modules.CSICameras.csi_core.backends import picam_backend

        with patch.object(picam_backend, "Picamera2", None):
            caps = run_async(picam_backend.probe("0", logger=MagicMock()))
            assert caps is None

    def test_probe_handles_camera_open_failure(self, mock_picamera2):
        """Test that probe handles camera open failure gracefully."""
        mock_picamera2.side_effect = RuntimeError("Camera not found")

        with patch.dict("sys.modules", {"picamera2": MagicMock(Picamera2=mock_picamera2)}):
            from rpi_logger.modules.CSICameras.csi_core.backends import picam_backend

            with patch.object(picam_backend, "Picamera2", mock_picamera2):
                caps = run_async(picam_backend.probe("0", logger=MagicMock()))
                assert caps is None


class TestPicamEnums:
    """Tests for Picamera2 enum control handling."""

    def test_picam_enums_contains_awb_modes(self):
        """Test that PICAM_ENUMS contains AWB modes."""
        from rpi_logger.modules.CSICameras.csi_core.backends.picam_backend import PICAM_ENUMS

        assert "AwbMode" in PICAM_ENUMS
        assert "Auto" in PICAM_ENUMS["AwbMode"]
        assert "Daylight" in PICAM_ENUMS["AwbMode"]

    def test_picam_enums_contains_af_modes(self):
        """Test that PICAM_ENUMS contains AF modes."""
        from rpi_logger.modules.CSICameras.csi_core.backends.picam_backend import PICAM_ENUMS

        assert "AfMode" in PICAM_ENUMS
        assert "Manual" in PICAM_ENUMS["AfMode"]
        assert "Auto" in PICAM_ENUMS["AfMode"]
        assert "Continuous" in PICAM_ENUMS["AfMode"]


# =============================================================================
# PicamCapture Tests
# =============================================================================


class TestPicamCapture:
    """Tests for PicamCapture class."""

    def test_capture_initialization_fails_without_picamera2(self):
        """Test that PicamCapture raises error when Picamera2 unavailable."""
        with patch.dict("sys.modules", {"picamera2": None}):
            # Force reimport to pick up the patch
            import importlib
            from rpi_logger.modules.CSICameras.csi_core import capture

            with patch.object(capture, "Picamera2", None):
                with pytest.raises(RuntimeError, match="Picamera2 is not available"):
                    capture.PicamCapture("0", (1920, 1080), 30.0)

    def test_capture_start_configures_camera(self, mock_picamera2):
        """Test that capture start properly configures the camera."""
        from rpi_logger.modules.CSICameras.csi_core import capture

        with patch.object(capture, "Picamera2", mock_picamera2):
            picam = capture.PicamCapture("0", (1920, 1080), 30.0)
            run_async(picam.start())

            # Verify camera was opened and configured
            mock_picamera2.assert_called_once()
            cam_instance = mock_picamera2.return_value
            cam_instance.configure.assert_called_once()
            cam_instance.start.assert_called_once()

    def test_capture_with_lores_stream(self, mock_picamera2):
        """Test that capture can be configured with lores stream for preview."""
        from rpi_logger.modules.CSICameras.csi_core import capture

        # Make create_video_configuration return a real dict that can be modified
        mock_picamera2.return_value.create_video_configuration.return_value = {
            "main": {"size": (1920, 1080), "format": "RGB888"},
            "buffer_count": 4,
        }

        with patch.object(capture, "Picamera2", mock_picamera2):
            picam = capture.PicamCapture(
                "0",
                (1920, 1080),
                30.0,
                lores_size=(320, 240),
            )
            run_async(picam.start())

            # Verify lores stream was added to config before configure() was called
            cam_instance = mock_picamera2.return_value
            configure_call = cam_instance.configure.call_args
            config = configure_call[0][0]
            assert "lores" in config
            assert config["lores"]["size"] == (320, 240)
            assert config["lores"]["format"] == "YUV420"

    def test_capture_stop_closes_camera(self, mock_picamera2):
        """Test that capture stop properly closes the camera."""
        from rpi_logger.modules.CSICameras.csi_core import capture

        with patch.object(capture, "Picamera2", mock_picamera2):
            picam = capture.PicamCapture("0", (1920, 1080), 30.0)
            run_async(picam.start())
            run_async(picam.stop())

            cam_instance = mock_picamera2.return_value
            cam_instance.stop.assert_called_once()
            cam_instance.close.assert_called_once()

    def test_capture_actual_fps_returns_requested(self, mock_picamera2):
        """Test that actual_fps returns the requested FPS for Picam."""
        from rpi_logger.modules.CSICameras.csi_core import capture

        with patch.object(capture, "Picamera2", mock_picamera2):
            picam = capture.PicamCapture("0", (1920, 1080), 30.0)
            assert picam.actual_fps == 30.0

    def test_capture_set_control(self, mock_picamera2):
        """Test setting camera controls through capture."""
        from rpi_logger.modules.CSICameras.csi_core import capture

        with patch.object(capture, "Picamera2", mock_picamera2):
            picam = capture.PicamCapture("0", (1920, 1080), 30.0)
            run_async(picam.start())

            result = picam.set_control("Brightness", 0.7)
            assert result is True

            cam_instance = mock_picamera2.return_value
            cam_instance.set_controls.assert_called_with({"Brightness": 0.7})

    def test_capture_set_control_enum_converts_string(self, mock_picamera2):
        """Test that enum controls convert string values to indices."""
        from rpi_logger.modules.CSICameras.csi_core import capture

        with patch.object(capture, "Picamera2", mock_picamera2):
            picam = capture.PicamCapture("0", (1920, 1080), 30.0)
            run_async(picam.start())

            # AwbMode "Auto" should convert to index 1
            result = picam.set_control("AwbMode", "Auto")
            assert result is True

            cam_instance = mock_picamera2.return_value
            cam_instance.set_controls.assert_called_with({"AwbMode": 1})


class TestCaptureFrame:
    """Tests for CaptureFrame data class."""

    def test_capture_frame_creation(self):
        """Test creating a CaptureFrame with all fields."""
        from rpi_logger.modules.base.camera_types import CaptureFrame

        frame_data = np.zeros((1080, 1920, 3), dtype=np.uint8)
        frame = CaptureFrame(
            data=frame_data,
            timestamp=1000.0,
            frame_number=1,
            monotonic_ns=1000000000000,
            sensor_timestamp_ns=123456789000,
            wall_time=time.time(),
            color_format="rgb",
        )

        assert frame.data.shape == (1080, 1920, 3)
        assert frame.frame_number == 1
        assert frame.color_format == "rgb"

    def test_capture_frame_with_lores(self):
        """Test CaptureFrame with lores data for preview."""
        from rpi_logger.modules.base.camera_types import CaptureFrame

        main_data = np.zeros((1080, 1920, 3), dtype=np.uint8)
        lores_data = np.zeros((240, 320), dtype=np.uint8)  # YUV420

        frame = CaptureFrame(
            data=main_data,
            timestamp=1000.0,
            frame_number=1,
            monotonic_ns=1000000000000,
            sensor_timestamp_ns=123456789000,
            wall_time=time.time(),
            color_format="rgb",
            lores_data=lores_data,
            lores_format="yuv420",
        )

        assert frame.lores_data is not None
        assert frame.lores_format == "yuv420"


# =============================================================================
# Session Paths Tests
# =============================================================================


class TestSessionPaths:
    """Tests for session path resolution."""

    def test_resolve_session_paths_basic(self, mock_camera_id, tmp_path):
        """Test basic session path resolution."""
        from rpi_logger.modules.CSICameras.storage.session_paths import resolve_session_paths

        session_dir = tmp_path / "session_001"
        session_dir.mkdir()

        paths = resolve_session_paths(
            session_dir=session_dir,
            camera_id=mock_camera_id,
            trial_number=1,
        )

        assert paths.session_root == session_dir
        assert paths.camera_dir.exists()
        assert "CSICameras" in str(paths.camera_dir)
        assert paths.video_path.suffix == ".avi"
        assert "timing" in str(paths.timing_path)

    def test_resolve_session_paths_uses_friendly_name(self, mock_camera_id, tmp_path):
        """Test that paths use camera friendly name."""
        from rpi_logger.modules.CSICameras.storage.session_paths import resolve_session_paths

        session_dir = tmp_path / "session_001"
        session_dir.mkdir()

        paths = resolve_session_paths(
            session_dir=session_dir,
            camera_id=mock_camera_id,
            trial_number=1,
        )

        # Should include sanitized friendly name
        assert "IMX296" in str(paths.camera_dir) or "Global" in str(paths.camera_dir)

    def test_resolve_session_paths_no_friendly_name(self, tmp_path):
        """Test path resolution when no friendly name is set."""
        from rpi_logger.modules.base.camera_types import CameraId
        from rpi_logger.modules.CSICameras.storage.session_paths import resolve_session_paths

        camera_id = CameraId(
            backend="picam",
            stable_id="test_sensor_0",
            friendly_name=None,
        )

        session_dir = tmp_path / "session_001"
        session_dir.mkdir()

        paths = resolve_session_paths(
            session_dir=session_dir,
            camera_id=camera_id,
            trial_number=1,
        )

        # Should use stable_id when no friendly name
        assert "test_sensor_0" in str(paths.camera_dir)


class TestSanitizeForFilesystem:
    """Tests for filename sanitization."""

    def test_sanitize_replaces_spaces(self):
        """Test that spaces are replaced with underscores."""
        from rpi_logger.modules.CSICameras.storage.session_paths import _sanitize_for_filesystem

        result = _sanitize_for_filesystem("IMX296 Global Shutter")
        assert " " not in result
        assert "_" in result

    def test_sanitize_removes_problematic_chars(self):
        """Test that problematic characters are removed."""
        from rpi_logger.modules.CSICameras.storage.session_paths import _sanitize_for_filesystem

        result = _sanitize_for_filesystem("camera:1/path\\test")
        assert ":" not in result
        assert "/" not in result
        assert "\\" not in result

    def test_sanitize_truncates_long_names(self):
        """Test that long names are truncated."""
        from rpi_logger.modules.CSICameras.storage.session_paths import _sanitize_for_filesystem

        long_name = "a" * 100
        result = _sanitize_for_filesystem(long_name, max_length=50)
        assert len(result) <= 50

    def test_sanitize_empty_returns_default(self):
        """Test that empty input returns 'camera'."""
        from rpi_logger.modules.CSICameras.storage.session_paths import _sanitize_for_filesystem

        result = _sanitize_for_filesystem("")
        assert result == "camera"


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Tests for error handling scenarios."""

    def test_probe_handles_no_sensor_modes(self, mock_picamera2):
        """Test probe handles camera with no sensor modes."""
        mock_picamera2.return_value.sensor_modes = []

        with patch.dict("sys.modules", {"picamera2": MagicMock(Picamera2=mock_picamera2)}):
            from rpi_logger.modules.CSICameras.csi_core.backends import picam_backend

            with patch.object(picam_backend, "Picamera2", mock_picamera2):
                caps = run_async(picam_backend.probe("0", logger=MagicMock()))

                assert caps is not None
                assert len(caps.modes) == 0

    def test_capture_handles_request_failure(self, mock_picamera2):
        """Test capture handles failed capture requests."""
        mock_picamera2.return_value.capture_request.return_value = None

        from rpi_logger.modules.CSICameras.csi_core import capture

        with patch.object(capture, "Picamera2", mock_picamera2):
            picam = capture.PicamCapture("0", (1920, 1080), 30.0)
            run_async(picam.start())

            # The frames generator should skip None requests
            # Test that it doesn't raise an exception
            picam._running = False  # Stop immediately for test

            async def consume_frames():
                async for frame in picam.frames():
                    pass  # Should not yield any frames

            run_async(consume_frames())

    def test_set_control_without_camera_returns_false(self, mock_picamera2):
        """Test that set_control returns False when camera not open."""
        from rpi_logger.modules.CSICameras.csi_core import capture

        with patch.object(capture, "Picamera2", mock_picamera2):
            picam = capture.PicamCapture("0", (1920, 1080), 30.0)
            # Don't call start() - camera is not opened

            result = picam.set_control("Brightness", 0.5)
            assert result is False


# =============================================================================
# Camera Types Integration Tests
# =============================================================================


class TestCameraIdIntegration:
    """Tests for CameraId used with CSI cameras."""

    def test_camera_id_key_format(self, mock_camera_id):
        """Test that camera ID key follows expected format."""
        assert mock_camera_id.key == "picam:0"

    def test_camera_id_backend_is_picam(self, mock_camera_id):
        """Test that CSI cameras use 'picam' backend."""
        assert mock_camera_id.backend == "picam"


class TestCapabilityValidatorIntegration:
    """Tests for CapabilityValidator with CSI camera capabilities."""

    def test_validate_mode_valid(self, mock_capabilities):
        """Test validating a valid mode."""
        from rpi_logger.modules.base.camera_validator import CapabilityValidator

        validator = CapabilityValidator(mock_capabilities)
        result = validator.validate_mode((1920, 1080), 30.0)

        assert result.valid is True
        assert result.corrected_value == ((1920, 1080), 30.0)

    def test_validate_mode_invalid_corrected(self, mock_capabilities):
        """Test that invalid mode is corrected to closest valid."""
        from rpi_logger.modules.base.camera_validator import CapabilityValidator

        validator = CapabilityValidator(mock_capabilities)
        # 1920x1080 at 60fps is not available - should correct
        result = validator.validate_mode((1920, 1080), 60.0)

        assert result.valid is False
        # Should be corrected to a valid mode
        assert result.corrected_value is not None

    def test_validate_resolution_string_format(self, mock_capabilities):
        """Test validating resolution in string format."""
        from rpi_logger.modules.base.camera_validator import CapabilityValidator

        validator = CapabilityValidator(mock_capabilities)
        result = validator.validate_mode("1920x1080", 30.0)

        assert result.valid is True


# =============================================================================
# Camera Descriptor Tests
# =============================================================================


class TestCameraDescriptor:
    """Tests for CameraDescriptor with CSI cameras."""

    def test_descriptor_creation(self, mock_camera_id):
        """Test creating a CameraDescriptor for CSI camera."""
        from rpi_logger.modules.base.camera_types import CameraDescriptor

        descriptor = CameraDescriptor(
            camera_id=mock_camera_id,
            hw_model="imx296",
            location_hint="J3",  # Camera connector
        )

        assert descriptor.camera_id == mock_camera_id
        assert descriptor.hw_model == "imx296"
        assert descriptor.location_hint == "J3"

    def test_descriptor_serialization(self, mock_camera_id):
        """Test serializing and deserializing CameraDescriptor."""
        from rpi_logger.modules.base.camera_types import (
            CameraDescriptor,
            serialize_descriptor,
            deserialize_descriptor,
        )

        descriptor = CameraDescriptor(
            camera_id=mock_camera_id,
            hw_model="imx296",
            location_hint="J3",
            seen_at=time.monotonic(),
        )

        serialized = serialize_descriptor(descriptor)
        assert "camera_id" in serialized
        assert serialized["hw_model"] == "imx296"

        deserialized = deserialize_descriptor(serialized)
        assert deserialized is not None
        assert deserialized.hw_model == descriptor.hw_model


# =============================================================================
# Mock Infrastructure Tests
# =============================================================================


class TestMockPicamera2:
    """Tests for MockPicamera2 from camera_mocks.py."""

    def test_mock_picamera2_creation(self):
        """Test creating MockPicamera2 instance."""
        from tests.infrastructure.mocks.camera_mocks import MockPicamera2

        mock = MockPicamera2(camera_num=0)
        assert mock.camera_num == 0
        assert mock._started is False

    def test_mock_picamera2_video_config(self):
        """Test creating video configuration."""
        from tests.infrastructure.mocks.camera_mocks import MockPicamera2

        mock = MockPicamera2()
        config = mock.create_video_configuration(
            main={"size": (1920, 1080), "format": "RGB888"},
        )

        assert "main" in config
        assert config["main"]["size"] == (1920, 1080)

    def test_mock_picamera2_start_stop(self):
        """Test start and stop lifecycle."""
        from tests.infrastructure.mocks.camera_mocks import MockPicamera2

        mock = MockPicamera2()
        config = mock.create_video_configuration()
        mock.configure(config)
        mock.start()

        assert mock._started is True

        mock.stop()
        assert mock._started is False

    def test_mock_picamera2_capture_array(self):
        """Test capturing frames from mock."""
        from tests.infrastructure.mocks.camera_mocks import MockPicamera2

        mock = MockPicamera2()
        config = mock.create_video_configuration(
            main={"size": (640, 480), "format": "RGB888"},
        )
        mock.configure(config)
        mock.start()

        frame = mock.capture_array("main")
        assert isinstance(frame, np.ndarray)
        assert frame.shape == (480, 640, 3)

    def test_mock_picamera2_start_without_config_raises(self):
        """Test that start without configure raises error."""
        from tests.infrastructure.mocks.camera_mocks import MockPicamera2

        mock = MockPicamera2()
        with pytest.raises(RuntimeError, match="not configured"):
            mock.start()

    def test_mock_picamera2_global_camera_info(self):
        """Test global camera info static method."""
        from tests.infrastructure.mocks.camera_mocks import MockPicamera2

        info = MockPicamera2.global_camera_info()
        assert isinstance(info, list)
        assert len(info) >= 1
        assert "Model" in info[0]


# =============================================================================
# Control Info Tests
# =============================================================================


class TestControlInfo:
    """Tests for camera control information."""

    def test_control_info_integer_type(self):
        """Test creating integer control info."""
        from rpi_logger.modules.base.camera_types import ControlInfo, ControlType

        ctrl = ControlInfo(
            name="ExposureTime",
            control_type=ControlType.INTEGER,
            min_value=100,
            max_value=1000000,
            default_value=10000,
            current_value=10000,
        )

        assert ctrl.control_type == ControlType.INTEGER
        assert ctrl.min_value == 100
        assert ctrl.max_value == 1000000

    def test_control_info_enum_type(self):
        """Test creating enum control info."""
        from rpi_logger.modules.base.camera_types import ControlInfo, ControlType

        ctrl = ControlInfo(
            name="AwbMode",
            control_type=ControlType.ENUM,
            options=["Off", "Auto", "Daylight"],
            default_value=1,
            current_value=1,
        )

        assert ctrl.control_type == ControlType.ENUM
        assert len(ctrl.options) == 3
        assert "Auto" in ctrl.options

    def test_control_info_serialization(self):
        """Test serializing and deserializing control info."""
        from rpi_logger.modules.base.camera_types import (
            ControlInfo,
            ControlType,
            serialize_control,
            deserialize_control,
        )

        ctrl = ControlInfo(
            name="Brightness",
            control_type=ControlType.FLOAT,
            min_value=0.0,
            max_value=1.0,
            default_value=0.5,
            current_value=0.7,
        )

        serialized = serialize_control(ctrl)
        assert serialized["name"] == "Brightness"
        assert serialized["type"] == "float"

        deserialized = deserialize_control(serialized)
        assert deserialized is not None
        assert deserialized.name == "Brightness"
        assert deserialized.control_type == ControlType.FLOAT


# =============================================================================
# Capability Mode Tests
# =============================================================================


class TestCapabilityMode:
    """Tests for CapabilityMode used with CSI cameras."""

    def test_capability_mode_signature(self):
        """Test that mode signature is unique and consistent."""
        from rpi_logger.modules.base.camera_types import CapabilityMode

        mode1 = CapabilityMode(size=(1920, 1080), fps=30.0, pixel_format="RGB")
        mode2 = CapabilityMode(size=(1920, 1080), fps=30.0, pixel_format="RGB")
        mode3 = CapabilityMode(size=(1920, 1080), fps=60.0, pixel_format="RGB")

        assert mode1.signature() == mode2.signature()
        assert mode1.signature() != mode3.signature()

    def test_capability_mode_width_height_properties(self):
        """Test width and height property accessors."""
        from rpi_logger.modules.base.camera_types import CapabilityMode

        mode = CapabilityMode(size=(1920, 1080), fps=30.0, pixel_format="RGB")

        assert mode.width == 1920
        assert mode.height == 1080


# =============================================================================
# Camera Capabilities Serialization Tests
# =============================================================================


class TestCapabilitiesSerialization:
    """Tests for serializing/deserializing camera capabilities."""

    def test_serialize_capabilities(self, mock_capabilities):
        """Test serializing CameraCapabilities."""
        from rpi_logger.modules.base.camera_types import serialize_capabilities

        serialized = serialize_capabilities(mock_capabilities)

        assert "modes" in serialized
        assert len(serialized["modes"]) == 3
        assert "controls" in serialized
        assert "Brightness" in serialized["controls"]

    def test_deserialize_capabilities(self, mock_capabilities):
        """Test deserializing CameraCapabilities."""
        from rpi_logger.modules.base.camera_types import (
            serialize_capabilities,
            deserialize_capabilities,
        )

        serialized = serialize_capabilities(mock_capabilities)
        deserialized = deserialize_capabilities(serialized)

        assert deserialized is not None
        assert len(deserialized.modes) == 3
        assert "Brightness" in deserialized.controls

    def test_deserialize_handles_invalid_data(self):
        """Test that deserialization handles invalid data gracefully."""
        from rpi_logger.modules.base.camera_types import deserialize_capabilities

        assert deserialize_capabilities(None) is None
        assert deserialize_capabilities({}) is not None  # Empty but valid
        assert deserialize_capabilities("invalid") is None


# =============================================================================
# Integration with conftest fixtures
# =============================================================================


class TestWithConftestFixtures:
    """Tests using fixtures from the unit test conftest."""

    def test_mock_camera_factory(self, mock_camera_factory):
        """Test using mock_camera_factory from conftest."""
        mock = mock_camera_factory(
            width=1920,
            height=1080,
            fps=30.0,
            device_path="/dev/video0",
        )

        assert mock.isOpened() is True
        ret, frame = mock.read()
        assert ret is True
        assert frame.shape == (1080, 1920, 3)

    def test_temp_work_dir_for_session(self, temp_work_dir):
        """Test using temp_work_dir for session paths."""
        from rpi_logger.modules.base.camera_types import CameraId
        from rpi_logger.modules.CSICameras.storage.session_paths import resolve_session_paths

        camera_id = CameraId(backend="picam", stable_id="0", friendly_name="Test")
        session_dir = temp_work_dir / "session"
        session_dir.mkdir()

        paths = resolve_session_paths(session_dir, camera_id, trial_number=1)

        assert paths.session_root == session_dir
        assert paths.camera_dir.exists()
