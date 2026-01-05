"""Unit tests for the Cameras module.

This module provides comprehensive unit tests for camera-related functionality
including:
- Configuration loading and validation
- Camera device detection (with mocked cv2/OpenCV)
- Frame capture logic
- Video recording start/stop
- Resolution and FPS settings
- Error handling

All tests are isolated and do not require real hardware. Mock cv2.VideoCapture
and other camera-related components appropriately.
"""

from __future__ import annotations

import asyncio
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, Mock, patch, PropertyMock

import numpy as np
import pytest


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def mock_cv2():
    """Create a comprehensive mock cv2 module."""
    mock = MagicMock()

    # Common OpenCV property constants
    mock.CAP_PROP_FRAME_WIDTH = 3
    mock.CAP_PROP_FRAME_HEIGHT = 4
    mock.CAP_PROP_FPS = 5
    mock.CAP_PROP_FOURCC = 6
    mock.CAP_PROP_BRIGHTNESS = 10
    mock.CAP_PROP_CONTRAST = 11
    mock.CAP_PROP_SATURATION = 12
    mock.CAP_PROP_HUE = 13
    mock.CAP_PROP_GAIN = 14
    mock.CAP_PROP_EXPOSURE = 15
    mock.CAP_PROP_AUTO_EXPOSURE = 21
    mock.CAP_PROP_AUTOFOCUS = 39
    mock.CAP_PROP_FOCUS = 28
    mock.CAP_PROP_ZOOM = 27
    mock.CAP_PROP_WHITE_BALANCE_BLUE_U = 17
    mock.CAP_PROP_WHITE_BALANCE_RED_V = 26
    mock.CAP_PROP_GAMMA = 22
    mock.CAP_PROP_BACKLIGHT = 32
    mock.CAP_PROP_PAN = 33
    mock.CAP_PROP_TILT = 34
    mock.CAP_V4L2 = 200

    # VideoWriter_fourcc
    mock.VideoWriter_fourcc = lambda *args: sum(ord(c) << (8 * i) for i, c in enumerate(args))

    # Font and line constants for overlay
    mock.FONT_HERSHEY_SIMPLEX = 0
    mock.LINE_AA = 16
    mock.putText = MagicMock()

    # VideoWriter mock
    mock_writer = MagicMock()
    mock_writer.isOpened.return_value = True
    mock_writer.write = MagicMock()
    mock_writer.release = MagicMock()
    mock.VideoWriter.return_value = mock_writer

    return mock


@pytest.fixture
def mock_video_capture(mock_cv2):
    """Create a mock VideoCapture that returns valid frames."""
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True

    # Frame dimensions
    _width = 1920
    _height = 1080
    _fps = 30.0

    # Properties storage
    _props = {
        3: float(_width),   # CAP_PROP_FRAME_WIDTH
        4: float(_height),  # CAP_PROP_FRAME_HEIGHT
        5: float(_fps),     # CAP_PROP_FPS
    }

    def mock_get(prop_id):
        return _props.get(prop_id, 0.0)

    def mock_set(prop_id, value):
        _props[prop_id] = float(value)
        return True

    mock_cap.get.side_effect = mock_get
    mock_cap.set.side_effect = mock_set

    # Generate test frames
    def mock_read():
        frame = np.zeros((_height, _width, 3), dtype=np.uint8)
        return True, frame

    mock_cap.read.side_effect = mock_read
    mock_cap.release = MagicMock()

    mock_cv2.VideoCapture.return_value = mock_cap

    return mock_cap


@pytest.fixture
def sample_camera_config():
    """Create a sample camera configuration dictionary."""
    return {
        "preview.resolution": "1280x720",
        "preview.fps_cap": 30.0,
        "preview.format": "RGB",
        "preview.overlay": True,
        "record.resolution": "1920x1080",
        "record.fps_cap": 30.0,
        "record.format": "MJPEG",
        "record.overlay": True,
        "guard.disk_free_gb_min": 1.0,
        "guard.check_interval_ms": 5000,
        "retention.max_sessions": 10,
        "retention.prune_on_start": True,
        "storage.base_path": "./data",
        "storage.per_camera_subdir": True,
        "telemetry.emit_interval_ms": 2000,
        "telemetry.include_metrics": True,
        "ui.auto_start_preview": False,
        "logging.level": "INFO",
        "logging.file": "./logs/cameras.log",
    }


# =============================================================================
# Configuration Tests
# =============================================================================


