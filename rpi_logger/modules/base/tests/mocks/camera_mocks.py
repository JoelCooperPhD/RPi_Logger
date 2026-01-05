"""Mock camera backend for testing Cameras and CSICameras modules.

Provides mock implementations of V4L2 and Picamera2 backends for testing
without physical camera hardware.
"""

from __future__ import annotations

import numpy as np
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union


@dataclass
class MockCameraMode:
    """Represents a camera mode (resolution + FPS)."""
    width: int
    height: int
    fps: float
    format: str = "YUYV"


@dataclass
class MockCameraCapabilities:
    """Mock camera capabilities."""
    modes: List[MockCameraMode] = field(default_factory=list)
    controls: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    hw_model: str = "Mock Camera"
    stable_id: str = "mock_camera_0"

    def __post_init__(self):
        if not self.modes:
            self.modes = [
                MockCameraMode(1920, 1080, 30.0),
                MockCameraMode(1280, 720, 60.0),
                MockCameraMode(640, 480, 30.0),
            ]
        if not self.controls:
            self.controls = {
                "brightness": {"min": 0, "max": 255, "default": 128, "value": 128},
                "contrast": {"min": 0, "max": 255, "default": 128, "value": 128},
                "saturation": {"min": 0, "max": 255, "default": 128, "value": 128},
            }


@dataclass
class MockCameraFrame:
    """A mock camera frame."""
    data: np.ndarray
    timestamp: float
    frame_number: int


