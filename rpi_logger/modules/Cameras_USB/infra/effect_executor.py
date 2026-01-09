import asyncio
from pathlib import Path
from typing import Callable, Awaitable, Optional, Any
import logging

from ..core.state import (
    CameraCapabilities, CameraFingerprint, CameraSettings,
    FrameMetrics, USBDeviceInfo, USBAudioDevice,
)
from ..core.actions import (
    Action,
    DeviceDiscovered, ProbingProgress, VideoProbingComplete, AudioProbingComplete,
    ProbingFailed, FingerprintComputed, FingerprintVerified, FingerprintMismatch,
    StreamingStarted, CameraError, AudioCaptureStarted, AudioError,
    RecordingStarted, RecordingStopped, SettingsApplied,
    UpdateMetrics, PreviewFrameReady,
)
from ..core.effects import (
    Effect,
    LookupKnownCamera, ProbeVideoCapabilities, ProbeAudioCapabilities,
    ComputeFingerprint, VerifyFingerprint,
    PersistKnownCamera, LoadCachedSettings, PersistSettings,
    OpenCamera, CloseCamera, StartCapture, StopCapture, ApplyCameraSettings,
    OpenAudioDevice, CloseAudioDevice, StartAudioStream, StopAudioStream,
    StartEncoder, StopEncoder, StartMuxer, StopMuxer, StartTimingWriter, StopTimingWriter,
    SendStatus, NotifyUI, CleanupResources,
)
from ..capture import USBSource, AudioSource, CapturedFrame, AudioChunk
from ..recording import RecordingSession
from ..discovery import (
    probe_video_capabilities, probe_video_quick,
    match_audio_to_camera,
    compute_fingerprint as compute_fp, fingerprint_to_string, fingerprints_match,
)


logger = logging.getLogger(__name__)