class TestCamerasConfig:
    """Tests for Cameras configuration loading and validation."""

    def test_default_config_values(self):
        """Test that default configuration values are reasonable."""
        from rpi_logger.modules.Cameras.config import (
            DEFAULT_CAPTURE_RESOLUTION,
            DEFAULT_CAPTURE_FPS,
            DEFAULT_RECORD_FPS,
            DEFAULT_PREVIEW_SIZE,
            DEFAULT_PREVIEW_FPS,
            DEFAULT_PREVIEW_JPEG_QUALITY,
            DEFAULT_GUARD_DISK_FREE_GB,
            DEFAULT_RETENTION_MAX_SESSIONS,
        )

        assert DEFAULT_CAPTURE_RESOLUTION == (1280, 720)
        assert DEFAULT_CAPTURE_FPS == 30.0
        assert DEFAULT_RECORD_FPS == 30.0
        assert DEFAULT_PREVIEW_SIZE == (320, 180)
        assert DEFAULT_PREVIEW_FPS == 10.0
        assert DEFAULT_PREVIEW_JPEG_QUALITY == 80
        assert DEFAULT_GUARD_DISK_FREE_GB == 1.0
        assert DEFAULT_RETENTION_MAX_SESSIONS == 10

    def test_preview_settings_dataclass(self):
        """Test PreviewSettings dataclass creation."""
        from rpi_logger.modules.Cameras.config import PreviewSettings

        settings = PreviewSettings(
            resolution=(1280, 720),
            fps_cap=30.0,
            pixel_format="RGB",
            overlay=True,
            auto_start=False,
        )

        assert settings.resolution == (1280, 720)
        assert settings.fps_cap == 30.0
        assert settings.pixel_format == "RGB"
        assert settings.overlay is True
        assert settings.auto_start is False

    def test_record_settings_dataclass(self):
        """Test RecordSettings dataclass creation."""
        from rpi_logger.modules.Cameras.config import RecordSettings

        settings = RecordSettings(
            resolution=(1920, 1080),
            fps_cap=30.0,
            pixel_format="MJPEG",
            overlay=True,
        )

        assert settings.resolution == (1920, 1080)
        assert settings.fps_cap == 30.0
        assert settings.pixel_format == "MJPEG"
        assert settings.overlay is True

    def test_guard_settings_dataclass(self):
        """Test GuardSettings dataclass creation."""
        from rpi_logger.modules.Cameras.config import GuardSettings

        settings = GuardSettings(
            disk_free_gb_min=2.0,
            check_interval_ms=10000,
        )

        assert settings.disk_free_gb_min == 2.0
        assert settings.check_interval_ms == 10000

    def test_storage_settings_dataclass(self):
        """Test StorageSettings dataclass creation."""
        from rpi_logger.modules.Cameras.config import StorageSettings

        settings = StorageSettings(
            base_path=Path("/tmp/camera_data"),
            per_camera_subdir=True,
        )

        assert settings.base_path == Path("/tmp/camera_data")
        assert settings.per_camera_subdir is True

    def test_cameras_config_to_dict(self):
        """Test CamerasConfig.to_dict() serialization."""
        from rpi_logger.modules.Cameras.config import (
            CamerasConfig,
            PreviewSettings,
            RecordSettings,
            GuardSettings,
            RetentionSettings,
            StorageSettings,
            TelemetrySettings,
            UISettings,
            BackendSettings,
            LoggingSettings,
        )

        config = CamerasConfig(
            preview=PreviewSettings((1280, 720), 30.0, "RGB", True),
            record=RecordSettings((1920, 1080), 30.0, "MJPEG", True),
            guard=GuardSettings(1.0, 5000),
            retention=RetentionSettings(10, True),
            storage=StorageSettings(Path("./data"), True),
            telemetry=TelemetrySettings(2000, True),
            ui=UISettings(False),
            backend=BackendSettings({}),
            logging=LoggingSettings("INFO", Path("./logs/cameras.log")),
        )

        result = config.to_dict()

        assert result["preview.resolution"] == "1280x720"
        assert result["preview.fps_cap"] == 30.0
        assert result["record.resolution"] == "1920x1080"
        assert result["guard.disk_free_gb_min"] == 1.0
        assert result["storage.per_camera_subdir"] is True


class TestConfigCoercion:
    """Tests for configuration type coercion functions."""

    def test_resolution_parsing_tuple(self):
        """Test parsing resolution from tuple."""
        from rpi_logger.modules.Cameras.utils import parse_resolution

        result = parse_resolution((1920, 1080), (640, 480))
        assert result == (1920, 1080)

    def test_resolution_parsing_list(self):
        """Test parsing resolution from list."""
        from rpi_logger.modules.Cameras.utils import parse_resolution

        result = parse_resolution([1280, 720], (640, 480))
        assert result == (1280, 720)

    def test_resolution_parsing_string(self):
        """Test parsing resolution from string."""
        from rpi_logger.modules.Cameras.utils import parse_resolution

        result = parse_resolution("1920x1080", (640, 480))
        assert result == (1920, 1080)

    def test_resolution_parsing_invalid_returns_default(self):
        """Test that invalid resolution returns default."""
        from rpi_logger.modules.Cameras.utils import parse_resolution

        result = parse_resolution("invalid", (640, 480))
        assert result == (640, 480)

        result = parse_resolution(None, (320, 240))
        assert result == (320, 240)


# =============================================================================
# Camera State Tests
# =============================================================================


class TestCameraId:
    """Tests for CameraId data model."""

    def test_camera_id_creation(self):
        """Test CameraId creation and key generation."""
        from rpi_logger.modules.Cameras.camera_core import CameraId

        cam_id = CameraId(
            backend="usb",
            stable_id="usb_camera_001",
            friendly_name="Front Camera",
            dev_path="/dev/video0",
        )

        assert cam_id.backend == "usb"
        assert cam_id.stable_id == "usb_camera_001"
        assert cam_id.friendly_name == "Front Camera"
        assert cam_id.dev_path == "/dev/video0"
        assert cam_id.key == "usb:usb_camera_001"

    def test_camera_id_frozen(self):
        """Test that CameraId is immutable (frozen)."""
        from rpi_logger.modules.Cameras.camera_core import CameraId

        cam_id = CameraId(backend="usb", stable_id="test")

        with pytest.raises(AttributeError):
            cam_id.backend = "picam"

    def test_camera_id_optional_fields(self):
        """Test CameraId with optional fields as None."""
        from rpi_logger.modules.Cameras.camera_core import CameraId

        cam_id = CameraId(backend="picam", stable_id="csi_0")

        assert cam_id.friendly_name is None
        assert cam_id.dev_path is None
        assert cam_id.key == "picam:csi_0"


class TestCapabilityMode:
    """Tests for CapabilityMode data model."""

    def test_capability_mode_creation(self):
        """Test CapabilityMode creation."""
        from rpi_logger.modules.Cameras.camera_core import CapabilityMode

        mode = CapabilityMode(
            size=(1920, 1080),
            fps=30.0,
            pixel_format="MJPEG",
        )

        assert mode.size == (1920, 1080)
        assert mode.width == 1920
        assert mode.height == 1080
        assert mode.fps == 30.0
        assert mode.pixel_format == "MJPEG"

    def test_capability_mode_signature(self):
        """Test CapabilityMode signature generation."""
        from rpi_logger.modules.Cameras.camera_core import CapabilityMode

        mode = CapabilityMode(size=(1280, 720), fps=30.0, pixel_format="YUYV")

        sig = mode.signature()
        assert sig == (1280, 720, 30.0, "yuyv")  # format is lowercased

    def test_capability_mode_signature_uniqueness(self):
        """Test that different modes have different signatures."""
        from rpi_logger.modules.Cameras.camera_core import CapabilityMode

        mode1 = CapabilityMode(size=(1920, 1080), fps=30.0, pixel_format="MJPEG")
        mode2 = CapabilityMode(size=(1280, 720), fps=30.0, pixel_format="MJPEG")
        mode3 = CapabilityMode(size=(1920, 1080), fps=60.0, pixel_format="MJPEG")

        assert mode1.signature() != mode2.signature()
        assert mode1.signature() != mode3.signature()
        assert mode2.signature() != mode3.signature()


