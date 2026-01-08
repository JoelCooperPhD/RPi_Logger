from dataclasses import replace
from pathlib import Path

from .state import AppState, CameraStatus, RecordingStatus, FrameMetrics
from .actions import (
    Action, AssignCamera, CameraAssigned, CameraError, UnassignCamera,
    StartPreview, StopPreview,
    StartRecording, StopRecording, RecordingStarted, RecordingStopped,
    ApplySettings, SettingsApplied,
    FrameReceived, UpdateMetrics, PreviewFrameReady,
    Shutdown
)
from .effects import (
    Effect, ProbeCamera, OpenCamera, CloseCamera,
    StartCapture, StopCapture,
    StartEncoder, StopEncoder,
    StartTimingWriter, StopTimingWriter,
    ApplyCameraSettings, SendStatus, CleanupResources
)


def update(state: AppState, action: Action) -> tuple[AppState, list[Effect]]:
    match action:
        case AssignCamera(camera_index):
            if state.camera_status != CameraStatus.IDLE:
                return state, []
            return (
                replace(state, camera_status=CameraStatus.ASSIGNING, camera_index=camera_index),
                [ProbeCamera(camera_index)]
            )

        case CameraAssigned(camera_id, camera_index, capabilities):
            return (
                replace(
                    state,
                    camera_status=CameraStatus.STREAMING,
                    camera_id=camera_id,
                    camera_index=camera_index,
                    capabilities=capabilities,
                    error_message=None
                ),
                [
                    OpenCamera(camera_index, state.settings),
                    StartCapture(),
                    SendStatus("camera_assigned", {"camera_id": camera_id})
                ]
            )

        case CameraError(message):
            return (
                replace(
                    state,
                    camera_status=CameraStatus.ERROR,
                    error_message=message
                ),
                [SendStatus("error", {"message": message})]
            )

        case UnassignCamera():
            if state.camera_status == CameraStatus.IDLE:
                return state, []
            effects: list[Effect] = [StopCapture(), CloseCamera()]
            if state.recording_status == RecordingStatus.RECORDING:
                effects.extend([StopEncoder(), StopTimingWriter()])
            effects.append(SendStatus("camera_unassigned", {}))
            return (
                replace(
                    state,
                    camera_status=CameraStatus.IDLE,
                    recording_status=RecordingStatus.STOPPED,
                    camera_id=None,
                    camera_index=None,
                    capabilities=None,
                    metrics=FrameMetrics()
                ),
                effects
            )

        case StartPreview():
            if state.camera_status != CameraStatus.STREAMING:
                return state, []
            return state, [StartCapture()]

        case StopPreview():
            return state, [StopCapture()]

        case StartRecording(session_dir, trial):
            if state.camera_status != CameraStatus.STREAMING:
                return state, []
            if state.recording_status != RecordingStatus.STOPPED:
                return state, []
            camera_idx = state.camera_index if state.camera_index is not None else 0
            camera_dir = session_dir / f"picam{camera_idx}"
            video_path = camera_dir / f"trial_{trial:03d}.avi"
            timing_path = camera_dir / f"trial_{trial:03d}_timing.csv"
            return (
                replace(
                    state,
                    recording_status=RecordingStatus.STARTING,
                    session_dir=session_dir,
                    trial_number=trial
                ),
                [
                    StartEncoder(video_path, state.settings.record_fps, state.settings.resolution),
                    StartTimingWriter(timing_path)
                ]
            )

        case RecordingStarted():
            return (
                replace(state, recording_status=RecordingStatus.RECORDING),
                [SendStatus("recording_started", {"trial": state.trial_number})]
            )

        case StopRecording():
            if state.recording_status not in (RecordingStatus.RECORDING, RecordingStatus.STARTING):
                return state, []
            return (
                replace(state, recording_status=RecordingStatus.STOPPING),
                [StopEncoder(), StopTimingWriter()]
            )

        case RecordingStopped():
            return (
                replace(
                    state,
                    recording_status=RecordingStatus.STOPPED,
                    session_dir=None,
                    trial_number=0
                ),
                [SendStatus("recording_stopped", {})]
            )

        case ApplySettings(settings):
            effects_list: list[Effect] = []
            if state.camera_status == CameraStatus.STREAMING:
                effects_list.append(ApplyCameraSettings(settings))
            return replace(state, settings=settings), effects_list

        case SettingsApplied(settings):
            return (
                replace(state, settings=settings),
                [SendStatus("settings_applied", {"resolution": settings.resolution})]
            )

        case UpdateMetrics(metrics):
            return replace(state, metrics=metrics), []

        case PreviewFrameReady(frame_data):
            return replace(state, preview_frame=frame_data), []

        case Shutdown():
            effects_list = [CleanupResources()]
            if state.recording_status == RecordingStatus.RECORDING:
                effects_list = [StopEncoder(), StopTimingWriter()] + effects_list
            if state.camera_status == CameraStatus.STREAMING:
                effects_list = [StopCapture(), CloseCamera()] + effects_list
            return (
                replace(
                    state,
                    camera_status=CameraStatus.IDLE,
                    recording_status=RecordingStatus.STOPPED
                ),
                effects_list
            )

        case _:
            return state, []
