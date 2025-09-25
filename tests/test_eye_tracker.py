import asyncio
import sys
import time
from collections import deque
from pathlib import Path
from types import SimpleNamespace


MODULE_ROOT = Path(__file__).resolve().parents[1] / "Modules" / "EyeTracker"
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

VENV_SITE_PACKAGES = Path(__file__).resolve().parents[1] / ".venv" / "lib" / "python3.11" / "site-packages"
if VENV_SITE_PACKAGES.exists() and str(VENV_SITE_PACKAGES) not in sys.path:
    sys.path.insert(0, str(VENV_SITE_PACKAGES))

import cv2
import numpy as np
import pytest

from config import Config  # type: ignore
from gaze_tracker import GazeTracker  # type: ignore
from recording_manager import RecordingManager, FrameTimingMetadata  # type: ignore
from stream_handler import FramePacket  # type: ignore


@pytest.mark.asyncio
async def test_recording_manager_records_video_and_gaze(tmp_path):
    config = Config(fps=5.0, resolution=(32, 24), output_dir=str(tmp_path))
    manager = RecordingManager(config, use_ffmpeg=False)

    await manager.start_recording()
    frame = np.zeros((24, 32, 3), dtype=np.uint8)

    try:
        for i in range(3):
            frame_value = (i * 20) % 255
            test_frame = np.full((24, 32, 3), frame_value, dtype=np.uint8)
            metadata = FrameTimingMetadata(
                capture_monotonic=time.perf_counter(),
                capture_unix=time.time(),
                camera_frame_index=i + 1,
                display_frame_index=i + 1,
                requested_fps=config.fps,
            )
            manager.write_frame(test_frame, metadata=metadata)
            gaze = SimpleNamespace(
                x=i / 10.0,
                y=0.5,
                worn=True,
                timestamp_unix_seconds=i / config.fps,
            )
            manager.write_gaze_sample(gaze)
            await asyncio.sleep(0)
    finally:
        await manager.stop_recording()

    video_path = Path(manager.recording_filename)
    gaze_path = Path(manager.gaze_filename)

    assert video_path.exists(), "Scene video was not created"
    assert gaze_path.exists(), "Gaze CSV was not created"

    fps = _probe_avg_fps(video_path)
    assert abs(fps - config.fps) < 0.25, f"Unexpected FPS {fps} for {video_path}"

    frame_count = _probe_frame_count(video_path)
    assert frame_count == 3, "Video frame count mismatch"

    csv_lines = gaze_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(csv_lines) == 4, "Gaze CSV missing samples"

    timing_path = Path(manager.frame_timing_filename)
    assert timing_path.exists(), "Frame timing CSV missing"
    timing_rows = timing_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(timing_rows) == 4  # header + 3 frames
    header = timing_rows[0].split(',')
    assert header[0] == "frame_number"
    first_row = timing_rows[1].split(',')
    assert first_row[3] == f"{1.0 / config.fps:.6f}"
    last_row = timing_rows[-1].split(',')
    assert last_row[0] == "3"


class DummyDeviceManager:
    def __init__(self):
        self._connected = False

    async def connect(self) -> bool:
        self._connected = True
        return True

    @property
    def is_connected(self) -> bool:
        return self._connected

    def get_rtsp_urls(self):
        return ("dummy-video", "dummy-gaze")

    async def cleanup(self):
        self._connected = False


class DummyStreamHandler:
    def __init__(self, frames, gazes):
        self._frames = deque(frames)
        self._gazes = deque(gazes)
        self.camera_frames = 0
        self.running = False
        self.tasks = []
        self._last_frame = None
        self._last_packet = None
        self._last_gaze = None

    async def start_streaming(self, *_args, **_kwargs):
        self.running = True
        return []

    async def stop_streaming(self):
        self.running = False
        self.tasks = []

    async def next_frame(self, timeout: float | None = None):
        await asyncio.sleep(0)
        if self._frames:
            self.camera_frames += 1
            frame = self._frames.popleft()
            packet = FramePacket(
                image=frame,
                received_monotonic=time.perf_counter(),
                timestamp_unix_seconds=time.time(),
                camera_frame_index=self.camera_frames,
            )
            self._last_frame = frame
            self._last_packet = packet
            return packet
        self.running = False
        return None

    def get_latest_frame(self):
        return self._last_frame

    def get_latest_frame_packet(self):
        return self._last_packet

    async def next_gaze(self, timeout: float | None = None):
        await asyncio.sleep(0)
        if self._gazes:
            self._last_gaze = self._gazes.popleft()
            return self._last_gaze
        return None

    def get_latest_gaze(self):
        return self._last_gaze

    def get_camera_fps(self):
        return 30.0