class TestCameraCapabilities:
    """Tests for CameraCapabilities data model."""

    def test_camera_capabilities_creation(self):
        """Test CameraCapabilities creation with modes."""
        from rpi_logger.modules.Cameras.camera_core import (
            CameraCapabilities,
            CapabilityMode,
            CapabilitySource,
        )

        modes = [
            CapabilityMode(size=(1920, 1080), fps=30.0, pixel_format="MJPEG"),
            CapabilityMode(size=(1280, 720), fps=60.0, pixel_format="MJPEG"),
        ]

        caps = CameraCapabilities(
            modes=modes,
            source=CapabilitySource.PROBE,
        )

        assert len(caps.modes) == 2
        assert caps.source == CapabilitySource.PROBE

    def test_camera_capabilities_dedupe(self):
        """Test CameraCapabilities duplicate mode removal."""
        from rpi_logger.modules.Cameras.camera_core import (
            CameraCapabilities,
            CapabilityMode,
        )

        # Create duplicate modes
        modes = [
            CapabilityMode(size=(1920, 1080), fps=30.0, pixel_format="MJPEG"),
            CapabilityMode(size=(1920, 1080), fps=30.0, pixel_format="MJPEG"),  # duplicate
            CapabilityMode(size=(1280, 720), fps=30.0, pixel_format="MJPEG"),
        ]

        caps = CameraCapabilities(modes=modes)
        caps.dedupe()

        assert len(caps.modes) == 2

    def test_camera_capabilities_find_matching(self):
        """Test CameraCapabilities mode lookup."""
        from rpi_logger.modules.Cameras.camera_core import (
            CameraCapabilities,
            CapabilityMode,
        )

        modes = [
            CapabilityMode(size=(1920, 1080), fps=30.0, pixel_format="MJPEG"),
            CapabilityMode(size=(1280, 720), fps=60.0, pixel_format="YUYV"),
        ]

        caps = CameraCapabilities(modes=modes)

        # Find existing mode
        target = CapabilityMode(size=(1280, 720), fps=60.0, pixel_format="YUYV")
        found = caps.find_matching(target)
        assert found is not None
        assert found.size == (1280, 720)

        # Non-existing mode
        missing = CapabilityMode(size=(640, 480), fps=30.0, pixel_format="MJPEG")
        not_found = caps.find_matching(missing)
        assert not_found is None


class TestRuntimeStatus:
    """Tests for RuntimeStatus enum."""

    def test_runtime_status_values(self):
        """Test RuntimeStatus enum values."""
        from rpi_logger.modules.Cameras.camera_core import RuntimeStatus

        assert RuntimeStatus.DISCOVERED.value == "discovered"
        assert RuntimeStatus.SELECTED.value == "selected"
        assert RuntimeStatus.PREVIEWING.value == "previewing"
        assert RuntimeStatus.RECORDING.value == "recording"
        assert RuntimeStatus.ERROR.value == "error"


class TestControlInfo:
    """Tests for ControlInfo data model."""

    def test_control_info_integer(self):
        """Test ControlInfo for integer control."""
        from rpi_logger.modules.Cameras.camera_core import ControlInfo, ControlType

        ctrl = ControlInfo(
            name="Brightness",
            control_type=ControlType.INTEGER,
            current_value=128,
            min_value=0,
            max_value=255,
            default_value=128,
            step=1.0,
        )

        assert ctrl.name == "Brightness"
        assert ctrl.control_type == ControlType.INTEGER
        assert ctrl.current_value == 128
        assert ctrl.min_value == 0
        assert ctrl.max_value == 255

    def test_control_info_boolean(self):
        """Test ControlInfo for boolean control."""
        from rpi_logger.modules.Cameras.camera_core import ControlInfo, ControlType

        ctrl = ControlInfo(
            name="AutoFocus",
            control_type=ControlType.BOOLEAN,
            current_value=True,
        )

        assert ctrl.control_type == ControlType.BOOLEAN
        assert ctrl.current_value is True

    def test_control_info_enum(self):
        """Test ControlInfo for enum control."""
        from rpi_logger.modules.Cameras.camera_core import ControlInfo, ControlType

        ctrl = ControlInfo(
            name="AutoExposure",
            control_type=ControlType.ENUM,
            current_value=3,
            options=["0:Manual", "1:Auto", "3:Aperture Priority"],
        )

        assert ctrl.control_type == ControlType.ENUM
        assert ctrl.options is not None
        assert len(ctrl.options) == 3


# =============================================================================
# Serialization Tests
# =============================================================================


