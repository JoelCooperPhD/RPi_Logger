import pytest
from pathlib import Path

from core import (
    AppState, CameraStatus, RecordingStatus,
    CameraSettings, CameraCapabilities, FrameMetrics,
    update,
    AssignCamera, CameraAssigned, CameraError, UnassignCamera,
    StartRecording, StopRecording, RecordingStarted, RecordingStopped,
    ApplySettings, Shutdown,
    ProbeCamera, OpenCamera, CloseCamera, StartCapture, StopCapture,
    StartEncoder, StopEncoder, StartTimingWriter, StopTimingWriter
)


class TestAssignCamera:
    def test_from_idle_transitions_to_assigning(self):
        state = AppState()
        new_state, effects = update(state, AssignCamera(0))

        assert new_state.camera_status == CameraStatus.ASSIGNING
        assert new_state.camera_index == 0
        assert len(effects) == 1
        assert isinstance(effects[0], ProbeCamera)
        assert effects[0].camera_index == 0

    def test_from_streaming_does_nothing(self):
        state = AppState(camera_status=CameraStatus.STREAMING)
        new_state, effects = update(state, AssignCamera(0))

        assert new_state.camera_status == CameraStatus.STREAMING
        assert effects == []


class TestCameraAssigned:
    def test_transitions_to_streaming(self):
        state = AppState(camera_status=CameraStatus.ASSIGNING, camera_index=0)
        caps = CameraCapabilities(camera_id="imx708")
        new_state, effects = update(state, CameraAssigned("imx708", 0, caps))

        assert new_state.camera_status == CameraStatus.STREAMING
        assert new_state.camera_id == "imx708"
        assert new_state.capabilities == caps
        assert any(isinstance(e, OpenCamera) for e in effects)
        assert any(isinstance(e, StartCapture) for e in effects)


class TestStartRecording:
    def test_from_streaming_starts_recording(self):
        state = AppState(
            camera_status=CameraStatus.STREAMING,
            settings=CameraSettings(resolution=(1920, 1080), frame_rate=5)
        )
        new_state, effects = update(state, StartRecording(Path("/data"), 1))

        assert new_state.recording_status == RecordingStatus.STARTING
        assert new_state.session_dir == Path("/data")
        assert new_state.trial_number == 1
        assert any(isinstance(e, StartEncoder) for e in effects)
        assert any(isinstance(e, StartTimingWriter) for e in effects)

    def test_from_idle_does_nothing(self):
        state = AppState(camera_status=CameraStatus.IDLE)
        new_state, effects = update(state, StartRecording(Path("/data"), 1))

        assert new_state.recording_status == RecordingStatus.STOPPED
        assert effects == []

    def test_while_already_recording_does_nothing(self):
        state = AppState(
            camera_status=CameraStatus.STREAMING,
            recording_status=RecordingStatus.RECORDING
        )
        new_state, effects = update(state, StartRecording(Path("/data"), 2))

        assert new_state.recording_status == RecordingStatus.RECORDING
        assert effects == []


class TestStopRecording:
    def test_while_recording_stops(self):
        state = AppState(
            camera_status=CameraStatus.STREAMING,
            recording_status=RecordingStatus.RECORDING
        )
        new_state, effects = update(state, StopRecording())

        assert new_state.recording_status == RecordingStatus.STOPPING
        assert any(isinstance(e, StopEncoder) for e in effects)
        assert any(isinstance(e, StopTimingWriter) for e in effects)


class TestUnassignCamera:
    def test_from_streaming_returns_to_idle(self):
        state = AppState(
            camera_status=CameraStatus.STREAMING,
            camera_id="imx708",
            camera_index=0
        )
        new_state, effects = update(state, UnassignCamera())

        assert new_state.camera_status == CameraStatus.IDLE
        assert new_state.camera_id is None
        assert new_state.camera_index is None
        assert any(isinstance(e, StopCapture) for e in effects)
        assert any(isinstance(e, CloseCamera) for e in effects)

    def test_while_recording_stops_recording_first(self):
        state = AppState(
            camera_status=CameraStatus.STREAMING,
            recording_status=RecordingStatus.RECORDING,
            camera_id="imx708"
        )
        new_state, effects = update(state, UnassignCamera())

        assert new_state.camera_status == CameraStatus.IDLE
        assert new_state.recording_status == RecordingStatus.STOPPED
        assert any(isinstance(e, StopEncoder) for e in effects)


class TestShutdown:
    def test_cleans_up_everything(self):
        state = AppState(
            camera_status=CameraStatus.STREAMING,
            recording_status=RecordingStatus.RECORDING
        )
        new_state, effects = update(state, Shutdown())

        assert new_state.camera_status == CameraStatus.IDLE
        assert new_state.recording_status == RecordingStatus.STOPPED
        assert any(isinstance(e, StopEncoder) for e in effects)
        assert any(isinstance(e, CloseCamera) for e in effects)
