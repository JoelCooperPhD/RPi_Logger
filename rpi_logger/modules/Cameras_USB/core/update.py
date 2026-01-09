"""State reducer for USB camera module.

Simplified flow:
  IDLE → (AssignDevice) → PROBING → (CameraReady) → READY → (StartStreaming) → STREAMING
"""

from dataclasses import replace

from .state import (
    AppState, CameraPhase, AudioPhase, RecordingPhase,
    CameraSlot, AudioSlot, FrameMetrics,
    USBDeviceInfo,
)
from .actions import (
    Action,
    AssignDevice, ProbingProgress, CameraReady, CameraError, UnassignCamera,
    StartStreaming, StreamingStarted, StopStreaming,
    SetAudioMode, AudioReady, AudioCaptureStarted, AudioError,
    StartRecording, RecordingStarted, StopRecording, RecordingStopped,
    ApplySettings, SettingsApplied,
    UpdateMetrics, PreviewFrameReady,
    Shutdown,
)
from .effects import (
    Effect,
    EnsureCameraProbed, ProbeAudio,
    OpenCamera, CloseCamera, StartCapture, StopCapture, ApplyCameraSettings,
    OpenAudioDevice, CloseAudioDevice, StartAudioStream, StopAudioStream,
    StartEncoder, StopEncoder, StartMuxer, StopMuxer, StartTimingWriter, StopTimingWriter,
    SendStatus, CleanupResources,
)