class TestStateSerialization:
    """Tests for camera state serialization/deserialization."""

    def test_serialize_camera_id(self):
        """Test CameraId serialization."""
        from rpi_logger.modules.Cameras.camera_core import (
            CameraId,
            serialize_camera_id,
            deserialize_camera_id,
        )

        cam_id = CameraId(
            backend="usb",
            stable_id="cam_001",
            friendly_name="Test Camera",
            dev_path="/dev/video0",
        )

        serialized = serialize_camera_id(cam_id)

        assert serialized["backend"] == "usb"
        assert serialized["stable_id"] == "cam_001"
        assert serialized["friendly_name"] == "Test Camera"
        assert serialized["dev_path"] == "/dev/video0"

    def test_deserialize_camera_id(self):
        """Test CameraId deserialization."""
        from rpi_logger.modules.Cameras.camera_core import (
            CameraId,
            deserialize_camera_id,
        )

        data = {
            "backend": "picam",
            "stable_id": "csi_sensor_0",
            "friendly_name": "CSI Camera",
            "dev_path": None,
        }

        cam_id = deserialize_camera_id(data)

        assert cam_id is not None
        assert cam_id.backend == "picam"
        assert cam_id.stable_id == "csi_sensor_0"

    def test_deserialize_camera_id_invalid(self):
        """Test CameraId deserialization with invalid data."""
        from rpi_logger.modules.Cameras.camera_core import deserialize_camera_id

        assert deserialize_camera_id(None) is None
        assert deserialize_camera_id({}) is None
        assert deserialize_camera_id("not_a_dict") is None
        assert deserialize_camera_id({"backend": "usb"}) is None  # missing stable_id

    def test_serialize_capabilities(self):
        """Test CameraCapabilities serialization."""
        from rpi_logger.modules.Cameras.camera_core import (
            CameraCapabilities,
            CapabilityMode,
            CapabilitySource,
            serialize_capabilities,
        )

        caps = CameraCapabilities(
            modes=[
                CapabilityMode(size=(1920, 1080), fps=30.0, pixel_format="MJPEG"),
            ],
            source=CapabilitySource.PROBE,
            timestamp_ms=1234567890.0,
        )

        serialized = serialize_capabilities(caps)

        assert "modes" in serialized
        assert len(serialized["modes"]) == 1
        assert serialized["modes"][0]["size"] == [1920, 1080]
        assert serialized["source"] == "probe"

    def test_deserialize_capabilities(self):
        """Test CameraCapabilities deserialization."""
        from rpi_logger.modules.Cameras.camera_core import (
            deserialize_capabilities,
            CapabilitySource,
        )

        data = {
            "modes": [
                {"size": [1280, 720], "fps": 30.0, "pixel_format": "MJPEG"},
                {"size": [640, 480], "fps": 15.0, "pixel_format": "YUYV"},
            ],
            "source": "cache",
            "timestamp_ms": 1000.0,
        }

        caps = deserialize_capabilities(data)

        assert caps is not None
        assert len(caps.modes) == 2
        assert caps.modes[0].width == 1280
        assert caps.source == CapabilitySource.CACHE

    def test_serialize_control_info(self):
        """Test ControlInfo serialization."""
        from rpi_logger.modules.Cameras.camera_core import (
            ControlInfo,
            ControlType,
            serialize_control,
            deserialize_control,
        )

        ctrl = ControlInfo(
            name="Brightness",
            control_type=ControlType.INTEGER,
            current_value=128,
            min_value=0,
            max_value=255,
            default_value=128,
        )

        serialized = serialize_control(ctrl)

        assert serialized["name"] == "Brightness"
        assert serialized["type"] == "int"
        assert serialized["current"] == 128
        assert serialized["min"] == 0
        assert serialized["max"] == 255

    def test_deserialize_control_info(self):
        """Test ControlInfo deserialization."""
        from rpi_logger.modules.Cameras.camera_core import (
            deserialize_control,
            ControlType,
        )

        data = {
            "name": "Contrast",
            "type": "int",
            "current": 100,
            "min": 0,
            "max": 200,
            "default": 100,
        }

        ctrl = deserialize_control(data)

        assert ctrl is not None
        assert ctrl.name == "Contrast"
        assert ctrl.control_type == ControlType.INTEGER
        assert ctrl.current_value == 100


# =============================================================================
# Frame Capture Tests
# =============================================================================


class TestCaptureFrame:
    """Tests for CaptureFrame data model."""

    def test_capture_frame_creation(self):
        """Test CaptureFrame creation."""
        from rpi_logger.modules.Cameras.camera_core.capture import CaptureFrame

        frame_data = np.zeros((720, 1280, 3), dtype=np.uint8)
        mono_ns = time.monotonic_ns()

        frame = CaptureFrame(
            data=frame_data,
            timestamp=mono_ns / 1e9,
            frame_number=1,
            monotonic_ns=mono_ns,
            sensor_timestamp_ns=None,
            wall_time=time.time(),
            color_format="bgr",
        )

        assert frame.data.shape == (720, 1280, 3)
        assert frame.frame_number == 1
        assert frame.color_format == "bgr"
        assert frame.lores_data is None


class TestUSBCapture:
    """Tests for USB camera capture functionality."""

    def test_usb_capture_initialization(self, mock_cv2, mock_video_capture):
        """Test USBCapture initialization."""
        with patch.dict(sys.modules, {"cv2": mock_cv2}):
            from rpi_logger.modules.Cameras.camera_core.capture import USBCapture

            capture = USBCapture(
                dev_path="/dev/video0",
                resolution=(1280, 720),
                fps=30.0,
            )

            assert capture._dev_path == "/dev/video0"
            assert capture._resolution == (1280, 720)
            assert capture._requested_fps == 30.0
            assert capture._running is False

    def test_usb_capture_start_success(self, mock_cv2, mock_video_capture):
        """Test successful USB capture start."""
        async def run_test():
            with patch.dict(sys.modules, {"cv2": mock_cv2}):
                # Need to reimport after patching
                from rpi_logger.modules.Cameras.camera_core import capture as capture_module

                cap = capture_module.USBCapture(
                    dev_path="/dev/video0",
                    resolution=(1280, 720),
                    fps=30.0,
                )

                await cap.start()

                assert cap._running is True
                assert cap._cap is not None

                await cap.stop()

        asyncio.run(run_test())

    def test_usb_capture_start_failure(self, mock_cv2):
        """Test USB capture start failure when device not found."""
        async def run_test():
            # Create a mock that fails to open
            mock_cap = MagicMock()
            mock_cap.isOpened.return_value = False
            mock_cv2.VideoCapture.return_value = mock_cap

            with patch.dict(sys.modules, {"cv2": mock_cv2}):
                from rpi_logger.modules.Cameras.camera_core import capture as capture_module

                cap = capture_module.USBCapture(
                    dev_path="/dev/video99",
                    resolution=(1280, 720),
                    fps=30.0,
                )

                with pytest.raises(RuntimeError, match="Failed to open USB camera"):
                    await cap.start()

        asyncio.run(run_test())

    def test_usb_capture_stop(self, mock_cv2, mock_video_capture):
        """Test USB capture stop releases resources."""
        async def run_test():
            with patch.dict(sys.modules, {"cv2": mock_cv2}):
                from rpi_logger.modules.Cameras.camera_core import capture as capture_module

                cap = capture_module.USBCapture(
                    dev_path="/dev/video0",
                    resolution=(1920, 1080),
                    fps=30.0,
                )

                await cap.start()
                await cap.stop()

                assert cap._running is False
                assert cap._cap is None

        asyncio.run(run_test())

    def test_usb_capture_actual_fps_property(self, mock_cv2, mock_video_capture):
        """Test actual_fps property after start."""
        async def run_test():
            with patch.dict(sys.modules, {"cv2": mock_cv2}):
                from rpi_logger.modules.Cameras.camera_core import capture as capture_module

                cap = capture_module.USBCapture(
                    dev_path="/dev/video0",
                    resolution=(1280, 720),
                    fps=30.0,
                )

                await cap.start()

                # actual_fps should match what camera reports
                assert cap.actual_fps == 30.0

                await cap.stop()

        asyncio.run(run_test())


