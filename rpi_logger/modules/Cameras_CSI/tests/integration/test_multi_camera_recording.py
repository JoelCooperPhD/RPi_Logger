import pytest
import asyncio
import tempfile
from pathlib import Path
from dataclasses import dataclass
import time

from core import (
    AppState, CameraStatus, RecordingStatus, CameraSettings, CameraCapabilities,
    Store, create_store, initial_state,
    AssignCamera, CameraAssigned, StartRecording, StopRecording,
    RecordingStarted, RecordingStopped,
    Effect, StartEncoder, StartTimingWriter, StopEncoder, StopTimingWriter
)


@dataclass
class MockFrame:
    """Mock captured frame."""
    wall_time: float
    monotonic_ns: int
    sensor_timestamp_ns: int
    data: bytes
    size: tuple[int, int]
    color_format: str = "rgb"


class RecordingEffectExecutor:
    """Effect executor that tracks recording paths."""

    def __init__(self):
        self.video_paths: list[Path] = []
        self.timing_paths: list[Path] = []
        self.executed_effects: list[Effect] = []

    async def __call__(self, effect: Effect, dispatch) -> None:
        self.executed_effects.append(effect)

        if isinstance(effect, StartEncoder):
            self.video_paths.append(effect.output_path)
            await dispatch(RecordingStarted())
        elif isinstance(effect, StartTimingWriter):
            self.timing_paths.append(effect.output_path)
        elif isinstance(effect, StopEncoder):
            await dispatch(RecordingStopped())


class TestMultiCameraRecordingIntegration:
    """Integration tests for multi-camera recording scenarios.

    These tests simulate the full workflow of multiple cameras recording
    simultaneously and verify they don't interfere with each other.
    """

    @pytest.mark.asyncio
    async def test_two_cameras_produce_unique_video_paths(self):
        """Two cameras recording simultaneously must create separate video files."""
        session_dir = Path("/data/session_001")

        # Create two independent stores (simulating two camera instances)
        store0 = create_store(initial_state())
        store1 = create_store(initial_state())

        executor0 = RecordingEffectExecutor()
        executor1 = RecordingEffectExecutor()

        store0.set_effect_handler(executor0)
        store1.set_effect_handler(executor1)

        # Assign cameras
        caps0 = CameraCapabilities(camera_id="imx708")
        caps1 = CameraCapabilities(camera_id="imx708")  # Same sensor model

        await store0.dispatch(CameraAssigned("imx708", 0, caps0))
        await store1.dispatch(CameraAssigned("imx708", 1, caps1))

        # Start recording on both
        await store0.dispatch(StartRecording(session_dir, trial=1))
        await store1.dispatch(StartRecording(session_dir, trial=1))

        # Both should be recording
        assert store0.state.recording_status == RecordingStatus.RECORDING
        assert store1.state.recording_status == RecordingStatus.RECORDING

        # Video paths must be different
        assert len(executor0.video_paths) == 1
        assert len(executor1.video_paths) == 1
        assert executor0.video_paths[0] != executor1.video_paths[0], \
            f"Both cameras have same video path: {executor0.video_paths[0]}"

    @pytest.mark.asyncio
    async def test_two_cameras_produce_unique_timing_paths(self):
        """Two cameras must have separate timing CSV files."""
        session_dir = Path("/data/session_001")

        store0 = create_store(initial_state())
        store1 = create_store(initial_state())

        executor0 = RecordingEffectExecutor()
        executor1 = RecordingEffectExecutor()

        store0.set_effect_handler(executor0)
        store1.set_effect_handler(executor1)

        caps = CameraCapabilities(camera_id="imx708")
        await store0.dispatch(CameraAssigned("imx708", 0, caps))
        await store1.dispatch(CameraAssigned("imx708", 1, caps))

        await store0.dispatch(StartRecording(session_dir, trial=1))
        await store1.dispatch(StartRecording(session_dir, trial=1))

        # Timing paths must be different
        assert len(executor0.timing_paths) == 1
        assert len(executor1.timing_paths) == 1
        assert executor0.timing_paths[0] != executor1.timing_paths[0], \
            f"Both cameras have same timing path: {executor0.timing_paths[0]}"

    @pytest.mark.asyncio
    async def test_camera_paths_contain_identifier(self):
        """Output paths should clearly identify which camera they belong to."""
        session_dir = Path("/data/session_001")

        store = create_store(initial_state())
        executor = RecordingEffectExecutor()
        store.set_effect_handler(executor)

        caps = CameraCapabilities(camera_id="imx708")
        await store.dispatch(CameraAssigned("imx708", 3, caps))
        await store.dispatch(StartRecording(session_dir, trial=1))

        video_path = executor.video_paths[0]
        path_str = str(video_path)

        # Should contain camera identifier (index 3)
        assert "picam3" in path_str or "cam3" in path_str or "/3/" in path_str, \
            f"Path doesn't identify camera 3: {path_str}"

    @pytest.mark.asyncio
    async def test_paths_organized_in_subdirectories(self):
        """Each camera should have its own subdirectory."""
        session_dir = Path("/data/session_001")

        store0 = create_store(initial_state())
        store1 = create_store(initial_state())

        executor0 = RecordingEffectExecutor()
        executor1 = RecordingEffectExecutor()

        store0.set_effect_handler(executor0)
        store1.set_effect_handler(executor1)

        caps = CameraCapabilities(camera_id="imx708")
        await store0.dispatch(CameraAssigned("imx708", 0, caps))
        await store1.dispatch(CameraAssigned("imx708", 1, caps))

        await store0.dispatch(StartRecording(session_dir, trial=1))
        await store1.dispatch(StartRecording(session_dir, trial=1))

        # Paths should be in different subdirectories
        video0_parent = executor0.video_paths[0].parent
        video1_parent = executor1.video_paths[0].parent

        assert video0_parent != video1_parent, \
            "Both cameras recording to same directory"
        assert video0_parent.parent == session_dir or video0_parent == session_dir.parent, \
            "Camera 0 not in expected session directory structure"

    @pytest.mark.asyncio
    async def test_four_cameras_all_unique_paths(self):
        """Stress test: 4 cameras should all have unique paths."""
        session_dir = Path("/data/session_001")
        n_cameras = 4

        stores = [create_store(initial_state()) for _ in range(n_cameras)]
        executors = [RecordingEffectExecutor() for _ in range(n_cameras)]

        for store, executor in zip(stores, executors):
            store.set_effect_handler(executor)

        caps = CameraCapabilities(camera_id="imx708")
        for i, store in enumerate(stores):
            await store.dispatch(CameraAssigned("imx708", i, caps))
            await store.dispatch(StartRecording(session_dir, trial=1))

        # Collect all paths
        all_video_paths = [e.video_paths[0] for e in executors]
        all_timing_paths = [e.timing_paths[0] for e in executors]

        # All should be unique
        assert len(set(all_video_paths)) == n_cameras, \
            f"Duplicate video paths found: {all_video_paths}"
        assert len(set(all_timing_paths)) == n_cameras, \
            f"Duplicate timing paths found: {all_timing_paths}"


