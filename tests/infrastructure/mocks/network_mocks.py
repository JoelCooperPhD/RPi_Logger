"""Mock network API for Pupil Labs Neon eye tracker testing.

Provides mock implementations of the Pupil Labs Realtime API for testing
without physical hardware.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple


@dataclass
class MockGazeData:
    """Mock gaze data sample."""
    timestamp_unix_seconds: float
    timestamp_unix_ns: int
    worn: bool = True
    x: float = 0.5
    y: float = 0.5
    pupil_diameter_left: float = 4.0
    pupil_diameter_right: float = 4.0

    # Per-eye coordinates
    @property
    def left(self):
        return type('Point', (), {'x': self.x - 0.05, 'y': self.y})()

    @property
    def right(self):
        return type('Point', (), {'x': self.x + 0.05, 'y': self.y})()

    # Extended attributes (may be None)
    eyeball_center_left_x: Optional[float] = None
    eyeball_center_left_y: Optional[float] = None
    eyeball_center_left_z: Optional[float] = None
    optical_axis_left_x: Optional[float] = None
    optical_axis_left_y: Optional[float] = None
    optical_axis_left_z: Optional[float] = None
    eyeball_center_right_x: Optional[float] = None
    eyeball_center_right_y: Optional[float] = None
    eyeball_center_right_z: Optional[float] = None
    optical_axis_right_x: Optional[float] = None
    optical_axis_right_y: Optional[float] = None
    optical_axis_right_z: Optional[float] = None
    eyelid_angle_top_left: Optional[float] = None
    eyelid_angle_bottom_left: Optional[float] = None
    eyelid_aperture_left: Optional[float] = None
    eyelid_angle_top_right: Optional[float] = None
    eyelid_angle_bottom_right: Optional[float] = None
    eyelid_aperture_right: Optional[float] = None


@dataclass
class MockIMUData:
    """Mock IMU data sample."""
    timestamp_unix_seconds: float
    timestamp_unix_ns: int
    gyro_data: Dict[str, float] = field(default_factory=lambda: {'x': 0.0, 'y': 0.0, 'z': 0.0})
    accel_data: Dict[str, float] = field(default_factory=lambda: {'x': 0.0, 'y': 0.0, 'z': -9.81})
    quaternion: Dict[str, float] = field(default_factory=lambda: {'w': 1.0, 'x': 0.0, 'y': 0.0, 'z': 0.0})
    temperature: float = 25.0


@dataclass
class MockEyeEvent:
    """Mock eye event (fixation, saccade, blink)."""
    timestamp_unix_seconds: float
    timestamp_unix_ns: int
    type: str = "fixation"  # fixation, saccade, blink
    event_type: str = "fixation"
    category: Optional[str] = None
    event_subtype: Optional[str] = None
    confidence: float = 0.95
    duration: float = 0.2
    start_time_ns: int = 0
    end_time_ns: int = 0
    start_gaze_x: float = 0.5
    start_gaze_y: float = 0.5
    end_gaze_x: float = 0.5
    end_gaze_y: float = 0.5
    mean_gaze_x: float = 0.5
    mean_gaze_y: float = 0.5
    amplitude_pixels: float = 0.0
    amplitude_angle_deg: float = 0.0
    mean_velocity: float = 0.0
    max_velocity: float = 0.0


@dataclass
class MockVideoFrame:
    """Mock video frame."""
    timestamp_unix_seconds: float
    timestamp_unix_ns: int
    data: bytes = b""
    width: int = 1088
    height: int = 1080

    @property
    def bgr_pixels(self):
        """Return BGR pixel data as numpy array."""
        import numpy as np
        return np.random.randint(0, 256, (self.height, self.width, 3), dtype=np.uint8)


@dataclass
class MockEyesFrame:
    """Mock eyes camera frame."""
    timestamp_unix_seconds: float
    timestamp_unix_ns: int
    data: bytes = b""
    width: int = 384
    height: int = 192

    @property
    def bgr_pixels(self):
        """Return BGR pixel data as numpy array."""
        import numpy as np
        return np.random.randint(0, 256, (self.height, self.width, 3), dtype=np.uint8)


class MockAudioFrame:
    """Mock audio frame."""

    def __init__(self, sample_rate: int = 16000, channels: int = 1):
        self.sample_rate = sample_rate
        self.channels = channels

        # Create mock av_frame
        self.av_frame = type('AVFrame', (), {
            'sample_rate': sample_rate,
            'layout': type('Layout', (), {'nb_channels': channels})(),
            'to_ndarray': self._to_ndarray,
        })()

    def _to_ndarray(self):
        import numpy as np
        # Generate 20ms of audio (320 samples at 16kHz)
        samples_per_frame = int(self.sample_rate * 0.02)
        return np.random.randn(self.channels, samples_per_frame).astype(np.float32) * 0.01


class MockDeviceInfo:
    """Mock Pupil Labs device information."""

    def __init__(
        self,
        serial: str = "MOCK001",
        name: str = "Mock Neon",
        ip: str = "192.168.1.100",
        port: int = 8080,
    ):
        self.serial = serial
        self.name = name
        self.phone_ip = ip
        self.phone_name = "MockPhone"
        self.dns_name = f"{serial}.local"
        self._port = port

    def direct_world_sensor_url(self) -> str:
        return f"rtsp://{self.phone_ip}:{self._port}/world"

    def direct_eyes_sensor_url(self) -> str:
        return f"rtsp://{self.phone_ip}:{self._port}/eyes"


class MockPupilNeonAPI:
    """Mock Pupil Labs Neon Realtime API.

    Provides a mock implementation of the pupil_labs.realtime_api
    for testing without hardware.

    Usage:
        api = MockPupilNeonAPI()
        api.start_streaming()

        async for gaze in api.receive_gaze():
            print(gaze.x, gaze.y)
    """

    def __init__(
        self,
        device: Optional[MockDeviceInfo] = None,
        gaze_rate: float = 200.0,  # Hz
        imu_rate: float = 200.0,  # Hz
        video_rate: float = 30.0,  # Hz
        eyes_rate: float = 200.0,  # Hz
    ):
        """Initialize mock API.

        Args:
            device: Mock device info
            gaze_rate: Gaze sample rate (Hz)
            imu_rate: IMU sample rate (Hz)
            video_rate: Video frame rate (Hz)
            eyes_rate: Eyes camera frame rate (Hz)
        """
        self.device = device or MockDeviceInfo()
        self.gaze_rate = gaze_rate
        self.imu_rate = imu_rate
        self.video_rate = video_rate
        self.eyes_rate = eyes_rate

        self._streaming = False
        self._stop_event = asyncio.Event()

        # Gaze simulation parameters
        self._gaze_x = 0.5
        self._gaze_y = 0.5
        self._gaze_velocity_x = 0.0
        self._gaze_velocity_y = 0.0

    async def connect(self) -> None:
        """Connect to the mock device."""
        await asyncio.sleep(0.1)  # Simulate connection delay

    async def disconnect(self) -> None:
        """Disconnect from the mock device."""
        self._streaming = False
        self._stop_event.set()

    def start_streaming(self) -> None:
        """Start streaming data."""
        self._streaming = True
        self._stop_event.clear()

    def stop_streaming(self) -> None:
        """Stop streaming data."""
        self._streaming = False
        self._stop_event.set()

    async def receive_gaze(self) -> AsyncIterator[MockGazeData]:
        """Receive gaze data stream.

        Yields:
            MockGazeData samples
        """
        interval = 1.0 / self.gaze_rate

        while self._streaming and not self._stop_event.is_set():
            timestamp = time.time()
            timestamp_ns = int(timestamp * 1e9)

            # Simulate eye movements
            self._update_gaze()

            yield MockGazeData(
                timestamp_unix_seconds=timestamp,
                timestamp_unix_ns=timestamp_ns,
                worn=True,
                x=self._gaze_x,
                y=self._gaze_y,
                pupil_diameter_left=3.5 + random.random() * 1.0,
                pupil_diameter_right=3.5 + random.random() * 1.0,
            )

            await asyncio.sleep(interval)

    async def receive_imu(self) -> AsyncIterator[MockIMUData]:
        """Receive IMU data stream.

        Yields:
            MockIMUData samples
        """
        interval = 1.0 / self.imu_rate

        while self._streaming and not self._stop_event.is_set():
            timestamp = time.time()
            timestamp_ns = int(timestamp * 1e9)

            yield MockIMUData(
                timestamp_unix_seconds=timestamp,
                timestamp_unix_ns=timestamp_ns,
                gyro_data={
                    'x': random.gauss(0, 0.01),
                    'y': random.gauss(0, 0.01),
                    'z': random.gauss(0, 0.01),
                },
                accel_data={
                    'x': random.gauss(0, 0.1),
                    'y': random.gauss(0, 0.1),
                    'z': -9.81 + random.gauss(0, 0.1),
                },
                quaternion={'w': 1.0, 'x': 0.0, 'y': 0.0, 'z': 0.0},
                temperature=25.0 + random.gauss(0, 0.5),
            )

            await asyncio.sleep(interval)

    async def receive_events(self) -> AsyncIterator[MockEyeEvent]:
        """Receive eye events stream.

        Yields:
            MockEyeEvent samples
        """
        event_types = ["fixation", "saccade", "blink"]
        last_event_time = time.time()
        min_interval = 0.1  # Minimum time between events

        while self._streaming and not self._stop_event.is_set():
            # Wait for a random interval
            await asyncio.sleep(random.uniform(0.1, 0.5))

            if not self._streaming:
                break

            timestamp = time.time()
            timestamp_ns = int(timestamp * 1e9)

            # Generate random event
            event_type = random.choice(event_types)
            duration = random.uniform(0.05, 0.5) if event_type == "fixation" else random.uniform(0.02, 0.1)
            start_ns = timestamp_ns - int(duration * 1e9)

            yield MockEyeEvent(
                timestamp_unix_seconds=timestamp,
                timestamp_unix_ns=timestamp_ns,
                type=event_type,
                event_type=event_type,
                confidence=random.uniform(0.8, 1.0),
                duration=duration,
                start_time_ns=start_ns,
                end_time_ns=timestamp_ns,
                start_gaze_x=self._gaze_x + random.gauss(0, 0.05),
                start_gaze_y=self._gaze_y + random.gauss(0, 0.05),
                end_gaze_x=self._gaze_x,
                end_gaze_y=self._gaze_y,
                mean_gaze_x=self._gaze_x,
                mean_gaze_y=self._gaze_y,
                amplitude_pixels=random.uniform(0, 100) if event_type == "saccade" else 0,
                amplitude_angle_deg=random.uniform(0, 30) if event_type == "saccade" else 0,
                mean_velocity=random.uniform(50, 500) if event_type == "saccade" else 0,
                max_velocity=random.uniform(100, 800) if event_type == "saccade" else 0,
            )

    async def receive_video(self) -> AsyncIterator[MockVideoFrame]:
        """Receive video frames.

        Yields:
            MockVideoFrame samples
        """
        interval = 1.0 / self.video_rate

        while self._streaming and not self._stop_event.is_set():
            timestamp = time.time()
            timestamp_ns = int(timestamp * 1e9)

            yield MockVideoFrame(
                timestamp_unix_seconds=timestamp,
                timestamp_unix_ns=timestamp_ns,
            )

            await asyncio.sleep(interval)

    async def receive_eyes(self) -> AsyncIterator[MockEyesFrame]:
        """Receive eyes camera frames.

        Yields:
            MockEyesFrame samples
        """
        interval = 1.0 / self.eyes_rate

        while self._streaming and not self._stop_event.is_set():
            timestamp = time.time()
            timestamp_ns = int(timestamp * 1e9)

            yield MockEyesFrame(
                timestamp_unix_seconds=timestamp,
                timestamp_unix_ns=timestamp_ns,
            )

            await asyncio.sleep(interval)

    async def receive_audio(self) -> AsyncIterator[MockAudioFrame]:
        """Receive audio frames.

        Yields:
            MockAudioFrame samples
        """
        interval = 0.02  # 20ms audio frames

        while self._streaming and not self._stop_event.is_set():
            yield MockAudioFrame()
            await asyncio.sleep(interval)

    def _update_gaze(self) -> None:
        """Update simulated gaze position."""
        # Add random drift to velocity
        self._gaze_velocity_x += random.gauss(0, 0.001)
        self._gaze_velocity_y += random.gauss(0, 0.001)

        # Apply velocity with damping
        self._gaze_x += self._gaze_velocity_x
        self._gaze_y += self._gaze_velocity_y
        self._gaze_velocity_x *= 0.95
        self._gaze_velocity_y *= 0.95

        # Keep gaze within bounds
        self._gaze_x = max(0.1, min(0.9, self._gaze_x))
        self._gaze_y = max(0.1, min(0.9, self._gaze_y))

        # Occasionally simulate saccade
        if random.random() < 0.01:
            self._gaze_x = random.uniform(0.2, 0.8)
            self._gaze_y = random.uniform(0.2, 0.8)


class MockDiscovery:
    """Mock device discovery."""

    def __init__(self, devices: Optional[List[MockDeviceInfo]] = None):
        """Initialize mock discovery.

        Args:
            devices: List of mock devices to "discover"
        """
        self.devices = devices or [MockDeviceInfo()]

    async def discover(self, timeout: float = 5.0) -> List[MockDeviceInfo]:
        """Discover mock devices.

        Args:
            timeout: Discovery timeout (simulated)

        Returns:
            List of discovered devices
        """
        await asyncio.sleep(min(0.5, timeout))  # Simulate discovery time
        return self.devices


# Module-level mock for pupil_labs.realtime_api
class MockRealtimeAPIModule:
    """Mock module for pupil_labs.realtime_api."""

    Device = MockPupilNeonAPI
    DeviceInfo = MockDeviceInfo
    GazeData = MockGazeData
    IMUData = MockIMUData
    EyeEvent = MockEyeEvent
    VideoFrame = MockVideoFrame
    AudioFrame = MockAudioFrame

    @staticmethod
    async def discover_devices(timeout: float = 5.0) -> List[MockDeviceInfo]:
        """Discover devices."""
        discovery = MockDiscovery()
        return await discovery.discover(timeout)