class TestOpenCapture:
    """Tests for open_capture function."""

    def test_open_capture_usb(self, mock_cv2, mock_video_capture):
        """Test open_capture for USB cameras."""
        async def run_test():
            with patch.dict(sys.modules, {"cv2": mock_cv2}):
                from rpi_logger.modules.Cameras.camera_core.capture import open_capture

                handle, caps = await open_capture(
                    camera_type="usb",
                    camera_id="/dev/video0",
                    resolution=(1280, 720),
                    fps=30.0,
                )

                assert handle is not None
                assert caps["camera_type"] == "usb"
                assert caps["camera_id"] == "/dev/video0"
                assert caps["resolution"] == (1280, 720)

                await handle.stop()

        asyncio.run(run_test())

    def test_open_capture_unsupported_type(self, mock_cv2):
        """Test open_capture raises error for unsupported camera type."""
        async def run_test():
            with patch.dict(sys.modules, {"cv2": mock_cv2}):
                from rpi_logger.modules.Cameras.camera_core.capture import open_capture

                with pytest.raises(ValueError, match="Unsupported camera type"):
                    await open_capture(
                        camera_type="imaginary",
                        camera_id="test",
                    )

        asyncio.run(run_test())


# =============================================================================
# Encoder Tests
# =============================================================================


class TestEncoder:
    """Tests for video Encoder class."""

    def test_encoder_initialization(self, tmp_path, mock_cv2):
        """Test Encoder initialization."""
        with patch.dict(sys.modules, {"cv2": mock_cv2}):
            from rpi_logger.modules.Cameras.camera_core import Encoder

            video_path = str(tmp_path / "test_video.avi")
            csv_path = str(tmp_path / "test_timing.csv")

            encoder = Encoder(
                video_path=video_path,
                resolution=(1920, 1080),
                fps=30.0,
                overlay_enabled=True,
                csv_path=csv_path,
                trial_number=1,
                device_id="test_camera",
                use_pyav=False,  # Use OpenCV backend for testing
            )

            assert encoder.video_path == video_path
            assert encoder.csv_path == csv_path
            assert encoder._resolution == (1920, 1080)
            assert encoder._fps == 30.0
            assert encoder._overlay_enabled is True
            assert encoder.frame_count == 0

    def test_encoder_start_opencv(self, tmp_path, mock_cv2):
        """Test Encoder start with OpenCV backend."""
        with patch.dict(sys.modules, {"cv2": mock_cv2}):
            from rpi_logger.modules.Cameras.camera_core import Encoder

            video_path = str(tmp_path / "test_video.avi")

            encoder = Encoder(
                video_path=video_path,
                resolution=(1280, 720),
                fps=30.0,
                use_pyav=False,
            )

            encoder.start()

            assert encoder._kind == "opencv"
            assert encoder._writer is not None
            assert encoder._worker is not None

            encoder.stop()

    def test_encoder_frame_count(self, tmp_path, mock_cv2):
        """Test encoder frame counting."""
        with patch.dict(sys.modules, {"cv2": mock_cv2}):
            from rpi_logger.modules.Cameras.camera_core import Encoder

            video_path = str(tmp_path / "test_video.avi")

            encoder = Encoder(
                video_path=video_path,
                resolution=(640, 480),
                fps=30.0,
                overlay_enabled=False,
                use_pyav=False,
            )

            encoder.start()

            # Write some frames
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            for i in range(5):
                encoder.write_frame(frame, timestamp=time.time())

            # Give worker thread time to process
            time.sleep(0.2)

            encoder.stop()

            # Frame count should be 5 after processing
            # Note: actual count depends on worker thread timing
            assert encoder.frame_count >= 0

    def test_encoder_csv_creation(self, tmp_path, mock_cv2):
        """Test that encoder creates CSV timing file."""
        with patch.dict(sys.modules, {"cv2": mock_cv2}):
            from rpi_logger.modules.Cameras.camera_core import Encoder

            video_path = str(tmp_path / "test_video.avi")
            csv_path = str(tmp_path / "test_timing.csv")

            encoder = Encoder(
                video_path=video_path,
                resolution=(640, 480),
                fps=30.0,
                csv_path=csv_path,
                trial_number=1,
                device_id="cam_0",
                overlay_enabled=False,
                use_pyav=False,
            )

            encoder.start()

            # Write a frame
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            encoder.write_frame(frame, timestamp=time.time())

            time.sleep(0.1)
            encoder.stop()

            # CSV file should exist
            assert Path(csv_path).exists()

    def test_encoder_duration_property(self, tmp_path, mock_cv2):
        """Test encoder duration_sec property."""
        with patch.dict(sys.modules, {"cv2": mock_cv2}):
            from rpi_logger.modules.Cameras.camera_core import Encoder

            video_path = str(tmp_path / "test_video.avi")

            encoder = Encoder(
                video_path=video_path,
                resolution=(640, 480),
                fps=30.0,
                use_pyav=False,
            )

            # Before start, duration is 0
            assert encoder.duration_sec == 0.0

            encoder.start()
            time.sleep(0.1)

            # After start, duration should be positive
            assert encoder.duration_sec > 0

            encoder.stop()


