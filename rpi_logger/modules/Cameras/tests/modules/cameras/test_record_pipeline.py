import asyncio
import types
import time

import pytest
import numpy as np

from rpi_logger.modules.Cameras.runtime import CameraId, CapabilityMode, ModeSelection
from rpi_logger.modules.Cameras.runtime.record.pipeline import RecordPipeline
from rpi_logger.modules.Cameras.runtime.record.recorder import Recorder
from rpi_logger.modules.Cameras.storage import DiskGuard, resolve_session_paths


class DummyRecorder:
    def __init__(self):
        self.enqueued = 0
        self.started = False
        self.stopped = False

    async def start(self, camera_id, session_paths, selection, metadata_builder, csv_logger):
        self.started = True
        return types.SimpleNamespace(queue=asyncio.Queue())

    async def enqueue(self, handle, frame, *, timestamp, pts_time_ns=None):
        self.enqueued += 1

    async def stop(self, handle):
        self.stopped = True


class FakeClock:
    def __init__(self) -> None:
        self._t = 0.0

    def advance(self, delta: float) -> None:
        self._t += delta

    def __call__(self) -> float:
        return self._t


@pytest.mark.asyncio
async def test_record_pipeline_enqueues_and_stops(tmp_path):
    recorder = DummyRecorder()
    disk_guard = DiskGuard(threshold_gb=0.0)  # always ok
    pipeline = RecordPipeline(recorder, disk_guard)

    cam_id = CameraId(backend="usb", stable_id="cam0")
    selection = ModeSelection(mode=CapabilityMode(size=(640, 480), fps=30, pixel_format="RGB"), target_fps=None)
    queue: asyncio.Queue = asyncio.Queue()
    session_paths = resolve_session_paths(tmp_path, "test_session", cam_id, module_name="Cameras", module_code="CAM")

    pipeline.start(
        cam_id,
        queue,
        selection,
        session_paths=session_paths,
        metadata_builder=lambda: {},
        csv_logger=None,
        trial_number=1,
    )

    await queue.put(types.SimpleNamespace(data=None, frame_number=1))
    await queue.put(None)
    await asyncio.sleep(0.2)

    assert recorder.started
    assert recorder.enqueued >= 1
    await pipeline.stop(cam_id)
    assert recorder.stopped


@pytest.mark.asyncio
async def test_record_pipeline_caps_output_fps(tmp_path):
    recorder = DummyRecorder()
    disk_guard = DiskGuard(threshold_gb=0.0)
    clock = FakeClock()
    pipeline = RecordPipeline(recorder, disk_guard, clock=clock)

    cam_id = CameraId(backend="usb", stable_id="cam1")
    selection = ModeSelection(mode=CapabilityMode(size=(640, 480), fps=60, pixel_format="RGB"), target_fps=30.0)
    queue: asyncio.Queue = asyncio.Queue()
    session_paths = resolve_session_paths(tmp_path, "test_session", cam_id, module_name="Cameras", module_code="CAM")

    pipeline.start(
        cam_id,
        queue,
        selection,
        session_paths=session_paths,
        metadata_builder=lambda: {},
        csv_logger=None,
        trial_number=1,
    )

    async def produce():
        for _ in range(60):  # simulate ~1s of 60 fps input
            clock.advance(1 / 60)
            await queue.put(types.SimpleNamespace(data=None))
            await asyncio.sleep(0)
        await queue.put(None)

    await produce()
    await asyncio.sleep(0.2)
    assert recorder.started
    # Expect roughly half the frames to make it through the 30 fps limiter.
    assert 20 <= recorder.enqueued <= 35
    await pipeline.stop(cam_id)
    assert recorder.stopped


@pytest.mark.asyncio
async def test_recorder_uses_target_fps(monkeypatch, tmp_path):
    captured = {}

    class FakeWriter:
        def __init__(self, path, fourcc, fps, size):
            captured["fps"] = fps

        def write(self, frame):
            return None

        def release(self):
            return None

    monkeypatch.setattr("rpi_logger.modules.Cameras.runtime.record.recorder.cv2.VideoWriter", FakeWriter)

    recorder = Recorder(queue_size=2, use_pyav=False)
    cam_id = CameraId(backend="usb", stable_id="cam2")
    selection = ModeSelection(mode=CapabilityMode(size=(640, 480), fps=60, pixel_format="RGB"), target_fps=24.0)
    session_paths = resolve_session_paths(tmp_path, "test_session", cam_id, module_name="Cameras", module_code="CAM")

    handle = await recorder.start(cam_id, session_paths, selection, metadata_builder=lambda: {}, csv_logger=None)
    await recorder.stop(handle)
    await asyncio.sleep(0.05)

    assert captured["fps"] == 24.0


