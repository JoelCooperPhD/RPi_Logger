import pytest
from pathlib import Path

from core import (
    AppState, CameraStatus, RecordingStatus, CameraSettings,
    update, StartRecording, StartEncoder, StartTimingWriter
)


class TestMultiCameraPathUniqueness:
    """Tests that would have caught the multi-camera file collision bug.

    Bug: Both cameras wrote to session_dir/trial_001.avi because the path
    didn't include camera-specific identifiers.
    """

    def test_different_cameras_get_different_paths(self):
        """Two cameras with different indices must produce different output paths."""
        session_dir = Path("/data/session")
        trial = 1

        # Camera 0
        state0 = AppState(
            camera_status=CameraStatus.STREAMING,
            camera_id="imx708",
            camera_index=0,
            settings=CameraSettings()
        )
        _, effects0 = update(state0, StartRecording(session_dir, trial))

        # Camera 1
        state1 = AppState(
            camera_status=CameraStatus.STREAMING,
            camera_id="imx708",  # Same sensor model
            camera_index=1,      # Different index
            settings=CameraSettings()
        )
        _, effects1 = update(state1, StartRecording(session_dir, trial))

        # Extract encoder paths
        encoder0 = next(e for e in effects0 if isinstance(e, StartEncoder))
        encoder1 = next(e for e in effects1 if isinstance(e, StartEncoder))

        # Paths MUST be different
        assert encoder0.output_path != encoder1.output_path, \
            f"Camera 0 and 1 have same path: {encoder0.output_path}"

    def test_different_cameras_get_different_timing_paths(self):
        """Two cameras must have different timing CSV paths."""
        session_dir = Path("/data/session")
        trial = 1

        state0 = AppState(
            camera_status=CameraStatus.STREAMING,
            camera_index=0,
            settings=CameraSettings()
        )
        _, effects0 = update(state0, StartRecording(session_dir, trial))

        state1 = AppState(
            camera_status=CameraStatus.STREAMING,
            camera_index=1,
            settings=CameraSettings()
        )
        _, effects1 = update(state1, StartRecording(session_dir, trial))

        timing0 = next(e for e in effects0 if isinstance(e, StartTimingWriter))
        timing1 = next(e for e in effects1 if isinstance(e, StartTimingWriter))

        assert timing0.output_path != timing1.output_path, \
            f"Camera 0 and 1 have same timing path: {timing0.output_path}"

    def test_path_includes_camera_index(self):
        """Output path should contain camera index for identification."""
        session_dir = Path("/data/session")

        state = AppState(
            camera_status=CameraStatus.STREAMING,
            camera_index=2,
            settings=CameraSettings()
        )
        _, effects = update(state, StartRecording(session_dir, 1))

        encoder = next(e for e in effects if isinstance(e, StartEncoder))

        # Path should contain camera identifier
        path_str = str(encoder.output_path)
        assert "picam2" in path_str or "cam2" in path_str or "/2/" in path_str, \
            f"Path doesn't identify camera 2: {path_str}"

    def test_same_camera_same_trial_gets_same_path(self):
        """Same camera recording same trial should produce consistent path."""
        session_dir = Path("/data/session")

        state = AppState(
            camera_status=CameraStatus.STREAMING,
            camera_index=0,
            settings=CameraSettings()
        )

        _, effects1 = update(state, StartRecording(session_dir, 1))
        _, effects2 = update(state, StartRecording(session_dir, 1))

        encoder1 = next(e for e in effects1 if isinstance(e, StartEncoder))
        encoder2 = next(e for e in effects2 if isinstance(e, StartEncoder))

        assert encoder1.output_path == encoder2.output_path

    def test_different_trials_get_different_paths(self):
        """Same camera, different trials should produce different paths."""
        session_dir = Path("/data/session")

        state = AppState(
            camera_status=CameraStatus.STREAMING,
            camera_index=0,
            settings=CameraSettings()
        )

        _, effects1 = update(state, StartRecording(session_dir, 1))

        # Reset state to allow another recording
        state2 = AppState(
            camera_status=CameraStatus.STREAMING,
            camera_index=0,
            settings=CameraSettings()
        )
        _, effects2 = update(state2, StartRecording(session_dir, 2))

        encoder1 = next(e for e in effects1 if isinstance(e, StartEncoder))
        encoder2 = next(e for e in effects2 if isinstance(e, StartEncoder))

        assert encoder1.output_path != encoder2.output_path