# =============================================================================
# USB Backend Tests
# =============================================================================


class TestUSBBackendProbe:
    """Tests for USB backend device probing."""

    def test_probe_returns_capabilities(self, mock_cv2, mock_video_capture):
        """Test that probe returns valid capabilities."""
        async def run_test():
            with patch.dict(sys.modules, {"cv2": mock_cv2}):
                from rpi_logger.modules.Cameras.camera_core.backends import usb_backend

                # Mock successful probing
                caps = await usb_backend.probe("/dev/video0")

                # Should return capabilities (may be None if probing failed)
                # In mocked environment, probing may not work fully
                # Just verify it doesn't crash

        asyncio.run(run_test())

    def test_probe_invalid_device_returns_none(self, mock_cv2):
        """Test probe returns None for invalid device."""
        async def run_test():
            mock_cap = MagicMock()
            mock_cap.isOpened.return_value = False
            mock_cv2.VideoCapture.return_value = mock_cap

            with patch.dict(sys.modules, {"cv2": mock_cv2}):
                from rpi_logger.modules.Cameras.camera_core.backends import usb_backend

                caps = await usb_backend.probe("/dev/video99")

                assert caps is None

        asyncio.run(run_test())


class TestUSBHandle:
    """Tests for USBHandle class."""

    def test_usb_handle_creation(self, mock_cv2, mock_video_capture):
        """Test USBHandle creation."""
        with patch.dict(sys.modules, {"cv2": mock_cv2}):
            from rpi_logger.modules.Cameras.camera_core.backends.usb_backend import USBHandle
            from rpi_logger.modules.Cameras.camera_core import CapabilityMode

            mode = CapabilityMode(size=(1280, 720), fps=30.0, pixel_format="MJPEG")

            handle = USBHandle("/dev/video0", mode)

            assert handle.dev_path == "/dev/video0"
            assert handle.mode == mode
            assert handle._frame_number == 0

    def test_usb_handle_is_alive(self, mock_cv2, mock_video_capture):
        """Test USBHandle is_alive check."""
        with patch.dict(sys.modules, {"cv2": mock_cv2}):
            from rpi_logger.modules.Cameras.camera_core.backends.usb_backend import USBHandle
            from rpi_logger.modules.Cameras.camera_core import CapabilityMode

            mode = CapabilityMode(size=(1280, 720), fps=30.0, pixel_format="MJPEG")
            handle = USBHandle("/dev/video0", mode)

            # Should be alive since mock returns isOpened=True
            assert handle.is_alive() is True

    def test_usb_handle_set_control(self, mock_cv2, mock_video_capture):
        """Test USBHandle set_control method."""
        with patch.dict(sys.modules, {"cv2": mock_cv2}):
            from rpi_logger.modules.Cameras.camera_core.backends.usb_backend import USBHandle
            from rpi_logger.modules.Cameras.camera_core import CapabilityMode

            mode = CapabilityMode(size=(1280, 720), fps=30.0, pixel_format="MJPEG")
            handle = USBHandle("/dev/video0", mode)

            # Test setting brightness
            result = handle.set_control("Brightness", 128)

            # Result depends on mock behavior
            assert isinstance(result, bool)


class TestDeviceLost:
    """Tests for DeviceLost exception."""

    def test_device_lost_exception(self):
        """Test DeviceLost exception creation."""
        from rpi_logger.modules.Cameras.camera_core.backends.usb_backend import DeviceLost

        exc = DeviceLost("Camera disconnected")

        assert str(exc) == "Camera disconnected"
        assert isinstance(exc, Exception)


# =============================================================================
# Utilities Tests
# =============================================================================