@pytest.mark.asyncio
async def test_recorder_pyav_uses_sensor_timestamps(monkeypatch, tmp_path):
    encoded_pts = []
    muxed = []

    class DummyPacket:
        def __init__(self, pts):
            self.pts = pts

    class DummyVideoFrame:
        def __init__(self, arr, format):
            self.arr = arr
            self.format = format
            self.pts = None
            self.time_base = None

        @classmethod
        def from_ndarray(cls, arr, format="bgr24"):
            return cls(arr, format)

    class DummyStream:
        def __init__(self):
            self.pix_fmt = None
            self.width = None
            self.height = None
            self.time_base = None
            self.average_rate = None
            self.codec_context = types.SimpleNamespace(time_base=None, framerate=None)

        def encode(self, frame=None):
            if frame is None:
                return []
            encoded_pts.append(frame.pts)
            return [DummyPacket(frame.pts)]

    class DummyContainer:
        def add_stream(self, _codec):
            return DummyStream()

        def mux(self, packet):
            muxed.append(getattr(packet, "pts", packet))

        def close(self):
            return None

    dummy_av = types.SimpleNamespace(VideoFrame=DummyVideoFrame, open=lambda *_args, **_kwargs: DummyContainer())

    monkeypatch.setattr("rpi_logger.modules.Cameras.runtime.record.recorder.av", dummy_av)
    monkeypatch.setattr("rpi_logger.modules.Cameras.runtime.record.recorder._HAS_PYAV", True)

    recorder = Recorder(queue_size=2, use_pyav=True)
    cam_id = CameraId(backend="usb", stable_id="cam_pyav")
    selection = ModeSelection(mode=CapabilityMode(size=(320, 240), fps=30, pixel_format="RGB"), target_fps=None)
    session_paths = resolve_session_paths(tmp_path, "test_session", cam_id, module_name="Cameras", module_code="CAM")

    handle = await recorder.start(cam_id, session_paths, selection, metadata_builder=lambda: {}, csv_logger=None)
    await recorder.enqueue(handle, np.zeros((2, 2, 3), dtype=np.uint8), timestamp=1.0, pts_time_ns=1_000_000_100)
    await recorder.enqueue(handle, np.zeros((2, 2, 3), dtype=np.uint8), timestamp=1.1, pts_time_ns=1_000_001_100)
    await recorder.stop(handle)

    assert handle.kind == "pyav"
    # PTS values should start at zero and advance based on the supplied nanosecond timestamps (microsecond ticks).
    assert encoded_pts == [0, 1]
    assert muxed  # packets were muxed


@pytest.mark.asyncio
async def test_record_pipeline_writes_timing_csv(tmp_path):
    recorder = DummyRecorder()
    disk_guard = DiskGuard(threshold_gb=0.0)  # always ok
    pipeline = RecordPipeline(recorder, disk_guard)

    cam_id = CameraId(backend="usb", stable_id="cam_csv")
    selection = ModeSelection(mode=CapabilityMode(size=(640, 480), fps=30, pixel_format="RGB"), target_fps=None)
    queue: asyncio.Queue = asyncio.Queue()
    session_paths = resolve_session_paths(tmp_path, "test_session", cam_id, module_name="Cameras", module_code="CAM")

    pipeline.start(
        cam_id,
        queue,
        selection,
        session_paths=session_paths,
        metadata_builder=lambda: {},
        trial_number=1,
    )

    await queue.put(types.SimpleNamespace(data=None, frame_number=5, timestamp=time.time()))
    await queue.put(None)
    await asyncio.sleep(0.25)
    await pipeline.stop(cam_id)

    csv_files = list(session_paths.camera_dir.glob("*frame_timing.csv"))
    assert csv_files, "Timing CSV was not created"
    lines = csv_files[0].read_text().strip().splitlines()
    assert lines[0].startswith("trial,frame_number,write_time_unix")
    assert len(lines) >= 2