class MockCameraBackend:
    """Mock camera backend for testing.

    Provides a video capture interface compatible with OpenCV's VideoCapture.
    Generates synthetic test frames.
    """

    # Class-level registry of available mock cameras
    _cameras: Dict[str, MockCameraCapabilities] = {
        "/dev/video0": MockCameraCapabilities(stable_id="mock_usb_camera_0", hw_model="Mock USB Camera"),
        "/dev/video2": MockCameraCapabilities(stable_id="mock_usb_camera_1", hw_model="Mock USB Camera 2"),
    }

    def __init__(
        self,
        device_path: str = "/dev/video0",
        width: int = 1920,
        height: int = 1080,
        fps: float = 30.0,
    ):
        """Initialize mock camera.

        Args:
            device_path: Device path (e.g., "/dev/video0")
            width: Frame width
            height: Frame height
            fps: Target frame rate
        """
        self.device_path = device_path
        self.width = width
        self.height = height
        self.fps = fps

        self._is_opened = False
        self._frame_number = 0
        self._start_time = 0.0

        # Frame generation settings
        self._generate_pattern = "color_bars"  # color_bars, noise, solid, gradient
        self._solid_color = (128, 128, 128)

        # Capabilities
        self.capabilities = self._cameras.get(device_path, MockCameraCapabilities())

    @classmethod
    def list_devices(cls) -> List[str]:
        """List available mock camera devices."""
        return list(cls._cameras.keys())

    @classmethod
    def add_mock_camera(cls, device_path: str, capabilities: Optional[MockCameraCapabilities] = None) -> None:
        """Add a mock camera to the registry.

        Args:
            device_path: Device path
            capabilities: Optional capabilities (uses defaults if not provided)
        """
        cls._cameras[device_path] = capabilities or MockCameraCapabilities(
            stable_id=f"mock_camera_{len(cls._cameras)}",
            hw_model=f"Mock Camera {len(cls._cameras)}",
        )

    @classmethod
    def clear_mock_cameras(cls) -> None:
        """Clear all mock cameras and restore defaults."""
        cls._cameras = {
            "/dev/video0": MockCameraCapabilities(stable_id="mock_usb_camera_0"),
        }

    def open(self) -> bool:
        """Open the mock camera.

        Returns:
            True if successful
        """
        if self.device_path not in self._cameras:
            return False

        self._is_opened = True
        self._frame_number = 0
        self._start_time = time.time()
        return True

    def release(self) -> None:
        """Release the mock camera."""
        self._is_opened = False

    def isOpened(self) -> bool:
        """Check if camera is opened."""
        return self._is_opened

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Read a frame from the mock camera.

        Returns:
            Tuple of (success, frame)
        """
        if not self._is_opened:
            return False, None

        frame = self._generate_frame()
        self._frame_number += 1

        # Simulate frame rate
        expected_time = self._start_time + (self._frame_number / self.fps)
        current_time = time.time()
        if current_time < expected_time:
            time.sleep(expected_time - current_time)

        return True, frame

    def set(self, prop_id: int, value: float) -> bool:
        """Set a camera property.

        Args:
            prop_id: OpenCV property ID
            value: Property value

        Returns:
            True if successful
        """
        # Common OpenCV property IDs
        CV_CAP_PROP_FRAME_WIDTH = 3
        CV_CAP_PROP_FRAME_HEIGHT = 4
        CV_CAP_PROP_FPS = 5

        if prop_id == CV_CAP_PROP_FRAME_WIDTH:
            self.width = int(value)
            return True
        elif prop_id == CV_CAP_PROP_FRAME_HEIGHT:
            self.height = int(value)
            return True
        elif prop_id == CV_CAP_PROP_FPS:
            self.fps = float(value)
            return True

        return False

    def get(self, prop_id: int) -> float:
        """Get a camera property.

        Args:
            prop_id: OpenCV property ID

        Returns:
            Property value
        """
        CV_CAP_PROP_FRAME_WIDTH = 3
        CV_CAP_PROP_FRAME_HEIGHT = 4
        CV_CAP_PROP_FPS = 5

        if prop_id == CV_CAP_PROP_FRAME_WIDTH:
            return float(self.width)
        elif prop_id == CV_CAP_PROP_FRAME_HEIGHT:
            return float(self.height)
        elif prop_id == CV_CAP_PROP_FPS:
            return float(self.fps)

        return 0.0

    def _generate_frame(self) -> np.ndarray:
        """Generate a synthetic test frame.

        Returns:
            BGR frame as numpy array
        """
        if self._generate_pattern == "color_bars":
            return self._generate_color_bars()
        elif self._generate_pattern == "noise":
            return self._generate_noise()
        elif self._generate_pattern == "solid":
            return self._generate_solid()
        elif self._generate_pattern == "gradient":
            return self._generate_gradient()
        else:
            return self._generate_color_bars()

    def _generate_color_bars(self) -> np.ndarray:
        """Generate SMPTE color bars test pattern."""
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)

        # Define color bar colors (BGR format)
        colors = [
            (255, 255, 255),  # White
            (0, 255, 255),    # Yellow
            (255, 255, 0),    # Cyan
            (0, 255, 0),      # Green
            (255, 0, 255),    # Magenta
            (0, 0, 255),      # Red
            (255, 0, 0),      # Blue
        ]

        bar_width = self.width // len(colors)

        for i, color in enumerate(colors):
            x_start = i * bar_width
            x_end = (i + 1) * bar_width if i < len(colors) - 1 else self.width
            frame[:, x_start:x_end] = color

        # Add frame number overlay
        self._add_frame_number(frame)

        return frame

    def _generate_noise(self) -> np.ndarray:
        """Generate random noise pattern."""
        frame = np.random.randint(0, 256, (self.height, self.width, 3), dtype=np.uint8)
        self._add_frame_number(frame)
        return frame

    def _generate_solid(self) -> np.ndarray:
        """Generate solid color frame."""
        frame = np.full((self.height, self.width, 3), self._solid_color, dtype=np.uint8)
        self._add_frame_number(frame)
        return frame

    def _generate_gradient(self) -> np.ndarray:
        """Generate gradient test pattern."""
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)

        # Horizontal gradient
        for x in range(self.width):
            value = int(255 * x / self.width)
            frame[:, x] = (value, value, value)

        self._add_frame_number(frame)
        return frame

    def _add_frame_number(self, frame: np.ndarray) -> None:
        """Add frame number overlay to frame.

        Args:
            frame: Frame to modify in place
        """
        # Simple text overlay using basic drawing
        # In real tests, you might use cv2.putText
        text = f"F:{self._frame_number:06d}"

        # Draw a black background box
        frame[10:30, 10:150] = (0, 0, 0)

        # Note: For actual text rendering, cv2.putText would be used
        # This is a simplified version that doesn't require OpenCV

    def set_pattern(self, pattern: str) -> None:
        """Set the frame generation pattern.

        Args:
            pattern: One of "color_bars", "noise", "solid", "gradient"
        """
        self._generate_pattern = pattern

    def set_solid_color(self, bgr: Tuple[int, int, int]) -> None:
        """Set the solid color for solid pattern.

        Args:
            bgr: BGR color tuple
        """
        self._solid_color = bgr


class MockVideoCapture:
    """OpenCV VideoCapture-compatible mock.

    Drop-in replacement for cv2.VideoCapture.
    """

    def __init__(self, source: Union[str, int] = 0, apiPreference: int = 0):
        """Initialize mock video capture.

        Args:
            source: Device path or index
            apiPreference: API backend preference (ignored)
        """
        if isinstance(source, int):
            devices = MockCameraBackend.list_devices()
            if source < len(devices):
                source = devices[source]
            else:
                source = f"/dev/video{source}"

        self._backend = MockCameraBackend(device_path=source)
        self._backend.open()

    def isOpened(self) -> bool:
        return self._backend.isOpened()

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        return self._backend.read()

    def release(self) -> None:
        self._backend.release()

    def set(self, prop_id: int, value: float) -> bool:
        return self._backend.set(prop_id, value)

    def get(self, prop_id: int) -> float:
        return self._backend.get(prop_id)


class MockPicamera2:
    """Mock Picamera2 for CSI camera testing.

    Provides a Picamera2-compatible interface for testing without hardware.
    """

    def __init__(self, camera_num: int = 0):
        """Initialize mock Picamera2.

        Args:
            camera_num: Camera number (0 or 1)
        """
        self.camera_num = camera_num
        self._started = False
        self._configured = False
        self._config: Dict[str, Any] = {}

        # Default configuration
        self._main_size = (1920, 1080)
        self._format = "RGB888"

    def create_video_configuration(
        self,
        main: Optional[Dict[str, Any]] = None,
        lores: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Create a video configuration.

        Args:
            main: Main stream configuration
            lores: Low-resolution stream configuration
            **kwargs: Additional configuration

        Returns:
            Configuration dictionary
        """
        config = {
            "main": main or {"size": self._main_size, "format": self._format},
            "lores": lores,
        }
        config.update(kwargs)
        return config

    def configure(self, config: Dict[str, Any]) -> None:
        """Configure the camera.

        Args:
            config: Configuration dictionary
        """
        self._config = config
        if "main" in config and "size" in config["main"]:
            self._main_size = config["main"]["size"]
        self._configured = True

    def start(self) -> None:
        """Start the camera."""
        if not self._configured:
            raise RuntimeError("Camera not configured")
        self._started = True

    def stop(self) -> None:
        """Stop the camera."""
        self._started = False

    def close(self) -> None:
        """Close the camera."""
        self.stop()

    def capture_array(self, name: str = "main") -> np.ndarray:
        """Capture a frame as numpy array.

        Args:
            name: Stream name ("main" or "lores")

        Returns:
            Frame as numpy array
        """
        if not self._started:
            raise RuntimeError("Camera not started")

        width, height = self._main_size
        if self._format == "RGB888":
            return np.random.randint(0, 256, (height, width, 3), dtype=np.uint8)
        elif self._format == "YUV420":
            return np.random.randint(0, 256, (height * 3 // 2, width), dtype=np.uint8)
        else:
            return np.random.randint(0, 256, (height, width, 3), dtype=np.uint8)

    @property
    def camera_properties(self) -> Dict[str, Any]:
        """Get camera properties."""
        return {
            "Model": f"Mock CSI Camera {self.camera_num}",
            "PixelArraySize": self._main_size,
        }

    @staticmethod
    def global_camera_info() -> List[Dict[str, Any]]:
        """Get info about all available cameras."""
        return [
            {"Model": "Mock CSI Camera 0", "Num": 0},
        ]