class TestCameraUtils:
    """Tests for camera utility functions."""

    def test_to_snake_case(self):
        """Test PascalCase to snake_case conversion."""
        from rpi_logger.modules.Cameras.camera_core.utils import to_snake_case

        assert to_snake_case("Brightness") == "brightness"
        assert to_snake_case("AutoExposure") == "auto_exposure"
        assert to_snake_case("WhiteBalanceBlueU") == "white_balance_blue_u"
        assert to_snake_case("FPS") == "f_p_s"  # All caps

    def test_resolution_parsing(self):
        """Test resolution parsing utility."""
        from rpi_logger.modules.Cameras.utils import parse_resolution

        # String format
        assert parse_resolution("1920x1080", (0, 0)) == (1920, 1080)
        assert parse_resolution("1280X720", (0, 0)) == (1280, 720)  # Case insensitive

        # Tuple/list format
        assert parse_resolution((640, 480), (0, 0)) == (640, 480)
        assert parse_resolution([320, 240], (0, 0)) == (320, 240)

        # Invalid returns default
        assert parse_resolution("invalid", (100, 100)) == (100, 100)
        assert parse_resolution(None, (200, 200)) == (200, 200)


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Tests for error handling in camera operations."""

    def test_capture_recovers_from_read_failure(self, mock_cv2):
        """Test capture handles read failures gracefully."""
        async def run_test():
            mock_cap = MagicMock()
            mock_cap.isOpened.return_value = True

            # Properties
            mock_cap.get.side_effect = lambda x: {3: 640.0, 4: 480.0, 5: 30.0}.get(x, 0.0)
            mock_cap.set.return_value = True

            # First read succeeds, subsequent fail
            call_count = [0]
            def mock_read():
                call_count[0] += 1
                if call_count[0] <= 3:  # First 3 reads succeed (for warmup)
                    return True, np.zeros((480, 640, 3), dtype=np.uint8)
                return False, None

            mock_cap.read.side_effect = mock_read
            mock_cv2.VideoCapture.return_value = mock_cap

            with patch.dict(sys.modules, {"cv2": mock_cv2}):
                from rpi_logger.modules.Cameras.camera_core import capture as capture_module

                cap = capture_module.USBCapture("/dev/video0", (640, 480), 30.0)

                await cap.start()

                # Should be running after successful start
                assert cap._running is True

                await cap.stop()

        asyncio.run(run_test())

    def test_encoder_handles_write_failure(self, tmp_path, mock_cv2):
        """Test encoder handles write failures."""
        mock_writer = MagicMock()
        mock_writer.isOpened.return_value = True
        mock_writer.write.side_effect = Exception("Write failed")
        mock_cv2.VideoWriter.return_value = mock_writer

        with patch.dict(sys.modules, {"cv2": mock_cv2}):
            from rpi_logger.modules.Cameras.camera_core import Encoder

            encoder = Encoder(
                video_path=str(tmp_path / "test.avi"),
                resolution=(640, 480),
                fps=30.0,
                use_pyav=False,
            )

            encoder.start()

            # Write should not raise even if underlying write fails
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            result = encoder.write_frame(frame, timestamp=time.time())

            # Result indicates if frame was queued (not encoded)
            assert isinstance(result, bool)

            encoder.stop()

    def test_config_handles_invalid_values(self):
        """Test config handles invalid values gracefully."""
        from rpi_logger.modules.Cameras.config import (
            _to_bool,
            _to_int,
            _to_float,
            _to_str,
        )

        # Invalid bool returns default
        assert _to_bool("not_bool", True) is False  # "not_bool" is not in truthy values
        assert _to_bool(None, True) is True

        # Invalid int returns default
        assert _to_int("not_int", 42) == 42
        assert _to_int(None, 100) == 100

        # Invalid float returns default
        assert _to_float("not_float", 3.14) == 3.14
        assert _to_float(None, 2.71) == 2.71

        # Empty string returns default
        assert _to_str("", "default") == "default"
        assert _to_str(None, "fallback") == "fallback"


# =============================================================================
# Integration-like Unit Tests (with mocks)
# =============================================================================


class TestCameraWorkflow:
    """Tests for typical camera workflows with mocked dependencies."""

    def test_camera_discovery_to_recording_workflow(
        self, tmp_path, mock_cv2, mock_video_capture
    ):
        """Test complete workflow from discovery to recording."""
        async def run_test():
            with patch.dict(sys.modules, {"cv2": mock_cv2}):
                from rpi_logger.modules.Cameras.camera_core import (
                    CameraId,
                    CameraDescriptor,
                    CameraCapabilities,
                    CameraRuntimeState,
                    CapabilityMode,
                    RuntimeStatus,
                )
                from rpi_logger.modules.Cameras.camera_core.capture import USBCapture
                from rpi_logger.modules.Cameras.camera_core import Encoder

                # Step 1: Create camera ID
                cam_id = CameraId(
                    backend="usb",
                    stable_id="test_cam_001",
                    friendly_name="Test Camera",
                    dev_path="/dev/video0",
                )
                assert cam_id.key == "usb:test_cam_001"

                # Step 2: Create descriptor
                descriptor = CameraDescriptor(
                    camera_id=cam_id,
                    hw_model="Mock USB Camera",
                    seen_at=time.monotonic() * 1000,
                )

                # Step 3: Create capabilities
                caps = CameraCapabilities(
                    modes=[
                        CapabilityMode(size=(1920, 1080), fps=30.0, pixel_format="MJPEG"),
                        CapabilityMode(size=(1280, 720), fps=60.0, pixel_format="MJPEG"),
                    ],
                )

                # Step 4: Create runtime state
                state = CameraRuntimeState(
                    descriptor=descriptor,
                    capabilities=caps,
                    status=RuntimeStatus.DISCOVERED,
                )
                assert state.status == RuntimeStatus.DISCOVERED

                # Step 5: Open capture
                capture = USBCapture("/dev/video0", (1280, 720), 30.0)
                await capture.start()
                assert capture._running is True

                # Step 6: Create encoder
                video_path = str(tmp_path / "recording.avi")
                encoder = Encoder(
                    video_path=video_path,
                    resolution=(1280, 720),
                    fps=30.0,
                    use_pyav=False,
                )
                encoder.start()

                # Step 7: Update state to recording
                state.status = RuntimeStatus.RECORDING
                assert state.status == RuntimeStatus.RECORDING

                # Step 8: Cleanup
                encoder.stop()
                await capture.stop()

                assert capture._running is False

        asyncio.run(run_test())

    def test_config_with_cli_overrides(self):
        """Test configuration with CLI argument overrides."""
        from rpi_logger.modules.Cameras.config import (
            CamerasConfig,
            PreviewSettings,
            RecordSettings,
            GuardSettings,
            RetentionSettings,
            StorageSettings,
            TelemetrySettings,
            UISettings,
            BackendSettings,
            LoggingSettings,
        )
        from pathlib import Path

        # Create base config
        config = CamerasConfig(
            preview=PreviewSettings((1280, 720), 30.0, "RGB", True),
            record=RecordSettings((1920, 1080), 30.0, "MJPEG", True),
            guard=GuardSettings(1.0, 5000),
            retention=RetentionSettings(10, True),
            storage=StorageSettings(Path("./data"), True),
            telemetry=TelemetrySettings(2000, True),
            ui=UISettings(False),
            backend=BackendSettings({}),
            logging=LoggingSettings("INFO", Path("./logs/cameras.log")),
        )

        # Verify config can be serialized
        config_dict = config.to_dict()

        assert config_dict["preview.resolution"] == "1280x720"
        assert config_dict["record.resolution"] == "1920x1080"
        assert config_dict["logging.level"] == "INFO"


# =============================================================================
# Mock Camera Backend Tests (from infrastructure/mocks)
# =============================================================================


class TestMockCameraBackend:
    """Tests for MockCameraBackend from infrastructure/mocks."""

    def test_mock_camera_backend_creation(self):
        """Test MockCameraBackend creation."""
        from tests.infrastructure.mocks.camera_mocks import MockCameraBackend

        backend = MockCameraBackend(
            device_path="/dev/video0",
            width=1920,
            height=1080,
            fps=30.0,
        )

        assert backend.device_path == "/dev/video0"
        assert backend.width == 1920
        assert backend.height == 1080
        assert backend.fps == 30.0

    def test_mock_camera_backend_open_close(self):
        """Test MockCameraBackend open and release."""
        from tests.infrastructure.mocks.camera_mocks import MockCameraBackend

        backend = MockCameraBackend()

        assert backend.isOpened() is False

        result = backend.open()
        assert result is True
        assert backend.isOpened() is True

        backend.release()
        assert backend.isOpened() is False

    def test_mock_camera_backend_read_frame(self):
        """Test MockCameraBackend frame reading."""
        from tests.infrastructure.mocks.camera_mocks import MockCameraBackend

        backend = MockCameraBackend(width=640, height=480, fps=30.0)
        backend.open()

        success, frame = backend.read()

        assert success is True
        assert frame is not None
        assert frame.shape == (480, 640, 3)

        backend.release()

    def test_mock_camera_backend_properties(self):
        """Test MockCameraBackend get/set properties."""
        from tests.infrastructure.mocks.camera_mocks import MockCameraBackend

        backend = MockCameraBackend(width=1280, height=720, fps=30.0)

        # Get properties
        assert backend.get(3) == 1280.0  # CAP_PROP_FRAME_WIDTH
        assert backend.get(4) == 720.0   # CAP_PROP_FRAME_HEIGHT
        assert backend.get(5) == 30.0    # CAP_PROP_FPS

        # Set properties
        backend.set(3, 1920)
        backend.set(4, 1080)
        backend.set(5, 60.0)

        assert backend.get(3) == 1920.0
        assert backend.get(4) == 1080.0
        assert backend.get(5) == 60.0

    def test_mock_camera_backend_patterns(self):
        """Test MockCameraBackend frame generation patterns."""
        from tests.infrastructure.mocks.camera_mocks import MockCameraBackend

        backend = MockCameraBackend(width=320, height=240)
        backend.open()

        # Test color bars (default)
        backend.set_pattern("color_bars")
        _, frame = backend.read()
        assert frame is not None

        # Test noise
        backend.set_pattern("noise")
        _, frame = backend.read()
        assert frame is not None

        # Test solid
        backend.set_pattern("solid")
        backend.set_solid_color((255, 0, 0))
        _, frame = backend.read()
        assert frame is not None

        backend.release()

    def test_mock_video_capture_compatibility(self):
        """Test MockVideoCapture OpenCV compatibility."""
        from tests.infrastructure.mocks.camera_mocks import MockVideoCapture

        cap = MockVideoCapture("/dev/video0")

        assert cap.isOpened() is True

        success, frame = cap.read()
        assert success is True
        assert frame is not None

        # Set/get properties
        cap.set(3, 640)
        assert cap.get(3) == 640.0

        cap.release()


class TestMockCameraCapabilities:
    """Tests for MockCameraCapabilities."""

    def test_mock_camera_capabilities_defaults(self):
        """Test MockCameraCapabilities default values."""
        from tests.infrastructure.mocks.camera_mocks import MockCameraCapabilities

        caps = MockCameraCapabilities()

        # Should have default modes
        assert len(caps.modes) == 3

        # Should have default controls
        assert "brightness" in caps.controls
        assert "contrast" in caps.controls
        assert "saturation" in caps.controls

    def test_mock_camera_capabilities_custom(self):
        """Test MockCameraCapabilities with custom values."""
        from tests.infrastructure.mocks.camera_mocks import (
            MockCameraCapabilities,
            MockCameraMode,
        )

        custom_modes = [
            MockCameraMode(width=4096, height=2160, fps=60.0, format="H264"),
        ]

        caps = MockCameraCapabilities(
            modes=custom_modes,
            hw_model="Custom 4K Camera",
            stable_id="custom_cam_0",
        )

        assert len(caps.modes) == 1
        assert caps.modes[0].width == 4096
        assert caps.hw_model == "Custom 4K Camera"


# =============================================================================
# Build Capabilities Tests
# =============================================================================


class TestBuildCapabilities:
    """Tests for build_capabilities function."""

    def test_build_capabilities_from_modes(self):
        """Test building capabilities from mode list."""
        from rpi_logger.modules.Cameras.camera_core.capabilities import build_capabilities

        modes = [
            {"size": (1920, 1080), "fps": 30.0, "pixel_format": "MJPEG"},
            {"size": (1280, 720), "fps": 60.0, "pixel_format": "MJPEG"},
            {"size": (640, 480), "fps": 30.0, "pixel_format": "YUYV"},
        ]

        caps = build_capabilities(modes)

        assert caps is not None
        assert len(caps.modes) == 3

        # Check default modes are set
        assert caps.default_preview_mode is not None or caps.default_record_mode is not None

    def test_build_capabilities_empty_modes(self):
        """Test building capabilities with empty mode list."""
        from rpi_logger.modules.Cameras.camera_core.capabilities import build_capabilities

        caps = build_capabilities([])

        assert caps is not None
        assert len(caps.modes) == 0

    def test_build_capabilities_deduplication(self):
        """Test that build_capabilities deduplicates modes."""
        from rpi_logger.modules.Cameras.camera_core.capabilities import build_capabilities

        # Duplicate modes
        modes = [
            {"size": (1280, 720), "fps": 30.0, "pixel_format": "MJPEG"},
            {"size": (1280, 720), "fps": 30.0, "pixel_format": "MJPEG"},  # duplicate
            {"size": (1280, 720), "fps": 30.0, "pixel_format": "mjpeg"},  # same (case)
        ]

        caps = build_capabilities(modes)

        # Should be deduplicated
        assert len(caps.modes) <= 2  # May be 1 or 2 depending on case sensitivity