class FrameProcessorStub:
    def __init__(self, frames_before_quit: int):
        self.frames_before_quit = frames_before_quit
        self.check_calls = 0
        self.window_created = False
        self.window_destroyed = False
        self._quit_sent = False

    def process_frame(self, raw_frame):
        return raw_frame

    def add_overlays(self, frame, *_args, **_kwargs):
        return frame

    def display_frame(self, frame):
        return frame

    def create_window(self):
        self.window_created = True

    def destroy_windows(self):
        self.window_destroyed = True

    def check_keyboard(self):
        self.check_calls += 1
        if self.check_calls == 1:
            return "record"
        if not self._quit_sent and self.check_calls >= self.frames_before_quit:
            self._quit_sent = True
            return "quit"
        return None

    async def process_frame_async(self, raw_frame):
        return self.process_frame(raw_frame)

    async def add_overlays_async(self, frame, *args, **kwargs):
        return self.add_overlays(frame, *args, **kwargs)

    async def display_frame_async(self, frame):
        self.display_frame(frame)

    async def check_keyboard_async(self):
        return self.check_keyboard()


class RecordingManagerStub:
    def __init__(self):
        self.is_recording = False
        self.frames = []
        self.gaze_samples = []
        self.metadata = []
        self.recording_filename = "stub.mp4"
        self.gaze_filename = "stub.csv"

    async def toggle_recording(self):
        if self.is_recording:
            await self.stop_recording()
        else:
            await self.start_recording()

    async def start_recording(self):
        self.is_recording = True

    async def stop_recording(self):
        self.is_recording = False

    def write_frame(self, frame, metadata=None):
        if self.is_recording:
            self.frames.append(frame.copy())
            self.metadata.append(metadata)

    def write_gaze_sample(self, gaze):
        if self.is_recording and gaze is not None:
            self.gaze_samples.append(gaze)

    async def cleanup(self):
        await self.stop_recording()


@pytest.mark.asyncio
async def test_gaze_tracker_run_closes_and_records(tmp_path):
    frame_count = 5
    width, height = 64, 48
    frames = [np.full((height, width, 3), i * 10 % 255, dtype=np.uint8) for i in range(frame_count)]
    gazes = [
        SimpleNamespace(x=0.5, y=0.5, worn=True, timestamp_unix_seconds=i / 5.0)
        for i in range(frame_count)
    ]

    config = Config(fps=10.0, resolution=(width, height), output_dir=str(tmp_path), display_width=320)

    stream_handler = DummyStreamHandler(list(frames), list(gazes))
    frame_processor = FrameProcessorStub(frames_before_quit=frame_count)
    recording_manager = RecordingManagerStub()
    tracker = GazeTracker(
        config,
        device_manager=DummyDeviceManager(),
        stream_handler=stream_handler,
        frame_processor=frame_processor,
        recording_manager=recording_manager,
    )

    assert await tracker.connect()
    await tracker.run()

    assert not tracker.running
    assert frame_processor.window_created
    assert frame_processor.window_destroyed
    assert not stream_handler.running

    # Recording starts after the first frame toggles the record command.
    expected_frames = max(frame_count - 1, 0)
    assert len(recording_manager.frames) == expected_frames
    assert len(recording_manager.gaze_samples) == expected_frames


def _probe_avg_fps(video_path: Path) -> float:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        pytest.fail(f"Unable to open video: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        # Fallback: derive from timestamps if metadata missing
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        if duration <= 0:
            pytest.fail("Unable to determine FPS from video metadata")
        fps = frame_count / duration
    cap.release()
    return fps


def _probe_frame_count(video_path: Path) -> int:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        pytest.fail(f"Unable to open video: {video_path}")
    frame_count = 0
    while True:
        ret, _ = cap.read()
        if not ret:
            break
        frame_count += 1
    cap.release()
    return frame_count
