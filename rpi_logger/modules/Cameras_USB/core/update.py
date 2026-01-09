from dataclasses import replace

from .state import (
    AppState, CameraPhase, AudioPhase, RecordingPhase,
    CameraSlot, AudioSlot, FrameMetrics,
    USBDeviceInfo, CameraFingerprint
)
from .actions import (
    Action,
    AssignDevice, DeviceDiscovered,
    StartProbing, ProbingProgress, VideoProbingComplete, AudioProbingComplete, ProbingFailed,
    FingerprintComputed, FingerprintVerified, FingerprintMismatch,
    CameraReady, StartStreaming, StreamingStarted, StopStreaming, CameraError, UnassignCamera,
    SetAudioMode, AudioDeviceMatched, StartAudioCapture, AudioCaptureStarted, StopAudioCapture, AudioError,
    StartRecording, RecordingStarted, StopRecording, RecordingStopped,
    ApplySettings, SettingsApplied,
    UpdateMetrics, PreviewFrameReady,
    Shutdown
)
from .effects import (
    Effect,
    LookupKnownCamera, ProbeVideoCapabilities, ProbeAudioCapabilities,
    ComputeFingerprint, VerifyFingerprint,
    PersistKnownCamera, LoadCachedSettings,
    OpenCamera, CloseCamera, StartCapture, StopCapture, ApplyCameraSettings,
    OpenAudioDevice, CloseAudioDevice, StartAudioStream, StopAudioStream,
    StartEncoder, StopEncoder, StartMuxer, StopMuxer, StartTimingWriter, StopTimingWriter,
    SendStatus, NotifyUI, CleanupResources
)


def _generate_model_key(display_name: str) -> str:
    return display_name.lower().replace(" ", "_").replace(":", "_")[:32]