class TestMultiCameraRecordingWithRealFiles:
    """Integration tests that create real files to verify end-to-end behavior."""

    @pytest.mark.asyncio
    async def test_real_files_created_in_separate_directories(self):
        """Verify actual file creation in separate directories."""
        import numpy as np
        from recording.session import RecordingSession

        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)

            # Create two recording sessions with different camera dirs
            session0 = RecordingSession(
                session_dir=base_dir / "picam0",
                trial_number=1,
                device_id="cam0",
                resolution=(640, 480),
                fps=5
            )
            session1 = RecordingSession(
                session_dir=base_dir / "picam1",
                trial_number=1,
                device_id="cam1",
                resolution=(640, 480),
                fps=5
            )

            # Start both
            await session0.start()
            await session1.start()

            # Write frames to both (need numpy array for cv2.VideoWriter)
            for i in range(3):
                frame_data = np.zeros((480, 640, 3), dtype=np.uint8)
                frame = MockFrame(
                    wall_time=time.time(),
                    monotonic_ns=time.monotonic_ns(),
                    sensor_timestamp_ns=i * 1000000,
                    data=frame_data,
                    size=(640, 480)
                )
                await session0.write_frame(frame)
                await session1.write_frame(frame)

            # Stop both
            await session0.stop()
            await session1.stop()

            # Verify files exist in separate directories
            assert (base_dir / "picam0" / "trial_001.avi").exists()
            assert (base_dir / "picam1" / "trial_001.avi").exists()
            assert (base_dir / "picam0" / "trial_001_timing.csv").exists()
            assert (base_dir / "picam1" / "trial_001_timing.csv").exists()

            # Verify timing files have content
            timing0 = (base_dir / "picam0" / "trial_001_timing.csv").read_text()
            timing1 = (base_dir / "picam1" / "trial_001_timing.csv").read_text()

            assert len(timing0.strip().split('\n')) == 4  # header + 3 frames
            assert len(timing1.strip().split('\n')) == 4