class EffectExecutor:
    def __init__(
        self,
        status_callback: Optional[Callable[[str, dict], None]] = None,
        settings_save_callback: Optional[Callable[..., None]] = None,
        known_camera_lookup: Optional[Callable[[str, str], Awaitable[tuple[str, str] | None]]] = None,
        known_camera_save: Optional[Callable[[str, str, str, CameraCapabilities], Awaitable[None]]] = None,
    ):
        self._status_callback = status_callback
        self._settings_save_callback = settings_save_callback
        self._known_camera_lookup = known_camera_lookup
        self._known_camera_save = known_camera_save

        self._camera: Optional[USBSource] = None
        self._audio: Optional[AudioSource] = None
        self._recording: Optional[RecordingSession] = None

        self._capture_task: Optional[asyncio.Task] = None
        self._audio_task: Optional[asyncio.Task] = None

        self._preview_callback: Optional[Callable[[bytes], None]] = None

        self._device_info: Optional[USBDeviceInfo] = None
        self._capabilities: Optional[CameraCapabilities] = None
        self._audio_device: Optional[USBAudioDevice] = None

        self._settings = CameraSettings()
        self._cached_fingerprint: Optional[str] = None
        self._cached_model_key: Optional[str] = None

    def set_preview_callback(self, callback: Optional[Callable[[bytes], None]]) -> None:
        self._preview_callback = callback

    async def __call__(
        self,
        effect: Effect,
        dispatch: Callable[[Action], Awaitable[None]]
    ) -> None:
        match effect:
            case LookupKnownCamera(stable_id, vid_pid):
                await self._lookup_known_camera(stable_id, vid_pid, dispatch)

            case ProbeVideoCapabilities(device):
                await self._probe_video(device, dispatch)

            case ProbeAudioCapabilities(bus_path):
                await self._probe_audio(bus_path, dispatch)

            case ComputeFingerprint(vid_pid, capabilities):
                fp = compute_fp(vid_pid, capabilities)
                await dispatch(FingerprintComputed(fp))

            case VerifyFingerprint(cached_fingerprint, vid_pid, capabilities):
                await self._verify_fingerprint(cached_fingerprint, vid_pid, capabilities, dispatch)

            case PersistKnownCamera(stable_id, model_key, fingerprint, capabilities):
                await self._persist_known_camera(stable_id, model_key, fingerprint, capabilities)

            case LoadCachedSettings(stable_id):
                pass

            case PersistSettings(stable_id, settings):
                if self._settings_save_callback:
                    self._settings_save_callback(settings)

            case OpenCamera(device, resolution, fps):
                await self._open_camera(device, resolution, fps)

            case CloseCamera():
                await self._close_camera()

            case StartCapture():
                self._start_capture_loop(dispatch)

            case StopCapture():
                await self._stop_capture_loop()

            case ApplyCameraSettings(settings):
                await self._apply_settings(settings, dispatch)

            case OpenAudioDevice(sounddevice_index, sample_rate, channels):
                await self._open_audio(sounddevice_index, sample_rate, channels)

            case CloseAudioDevice():
                await self._close_audio()

            case StartAudioStream():
                self._start_audio_loop(dispatch)

            case StopAudioStream():
                await self._stop_audio_loop()

            case StartEncoder(video_path, fps, resolution, with_audio):
                await self._start_recording(video_path, fps, resolution, with_audio, dispatch)

            case StopEncoder():
                await self._stop_recording(dispatch)

            case StartMuxer(output_path, video_fps, resolution, audio_sample_rate, audio_channels):
                pass

            case StopMuxer():
                pass

            case StartTimingWriter(output_path):
                pass

            case StopTimingWriter():
                pass

            case SendStatus(status_type, payload):
                if self._status_callback:
                    self._status_callback(status_type, payload)

            case NotifyUI(event, payload):
                if self._status_callback:
                    self._status_callback(f"ui:{event}", payload)

            case CleanupResources():
                await self._cleanup()

    async def _lookup_known_camera(
        self,
        stable_id: str,
        vid_pid: str,
        dispatch: Callable[[Action], Awaitable[None]]
    ) -> None:
        await dispatch(ProbingProgress("Checking known cameras..."))

        if self._known_camera_lookup:
            result = await self._known_camera_lookup(stable_id, vid_pid)
            if result:
                model_key, fingerprint = result
                self._cached_model_key = model_key
                self._cached_fingerprint = fingerprint
                await dispatch(DeviceDiscovered(
                    device_info=self._device_info,
                    cached_model_key=model_key,
                    cached_fingerprint=fingerprint,
                ))
                return

        await dispatch(DeviceDiscovered(
            device_info=self._device_info,
            cached_model_key=None,
            cached_fingerprint=None,
        ))

    async def _probe_video(
        self,
        device: int | str,
        dispatch: Callable[[Action], Awaitable[None]]
    ) -> None:
        try:
            await dispatch(ProbingProgress("Probing video capabilities..."))

            loop = asyncio.get_running_loop()

            def on_progress(msg: str):
                loop.call_soon_threadsafe(
                    lambda: loop.create_task(dispatch(ProbingProgress(msg)))
                )

            capabilities = await probe_video_capabilities(device, on_progress=on_progress)
            self._capabilities = capabilities

            await dispatch(VideoProbingComplete(capabilities))

        except Exception as e:
            logger.error("Video probing failed: %s", e)
            await dispatch(ProbingFailed(str(e)))

    async def _probe_audio(
        self,
        bus_path: str,
        dispatch: Callable[[Action], Awaitable[None]]
    ) -> None:
        await dispatch(ProbingProgress("Detecting audio devices..."))

        try:
            audio_device = await match_audio_to_camera(bus_path)
            self._audio_device = audio_device
            await dispatch(AudioProbingComplete(audio_device))
        except Exception as e:
            logger.warning("Audio probing failed: %s", e)
            await dispatch(AudioProbingComplete(None))

    async def _verify_fingerprint(
        self,
        cached_fingerprint: str,
        vid_pid: str,
        capabilities: CameraCapabilities,
        dispatch: Callable[[Action], Awaitable[None]]
    ) -> None:
        current = compute_fp(vid_pid, capabilities)
        current_fp_str = fingerprint_to_string(current)

        if fingerprints_match(cached_fingerprint, current):
            await dispatch(FingerprintVerified(
                self._cached_model_key or "",
                capabilities,
            ))
        else:
            await dispatch(FingerprintMismatch(
                cached_fingerprint,
                current_fp_str,
            ))

    async def _persist_known_camera(
        self,
        stable_id: str,
        model_key: str,
        fingerprint: str,
        capabilities: CameraCapabilities,
    ) -> None:
        if self._known_camera_save:
            await self._known_camera_save(stable_id, model_key, fingerprint, capabilities)

    async def _open_camera(
        self,
        device: int | str,
        resolution: tuple[int, int],
        fps: float,
    ) -> None:
        if self._camera:
            self._camera.close()

        self._camera = USBSource(
            device=device,
            resolution=resolution,
            fps=fps,
        )

        def on_error(msg: str):
            logger.error("Camera error: %s", msg)

        self._camera.set_error_callback(on_error)

        if not self._camera.open():
            raise RuntimeError(f"Failed to open camera {device}")

        self._settings = CameraSettings(
            resolution=self._camera.resolution,
            frame_rate=int(fps),
        )

    async def _close_camera(self) -> None:
        if self._camera:
            self._camera.close()
            self._camera = None

    def _start_capture_loop(self, dispatch: Callable[[Action], Awaitable[None]]) -> None:
        if self._capture_task and not self._capture_task.done():
            return

        if self._camera:
            self._camera.start_capture()
            self._capture_task = asyncio.create_task(self._capture_loop(dispatch))

    async def _stop_capture_loop(self) -> None:
        if self._camera:
            self._camera.stop_capture()

        if self._capture_task:
            self._capture_task.cancel()
            try:
                await self._capture_task
            except asyncio.CancelledError:
                pass
            self._capture_task = None

    async def _capture_loop(self, dispatch: Callable[[Action], Awaitable[None]]) -> None:
        if not self._camera:
            return

        frame_count = 0
        record_count = 0
        preview_count = 0
        preview_divisor = self._settings.preview_divisor

        async for frame in self._camera.frames():
            frame_count += 1

            if self._recording:
                await self._recording.write_frame(frame)
                record_count += 1

            if self._preview_callback and frame_count % preview_divisor == 0:
                preview_data = self._frame_to_ppm(frame)
                if preview_data:
                    self._preview_callback(preview_data)
                preview_count += 1

            if frame_count % 30 == 0:
                metrics = FrameMetrics(
                    frames_captured=frame_count,
                    frames_recorded=record_count,
                    frames_previewed=preview_count,
                    frames_dropped=self._camera.drops,
                    audio_chunks_captured=self._audio.chunk_count if self._audio else 0,
                    last_frame_time=frame.wall_time,
                    capture_fps_actual=frame_count / max(1, frame.wall_time - self._camera.frame_count + frame_count),
                    record_fps_actual=0.0,
                    preview_fps_actual=0.0,
                )
                await dispatch(UpdateMetrics(metrics))

    def _frame_to_ppm(self, frame: CapturedFrame) -> Optional[bytes]:
        try:
            import cv2

            rgb = frame.data
            if frame.color_format == "BGR":
                rgb = cv2.cvtColor(frame.data, cv2.COLOR_BGR2RGB)

            scale = self._settings.preview_scale
            if scale < 1.0:
                h, w = rgb.shape[:2]
                new_w = int(w * scale)
                new_h = int(h * scale)
                if new_w > 0 and new_h > 0:
                    rgb = cv2.resize(rgb, (new_w, new_h), interpolation=cv2.INTER_NEAREST)

            h, w = rgb.shape[:2]
            header = f"P6\n{w} {h}\n255\n".encode('ascii')
            return header + rgb.tobytes()
        except Exception as e:
            logger.warning("Preview frame error: %s", e)
            return None

    async def _apply_settings(
        self,
        settings: CameraSettings,
        dispatch: Callable[[Action], Awaitable[None]]
    ) -> None:
        old_settings = self._settings
        self._settings = settings

        if self._camera and (
            old_settings.resolution != settings.resolution or
            old_settings.frame_rate != settings.frame_rate
        ):
            self._camera.configure(
                resolution=settings.resolution,
                fps=float(settings.frame_rate),
            )

        if self._settings_save_callback:
            self._settings_save_callback(settings)

        await dispatch(SettingsApplied(settings))

    async def _open_audio(
        self,
        sounddevice_index: int,
        sample_rate: int,
        channels: int,
    ) -> None:
        if self._audio:
            self._audio.close()

        self._audio = AudioSource(
            device_index=sounddevice_index,
            sample_rate=sample_rate,
            channels=channels,
        )

        def on_error(msg: str):
            logger.error("Audio error: %s", msg)

        self._audio.set_error_callback(on_error)
        self._audio.open()

    async def _close_audio(self) -> None:
        if self._audio:
            self._audio.close()
            self._audio = None

    def _start_audio_loop(self, dispatch: Callable[[Action], Awaitable[None]]) -> None:
        if self._audio_task and not self._audio_task.done():
            return

        if self._audio:
            self._audio.start_capture()
            self._audio_task = asyncio.create_task(self._audio_loop(dispatch))

    async def _stop_audio_loop(self) -> None:
        if self._audio:
            self._audio.stop_capture()

        if self._audio_task:
            self._audio_task.cancel()
            try:
                await self._audio_task
            except asyncio.CancelledError:
                pass
            self._audio_task = None

    async def _audio_loop(self, dispatch: Callable[[Action], Awaitable[None]]) -> None:
        if not self._audio:
            return

        async for chunk in self._audio.chunks():
            if self._recording:
                await self._recording.write_audio(chunk)

    async def _start_recording(
        self,
        video_path: Path,
        fps: int,
        resolution: tuple[int, int],
        with_audio: bool,
        dispatch: Callable[[Action], Awaitable[None]]
    ) -> None:
        session_dir = video_path.parent.parent
        trial = int(video_path.stem.split('_')[1]) if '_' in video_path.stem else 1
        device_id = self._device_info.stable_id if self._device_info else "usbcam0"

        self._recording = RecordingSession(
            session_dir=session_dir,
            device_id=device_id,
            trial_number=trial,
            resolution=resolution,
            fps=fps,
            with_audio=with_audio,
            audio_sample_rate=self._settings.sample_rate,
            audio_channels=self._audio_device.channels if self._audio_device else 2,
        )
        await self._recording.start()
        await dispatch(RecordingStarted())

        if self._status_callback:
            self._status_callback("recording_started", {
                "video_path": str(video_path),
                "device_id": device_id,
                "with_audio": with_audio,
            })

    async def _stop_recording(self, dispatch: Callable[[Action], Awaitable[None]]) -> None:
        if self._recording:
            await self._recording.stop()
            self._recording = None

        await dispatch(RecordingStopped())

        if self._status_callback:
            self._status_callback("recording_stopped", {})

    async def _cleanup(self) -> None:
        await self._stop_capture_loop()
        await self._stop_audio_loop()

        if self._recording:
            await self._recording.stop()
            self._recording = None

        await self._close_camera()
        await self._close_audio()

    def set_device_info(self, device_info: USBDeviceInfo) -> None:
        self._device_info = device_info