def update(state: AppState, action: Action) -> tuple[AppState, list[Effect]]:
    match action:
        # IDLE -> DISCOVERING
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
                phase=CameraPhase.DISCOVERING,
                device_info=device_info,
                probing_progress="Checking known cameras...",
            )
            return (
                replace(state, camera=new_camera),
                [LookupKnownCamera(stable_id, vid_pid)]
            )

        # DISCOVERING -> VERIFYING (known) or PROBING (unknown)
        case DeviceDiscovered(device_info, cached_model_key, cached_fingerprint):
            if cached_model_key and cached_fingerprint:
                new_camera = replace(
                    state.camera,
                    phase=CameraPhase.VERIFYING,
                    device_info=device_info,
                    model_key=cached_model_key,
                    probing_progress="Verifying camera...",
                )
                return (
                    replace(state, camera=new_camera),
                    [
                        ProbeVideoCapabilities(device_info.dev_path),
                        LoadCachedSettings(device_info.stable_id),
                    ]
                )
            else:
                new_camera = replace(
                    state.camera,
                    phase=CameraPhase.PROBING,
                    device_info=device_info,
                    probing_progress="Probing video capabilities...",
                )
                return (
                    replace(state, camera=new_camera),
                    [ProbeVideoCapabilities(device_info.dev_path)]
                )

        case ProbingProgress(message):
            new_camera = replace(state.camera, probing_progress=message)
            return replace(state, camera=new_camera), []

        # PROBING/VERIFYING -> handle video capabilities
        case VideoProbingComplete(capabilities):
            device_info = state.camera.device_info
            if not device_info:
                return state, []

            effects: list[Effect] = []

            if state.camera.phase == CameraPhase.VERIFYING:
                cached_fp = state.camera.fingerprint.capability_hash if state.camera.fingerprint else ""
                effects.append(VerifyFingerprint(cached_fp, device_info.vid_pid, capabilities))
            else:
                effects.append(ComputeFingerprint(device_info.vid_pid, capabilities))
                effects.append(ProbeAudioCapabilities(device_info.bus_path))

            new_camera = replace(
                state.camera,
                capabilities=capabilities,
                probing_progress="Checking audio devices..." if state.camera.phase == CameraPhase.PROBING else "Verifying...",
            )
            return replace(state, camera=new_camera), effects

        case FingerprintComputed(fingerprint):
            new_camera = replace(state.camera, fingerprint=fingerprint)
            return replace(state, camera=new_camera), []

        # VERIFYING -> READY (match) or PROBING (mismatch)
        case FingerprintVerified(model_key, capabilities):
            device_info = state.camera.device_info
            if not device_info:
                return state, []
            new_camera = replace(
                state.camera,
                phase=CameraPhase.READY,
                capabilities=capabilities,
                model_key=model_key,
                is_known=True,
                probing_progress="",
            )
            return (
                replace(state, camera=new_camera),
                [
                    ProbeAudioCapabilities(device_info.bus_path),
                    NotifyUI("camera_ready", {"is_known": True, "model_key": model_key}),
                ]
            )

        case FingerprintMismatch(expected_hash, actual_hash):
            device_info = state.camera.device_info
            if not device_info:
                return state, []
            new_camera = replace(
                state.camera,
                phase=CameraPhase.PROBING,
                probing_progress="Camera changed, reprobing...",
                is_known=False,
                model_key=None,
                fingerprint=None,
            )
            return (
                replace(state, camera=new_camera),
                [
                    ProbeVideoCapabilities(device_info.dev_path),
                    NotifyUI("fingerprint_mismatch", {"expected": expected_hash, "actual": actual_hash}),
                ]
            )

        case AudioProbingComplete(audio_device):
            audio_phase = AudioPhase.AVAILABLE if audio_device else AudioPhase.UNAVAILABLE
            if state.settings.audio_mode == "off":
                audio_phase = AudioPhase.DISABLED
            new_audio = AudioSlot(phase=audio_phase, device=audio_device)

            # If we were probing (unknown camera), now move to READY and persist
            effects: list[Effect] = []
            if state.camera.phase == CameraPhase.PROBING:
                device_info = state.camera.device_info
                capabilities = state.camera.capabilities
                fingerprint = state.camera.fingerprint
                if device_info and capabilities and fingerprint:
                    model_key = _generate_model_key(device_info.display_name)
                    effects.append(
                        PersistKnownCamera(
                            device_info.stable_id,
                            model_key,
                            f"{fingerprint.vid_pid}:{fingerprint.capability_hash}",
                            capabilities,
                        )
                    )
                    new_camera = replace(
                        state.camera,
                        phase=CameraPhase.READY,
                        model_key=model_key,
                        is_known=False,
                        probing_progress="",
                    )
                else:
                    new_camera = replace(
                        state.camera,
                        phase=CameraPhase.READY,
                        probing_progress="",
                    )
                effects.append(NotifyUI("camera_ready", {"is_known": False}))
                return replace(state, camera=new_camera, audio=new_audio), effects

            return replace(state, audio=new_audio), effects

        case ProbingFailed(error):
            new_camera = replace(
                state.camera,
                phase=CameraPhase.ERROR,
                error_message=error,
                probing_progress="",
            )
            return (
                replace(state, camera=new_camera),
                [SendStatus("error", {"message": error})]
            )

        case CameraReady(is_known):
            return state, []

        # READY -> STREAMING
        case StartStreaming():
            if state.camera.phase != CameraPhase.READY:
                return state, []
            device_info = state.camera.device_info
            if not device_info:
                return state, []
            effects = [
                OpenCamera(device_info.dev_path, state.settings.resolution, state.settings.frame_rate),
                StartCapture(),
            ]
            if state.audio.phase == AudioPhase.AVAILABLE and state.audio.device:
                effects.append(
                    OpenAudioDevice(
                        state.audio.device.sounddevice_index,
                        state.settings.sample_rate,
                        state.audio.device.channels,
                    )
                )
            new_camera = replace(state.camera, phase=CameraPhase.STREAMING)
            return replace(state, camera=new_camera), effects

        case StreamingStarted():
            return (
                state,
                [SendStatus("streaming_started", {"camera_id": state.camera.device_info.stable_id if state.camera.device_info else ""})]
            )

        case StopStreaming():
            if state.camera.phase != CameraPhase.STREAMING:
                return state, []
            effects: list[Effect] = [StopCapture(), CloseCamera()]
            if state.audio.phase == AudioPhase.CAPTURING:
                effects.extend([StopAudioStream(), CloseAudioDevice()])
            new_camera = replace(state.camera, phase=CameraPhase.READY)
            new_audio = replace(state.audio, phase=AudioPhase.AVAILABLE if state.audio.device else AudioPhase.UNAVAILABLE)
            return replace(state, camera=new_camera, audio=new_audio), effects

        case CameraError(message):
            new_camera = replace(
                state.camera,
                phase=CameraPhase.ERROR,
                error_message=message,
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

        # Audio actions
        case SetAudioMode(mode):
            new_settings = replace(state.settings, audio_mode=mode)
            if mode == "off":
                new_audio = replace(state.audio, phase=AudioPhase.DISABLED)
            elif state.audio.device:
                new_audio = replace(state.audio, phase=AudioPhase.AVAILABLE)
            else:
                new_audio = replace(state.audio, phase=AudioPhase.UNAVAILABLE)
            return replace(state, settings=new_settings, audio=new_audio), []

        case StartAudioCapture():
            if state.audio.phase != AudioPhase.AVAILABLE or not state.audio.device:
                return state, []
            new_audio = replace(state.audio, phase=AudioPhase.CAPTURING)
            return (
                replace(state, audio=new_audio),
                [StartAudioStream()]
            )

        case AudioCaptureStarted():
            return state, [SendStatus("audio_started", {})]

        case StopAudioCapture():
            if state.audio.phase != AudioPhase.CAPTURING:
                return state, []
            new_audio = replace(state.audio, phase=AudioPhase.AVAILABLE)
            return (
                replace(state, audio=new_audio),
                [StopAudioStream()]
            )

        case AudioError(message):
            new_audio = replace(state.audio, phase=AudioPhase.ERROR, error_message=message)
            return (
                replace(state, audio=new_audio),
                [SendStatus("audio_error", {"message": message})]
            )

        # Recording actions
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
            return (
                replace(state, recording_phase=RecordingPhase.STOPPING),
                effects
            )

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

        # Settings
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

        # Metrics and preview
        case UpdateMetrics(metrics):
            return replace(state, metrics=metrics), []

        case PreviewFrameReady(frame_data):
            return replace(state, preview_frame=frame_data), []

        # Shutdown
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