def update(state: AppState, action: Action) -> tuple[AppState, list[Effect]]:
    """Pure reducer function: (state, action) -> (new_state, effects)"""

    match action:
        # ================================================================
        # Camera Lifecycle
        # ================================================================

        case AssignDevice(dev_path, stable_id, vid_pid, display_name, sysfs_path, bus_path):
            if state.camera.phase != CameraPhase.IDLE:
                return state, []

            device_info = USBDeviceInfo(
                device=dev_path,
                stable_id=stable_id,
                display_name=display_name,
                vid_pid=vid_pid,
                sysfs_path=sysfs_path,
                bus_path=bus_path,
            )
            new_camera = replace(
                state.camera,
                phase=CameraPhase.PROBING,
                device_info=device_info,
                probing_progress="Checking camera...",
            )
            return (
                replace(state, camera=new_camera),
                [EnsureCameraProbed(dev_path, vid_pid, display_name)]
            )

        case ProbingProgress(message):
            new_camera = replace(state.camera, probing_progress=message)
            return replace(state, camera=new_camera), []

        case CameraReady(capabilities):
            device_info = state.camera.device_info
            if not device_info:
                return state, []

            new_camera = replace(
                state.camera,
                phase=CameraPhase.READY,
                capabilities=capabilities,
                probing_progress="",
            )
            effects: list[Effect] = [
                ProbeAudio(device_info.bus_path),
                SendStatus("camera_ready", {"camera_id": device_info.stable_id}),
            ]
            return replace(state, camera=new_camera), effects

        case CameraError(message):
            new_camera = replace(
                state.camera,
                phase=CameraPhase.ERROR,
                error_message=message,
                probing_progress="",
            )
            return (
                replace(state, camera=new_camera),
                [SendStatus("error", {"message": message})]
            )

        case UnassignCamera():
            if state.camera.phase == CameraPhase.IDLE:
                return state, []

            effects: list[Effect] = []
            if state.camera.phase == CameraPhase.STREAMING:
                effects.extend([StopCapture(), CloseCamera()])
            if state.audio.phase == AudioPhase.CAPTURING:
                effects.extend([StopAudioStream(), CloseAudioDevice()])
            if state.recording_phase == RecordingPhase.RECORDING:
                effects.extend([StopEncoder(), StopTimingWriter()])
            effects.append(SendStatus("camera_unassigned", {}))

            return (
                replace(
                    state,
                    camera=CameraSlot(),
                    audio=AudioSlot(),
                    recording_phase=RecordingPhase.STOPPED,
                    metrics=FrameMetrics(),
                ),
                effects
            )

        # ================================================================
        # Streaming
        # ================================================================

        case StartStreaming():
            if state.camera.phase != CameraPhase.READY:
                return state, []

            device_info = state.camera.device_info
            if not device_info:
                return state, []

            effects: list[Effect] = [
                OpenCamera(device_info.dev_path, state.settings.resolution, state.settings.frame_rate),
                StartCapture(),
            ]
            if state.audio.phase == AudioPhase.AVAILABLE and state.audio.device:
                effects.append(
                    OpenAudioDevice(
                        state.audio.device.sounddevice_index,
                        state.settings.sample_rate,
                        state.audio.device.channels,
                        state.audio.device.sample_rates,
                    )
                )

            new_camera = replace(state.camera, phase=CameraPhase.STREAMING)
            return replace(state, camera=new_camera), effects

        case StreamingStarted():
            device_id = state.camera.device_info.stable_id if state.camera.device_info else ""
            return state, [SendStatus("streaming_started", {"camera_id": device_id})]

        case StopStreaming():
            if state.camera.phase != CameraPhase.STREAMING:
                return state, []

            effects: list[Effect] = [StopCapture(), CloseCamera()]
            if state.audio.phase == AudioPhase.CAPTURING:
                effects.extend([StopAudioStream(), CloseAudioDevice()])

            new_camera = replace(state.camera, phase=CameraPhase.READY)
            new_audio = replace(
                state.audio,
                phase=AudioPhase.AVAILABLE if state.audio.device else AudioPhase.UNAVAILABLE
            )
            return replace(state, camera=new_camera, audio=new_audio), effects

        # ================================================================
        # Audio
        # ================================================================

        case SetAudioMode(mode):
            new_settings = replace(state.settings, audio_mode=mode)
            if mode == "off":
                new_audio = replace(state.audio, phase=AudioPhase.DISABLED)
            elif state.audio.device:
                new_audio = replace(state.audio, phase=AudioPhase.AVAILABLE)
            else:
                new_audio = replace(state.audio, phase=AudioPhase.UNAVAILABLE)
            return replace(state, settings=new_settings, audio=new_audio), []

        case AudioReady(device):
            if state.settings.audio_mode == "off":
                phase = AudioPhase.DISABLED
            elif device:
                phase = AudioPhase.AVAILABLE
            else:
                phase = AudioPhase.UNAVAILABLE

            new_audio = AudioSlot(phase=phase, device=device)
            return replace(state, audio=new_audio), []

        case AudioCaptureStarted():
            return state, [SendStatus("audio_started", {})]

        case AudioError(message):
            new_audio = replace(state.audio, phase=AudioPhase.ERROR, error_message=message)
            return (
                replace(state, audio=new_audio),
                [SendStatus("audio_error", {"message": message})]
            )

        # ================================================================
        # Recording
        # ================================================================

        case StartRecording(session_dir, trial):
            if state.camera.phase != CameraPhase.STREAMING:
                return state, []
            if state.recording_phase != RecordingPhase.STOPPED:
                return state, []

            device_info = state.camera.device_info
            stable_id = device_info.stable_id if device_info else "usbcam0"
            safe_id = stable_id.replace(":", "_").replace("-", "_")
            camera_dir = session_dir / safe_id

            with_audio = state.audio.phase == AudioPhase.CAPTURING
            ext = "mp4" if with_audio else "avi"
            video_path = camera_dir / f"trial_{trial:03d}.{ext}"
            timing_path = camera_dir / f"trial_{trial:03d}_timing.csv"

            effects: list[Effect] = [
                StartEncoder(video_path, state.settings.frame_rate, state.settings.resolution, with_audio),
                StartTimingWriter(timing_path),
            ]
            if with_audio and state.audio.device:
                effects.append(
                    StartMuxer(
                        video_path,
                        state.settings.frame_rate,
                        state.settings.resolution,
                        state.settings.sample_rate,
                        state.audio.device.channels,
                    )
                )

            return (
                replace(
                    state,
                    recording_phase=RecordingPhase.STARTING,
                    session_dir=session_dir,
                    trial_number=trial,
                ),
                effects
            )

        case RecordingStarted():
            return (
                replace(state, recording_phase=RecordingPhase.RECORDING),
                [SendStatus("recording_started", {"trial": state.trial_number})]
            )

        case StopRecording():
            if state.recording_phase not in (RecordingPhase.RECORDING, RecordingPhase.STARTING):
                return state, []

            effects: list[Effect] = [StopEncoder(), StopTimingWriter()]
            if state.audio.phase == AudioPhase.CAPTURING:
                effects.append(StopMuxer())

            return replace(state, recording_phase=RecordingPhase.STOPPING), effects

        case RecordingStopped():
            return (
                replace(
                    state,
                    recording_phase=RecordingPhase.STOPPED,
                    session_dir=None,
                    trial_number=0,
                ),
                [SendStatus("recording_stopped", {})]
            )

        # ================================================================
        # Settings
        # ================================================================

        case ApplySettings(settings):
            effects: list[Effect] = []
            if state.camera.phase == CameraPhase.STREAMING:
                effects.append(ApplyCameraSettings(settings))
            return replace(state, settings=settings), effects

        case SettingsApplied(settings):
            return (
                replace(state, settings=settings),
                [SendStatus("settings_applied", {"resolution": settings.resolution})]
            )

        # ================================================================
        # Metrics
        # ================================================================

        case UpdateMetrics(metrics):
            return replace(state, metrics=metrics), []

        case PreviewFrameReady(frame_data):
            return replace(state, preview_frame=frame_data), []

        # ================================================================
        # Shutdown
        # ================================================================

        case Shutdown():
            effects: list[Effect] = [CleanupResources()]
            if state.recording_phase == RecordingPhase.RECORDING:
                effects = [StopEncoder(), StopTimingWriter()] + effects
            if state.camera.phase == CameraPhase.STREAMING:
                effects = [StopCapture(), CloseCamera()] + effects
            if state.audio.phase == AudioPhase.CAPTURING:
                effects = [StopAudioStream(), CloseAudioDevice()] + effects

            return (
                replace(
                    state,
                    camera=CameraSlot(),
                    audio=AudioSlot(),
                    recording_phase=RecordingPhase.STOPPED,
                ),
                effects
            )

        case _:
            return state, []
