import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Callable, Optional, Any
import logging

from .state import (
    CameraState, CameraSettings, CameraCapabilities, FrameMetrics,
    USBDeviceInfo, USBAudioDevice,
    CameraPhase, RecordingPhase, AudioPhase,
)
from ..capture import USBSource, AudioSource, CapturedFrame
from ..recording import RecordingSession
from ..discovery import (
    probe_camera_modes,
    verify_camera_accessible,
    match_audio_to_camera,
    CameraKnowledge,
)

logger = logging.getLogger(__name__)


class CameraController:
    def __init__(
        self,
        knowledge: CameraKnowledge,
        status_callback: Optional[Callable[[str, dict], None]] = None,
        settings_save_callback: Optional[Callable[[CameraSettings], None]] = None,
    ):
        self._knowledge = knowledge
        self._status_callback = status_callback
        self._settings_save_callback = settings_save_callback

        self._state = CameraState()
        self._subscribers: list[Callable[[CameraState], None]] = []

        self._camera: Optional[USBSource] = None
        self._audio: Optional[AudioSource] = None
        self._recording: Optional[RecordingSession] = None
        self._capture_task: Optional[asyncio.Task] = None
        self._audio_task: Optional[asyncio.Task] = None
        self._preview_callback: Optional[Callable[[bytes], None]] = None
        self._recording_lock = asyncio.Lock()

    @property
    def state(self) -> CameraState:
        return self._state

    def subscribe(self, callback: Callable[[CameraState], None]) -> Callable[[], None]:
        self._subscribers.append(callback)
        callback(self._state)
        return lambda: self._subscribers.remove(callback)

    def set_preview_callback(self, callback: Optional[Callable[[bytes], None]]) -> None:
        self._preview_callback = callback

    def _notify(self) -> None:
        for sub in self._subscribers:
            try:
                sub(self._state)
            except Exception as e:
                logger.warning("Subscriber error: %s", e)

    def _send_status(self, status_type: str, payload: dict) -> None:
        if self._status_callback:
            self._status_callback(status_type, payload)

    # ================================================================
    # ASSIGN / PROBE
    # ================================================================

    async def assign(self, device_info: USBDeviceInfo) -> None:
        if self._state.phase != CameraPhase.IDLE:
            return

        self._state.phase = CameraPhase.PROBING
        self._state.device_info = device_info
        self._state.probing_progress = "Checking camera..."
        self._notify()

        asyncio.create_task(self._probe_camera(device_info))

    async def _probe_camera(self, device_info: USBDeviceInfo) -> None:
        try:
            profile = await self._knowledge.get(device_info.vid_pid)

            if profile:
                self._state.probing_progress = "Verifying camera..."
                self._notify()
                accessible = await verify_camera_accessible(device_info.device)
                if accessible:
                    logger.info("Known camera %s - using cached %d modes (has_audio=%s)",
                               device_info.vid_pid, len(profile.modes), profile.has_audio)
                    await self._camera_ready(profile, device_info)
                    return
                else:
                    logger.warning("Known camera %s not accessible, will re-probe",
                                   device_info.vid_pid)

            self._state.probing_progress = "Probing camera modes..."
            self._notify()

            loop = asyncio.get_running_loop()
            def on_progress(msg: str):
                asyncio.run_coroutine_threadsafe(self._set_progress(msg), loop)

            probed_modes = await probe_camera_modes(device_info.device, on_progress=on_progress)

            self._state.probing_progress = "Probing audio..."
            self._notify()

            audio_device = await match_audio_to_camera(device_info.bus_path)
            has_audio = audio_device is not None
            audio_sample_rates = audio_device.sample_rates if audio_device else ()
            audio_channels = audio_device.channels if audio_device else 2

            profile = CameraKnowledge.create_profile_from_probe(
                vid_pid=device_info.vid_pid,
                display_name=device_info.display_name,
                probed_modes=probed_modes,
                has_audio=has_audio,
                audio_sample_rates=audio_sample_rates,
                audio_channels=audio_channels,
            )
            await self._knowledge.register(profile)

            logger.info("Probed camera %s: %d modes, has_audio=%s",
                       device_info.vid_pid, len(profile.modes), has_audio)
            await self._camera_ready(profile, device_info)

        except Exception as e:
            logger.error("Probe failed: %s", e)
            self._state.phase = CameraPhase.ERROR
            self._state.error_message = str(e)
            self._notify()
            self._send_status("error", {"message": str(e)})

    async def _set_progress(self, msg: str) -> None:
        self._state.probing_progress = msg
        self._notify()

    async def _camera_ready(self, profile, device_info: USBDeviceInfo) -> None:
        capabilities = CameraCapabilities(
            camera_id=f"usb:{device_info.device}",
            modes=tuple(profile.modes),
            default_resolution=profile.default_resolution,
            default_fps=profile.default_fps,
        )

        if capabilities.default_resolution != self._state.settings.resolution:
            self._state.settings = replace(
                self._state.settings,
                resolution=capabilities.default_resolution,
                frame_rate=int(capabilities.default_fps),
            )

        if profile.has_audio:
            audio_device = await match_audio_to_camera(device_info.bus_path)
            if audio_device:
                self._state.audio_device = audio_device
                logger.info("Audio available: %s", audio_device.device_name)
            else:
                logger.warning("Profile says has_audio but no device found at bus_path %s",
                              device_info.bus_path)

        self._state.phase = CameraPhase.READY
        self._state.capabilities = capabilities
        self._state.probing_progress = ""
        self._notify()

        self._send_status("camera_ready", {"camera_id": device_info.stable_id})

    async def unassign(self) -> None:
        if self._state.phase == CameraPhase.STREAMING:
            await self.stop_streaming()
        if self._state.is_recording:
            await self.stop_recording()

        old_settings = self._state.settings
        self._state = CameraState(settings=old_settings)
        self._notify()

        self._send_status("camera_unassigned", {})

    # ================================================================
    # STREAMING
    # ================================================================

    async def start_streaming(self) -> None:
        if not self._state.can_stream:
            return

        device_info = self._state.device_info
        if not device_info:
            return

        self._camera = USBSource(
            device=device_info.dev_path,
            resolution=self._state.settings.resolution,
            fps=float(self._state.settings.frame_rate),
        )
        self._camera.set_error_callback(lambda msg: logger.error("Camera: %s", msg))

        if not self._camera.open():
            self._camera = None
            self._state.phase = CameraPhase.ERROR
            self._state.error_message = "Failed to open camera"
            self._notify()
            return

        self._camera.start_capture()
        self._capture_task = asyncio.create_task(self._capture_loop())

        if self._state.audio_available and self._state.audio_enabled and self._state.audio_device:
            try:
                await self._start_audio()
            except Exception as e:
                logger.warning("Audio start failed, continuing without audio: %s", e)
                self._state.audio_phase = AudioPhase.IDLE

        self._state.phase = CameraPhase.STREAMING
        self._notify()

        self._send_status("streaming_started", {"camera_id": device_info.stable_id})

    async def stop_streaming(self) -> None:
        if self._state.phase != CameraPhase.STREAMING:
            return

        if self._state.is_recording:
            await self.stop_recording()

        if self._capture_task:
            self._capture_task.cancel()
            try:
                await self._capture_task
            except asyncio.CancelledError:
                pass
            self._capture_task = None

        if self._camera:
            self._camera.stop_capture()
            self._camera.close()
            self._camera = None

        try:
            await self._stop_audio()
        except Exception as e:
            logger.warning("Audio stop error: %s", e)
        finally:
            self._state.audio_phase = AudioPhase.IDLE

        self._state.phase = CameraPhase.READY
        self._notify()

    async def _capture_loop(self) -> None:
        if not self._camera:
            return

        frame_count = 0
        record_count = 0
        preview_count = 0

        capture_start_time = 0.0
        record_intervals: list[float] = []
        preview_intervals: list[float] = []
        last_record_time = 0.0
        last_preview_time = 0.0
        record_fps_actual = 0.0
        preview_fps_actual = 0.0

        try:
            async for frame in self._camera.frames():
                frame_count += 1
                now = frame.wall_time

                if capture_start_time == 0.0:
                    capture_start_time = now

                # Only write during RECORDING phase (not STARTING/STOPPING) to avoid partial writes
                if self._state.recording_phase == RecordingPhase.RECORDING and self._recording:
                    await self._recording.write_frame(frame)
                    record_count += 1
                    if last_record_time > 0:
                        record_intervals.append(now - last_record_time)
                        if len(record_intervals) > 30:
                            record_intervals.pop(0)
                        if len(record_intervals) >= 3:
                            avg_interval = sum(record_intervals) / len(record_intervals)
                            record_fps_actual = 1.0 / avg_interval if avg_interval > 0 else 0.0
                    last_record_time = now

                preview_divisor = self._state.settings.preview_divisor
                if self._preview_callback and frame_count % preview_divisor == 0:
                    preview_data = self._frame_to_ppm(frame)
                    if preview_data:
                        self._preview_callback(preview_data)
                    preview_count += 1
                    if last_preview_time > 0:
                        preview_intervals.append(now - last_preview_time)
                        if len(preview_intervals) > 30:
                            preview_intervals.pop(0)
                        if len(preview_intervals) >= 5:
                            avg_interval = sum(preview_intervals) / len(preview_intervals)
                            preview_fps_actual = 1.0 / avg_interval if avg_interval > 0 else 0.0
                    last_preview_time = now

                if frame_count % 30 == 0:
                    elapsed = now - capture_start_time
                    capture_fps_actual = frame_count / elapsed if elapsed > 0 else 0.0
                    self._state.metrics = FrameMetrics(
                        frames_captured=frame_count,
                        frames_recorded=record_count,
                        frames_previewed=preview_count,
                        frames_dropped=self._camera.drops if self._camera else 0,
                        audio_chunks_captured=self._audio.chunk_count if self._audio else 0,
                        last_frame_time=now,
                        capture_fps_actual=capture_fps_actual,
                        record_fps_actual=record_fps_actual,
                        preview_fps_actual=preview_fps_actual,
                    )
                    self._notify()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Capture loop error: %s", e)

    def _frame_to_ppm(self, frame: CapturedFrame) -> Optional[bytes]:
        try:
            import cv2

            rgb = frame.data
            if frame.color_format == "BGR":
                rgb = cv2.cvtColor(frame.data, cv2.COLOR_BGR2RGB)

            scale = self._state.settings.preview_scale
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

    # ================================================================
    # AUDIO
    # ================================================================

    async def set_audio_mode(self, mode: str) -> None:
        self._state.settings = replace(self._state.settings, audio_mode=mode)
        self._notify()

    async def _start_audio(self) -> None:
        if not self._state.audio_device:
            return

        dev = self._state.audio_device
        self._audio = AudioSource(
            device_index=dev.sounddevice_index,
            sample_rate=self._state.settings.sample_rate,
            channels=dev.channels,
            supported_rates=dev.sample_rates,
        )
        self._audio.set_error_callback(lambda msg: logger.error("Audio: %s", msg))
        self._audio.open()
        self._audio.start_capture()
        self._audio_task = asyncio.create_task(self._audio_loop())

        self._state.audio_phase = AudioPhase.CAPTURING
        self._notify()

    async def _stop_audio(self) -> None:
        if self._audio_task:
            self._audio_task.cancel()
            try:
                await self._audio_task
            except asyncio.CancelledError:
                pass
            self._audio_task = None

        if self._audio:
            self._audio.stop_capture()
            self._audio.close()
            self._audio = None

    async def _audio_loop(self) -> None:
        if not self._audio:
            return

        try:
            async for chunk in self._audio.chunks():
                # Only write during RECORDING phase (not STARTING/STOPPING) to avoid partial writes
                if self._state.recording_phase == RecordingPhase.RECORDING and self._recording:
                    await self._recording.write_audio(chunk)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Audio loop error: %s", e)

    # ================================================================
    # RECORDING
    # ================================================================

    def _reset_recording_state(self) -> None:
        self._recording = None
        self._state.recording_phase = RecordingPhase.STOPPED
        self._state.session_dir = None
        self._state.trial_number = None
        self._notify()

    async def start_recording(self, session_dir: Path, trial: int) -> None:
        try:
            async with asyncio.timeout(30):
                async with self._recording_lock:
                    await self._start_recording_locked(session_dir, trial)
        except asyncio.TimeoutError:
            logger.error("Recording start timed out")
            await self._cleanup_recording_on_timeout()
            self._reset_recording_state()
            self._send_status("error", {"message": "Recording start timed out"})

    async def _start_recording_locked(self, session_dir: Path, trial: int) -> None:
        if not self._state.can_record:
            return

        device_info = self._state.device_info
        device_id = device_info.stable_id if device_info else "usbcam0"

        self._state.recording_phase = RecordingPhase.STARTING
        self._state.session_dir = session_dir
        self._state.trial_number = trial
        self._notify()

        try:
            actual_fps = (
                self._camera.fps if self._camera else self._state.settings.frame_rate
            )
            actual_sample_rate = (
                self._audio.sample_rate if self._audio else self._state.settings.sample_rate
            )
            display_name = device_info.display_name if device_info else ""
            self._recording = RecordingSession(
                session_dir=session_dir,
                device_id=device_id,
                trial_number=trial,
                resolution=self._state.settings.resolution,
                fps=int(actual_fps),
                with_audio=self._state.audio_capturing,
                audio_sample_rate=actual_sample_rate,
                audio_channels=self._state.audio_device.channels if self._state.audio_device else 2,
                display_name=display_name,
            )
            await self._recording.start()

            self._state.recording_phase = RecordingPhase.RECORDING
            self._notify()

            self._send_status("recording_started", {
                "trial": trial,
                "device_id": device_id,
                "video_path": str(self._recording.video_path),
                "with_audio": self._recording.with_audio,
            })
        except Exception as e:
            logger.error("Recording failed to start for %s trial %d: %s", device_id, trial, e)
            self._reset_recording_state()
            self._send_status("error", {
                "message": f"Recording failed: {e}",
                "device_id": device_id,
                "trial": trial,
            })

    async def stop_recording(self) -> None:
        try:
            async with asyncio.timeout(30):
                async with self._recording_lock:
                    await self._stop_recording_locked()
        except asyncio.TimeoutError:
            logger.error("Recording stop timed out")
            await self._cleanup_recording_on_timeout()
            self._reset_recording_state()
            self._send_status("error", {"message": "Recording stop timed out"})

    async def _stop_recording_locked(self) -> None:
        if self._state.recording_phase not in (RecordingPhase.RECORDING, RecordingPhase.STARTING):
            return

        self._state.recording_phase = RecordingPhase.STOPPING
        self._notify()

        try:
            if self._recording:
                await self._recording.stop()
        except Exception as e:
            logger.error("Recording stop error: %s", e)
        finally:
            self._reset_recording_state()
            self._send_status("recording_stopped", {})

    async def _cleanup_recording_on_timeout(self) -> None:
        if not self._recording:
            return
        try:
            async with asyncio.timeout(5):
                await self._recording.stop()
        except Exception as e:
            logger.warning("Recording cleanup failed: %s", e)
        finally:
            self._recording = None

    # ================================================================
    # SETTINGS
    # ================================================================

    async def apply_settings(self, settings: CameraSettings) -> None:
        old = self._state.settings
        self._state.settings = settings
        self._notify()

        resolution_changed = old.resolution != settings.resolution
        fps_changed = old.frame_rate != settings.frame_rate
        sample_rate_changed = old.sample_rate != settings.sample_rate

        if self._camera and self._state.phase == CameraPhase.STREAMING and (resolution_changed or fps_changed):
            if self._capture_task:
                self._capture_task.cancel()
                try:
                    await self._capture_task
                except asyncio.CancelledError:
                    pass
                self._capture_task = None

            self._camera.stop_capture()
            self._camera.close()

            device_info = self._state.device_info
            if device_info:
                self._camera = USBSource(
                    device=device_info.dev_path,
                    resolution=settings.resolution,
                    fps=float(settings.frame_rate),
                )
                self._camera.set_error_callback(lambda msg: logger.error("Camera: %s", msg))

                if self._camera.open():
                    self._camera.start_capture()
                    self._capture_task = asyncio.create_task(self._capture_loop())
                else:
                    logger.error("Failed to reopen camera with new settings")

        if self._state.phase == CameraPhase.STREAMING:
            audio_should_run = (
                self._state.audio_available
                and self._state.audio_enabled
                and self._state.audio_device is not None
            )
            audio_is_running = self._state.audio_phase == AudioPhase.CAPTURING

            if audio_is_running and not audio_should_run:
                await self._stop_audio()
                self._state.audio_phase = AudioPhase.IDLE
                self._notify()
            elif not audio_is_running and audio_should_run:
                await self._start_audio()
            elif audio_is_running and sample_rate_changed:
                await self._stop_audio()
                self._state.audio_phase = AudioPhase.IDLE
                await self._start_audio()

        if self._settings_save_callback:
            self._settings_save_callback(settings)

    # ================================================================
    # SHUTDOWN
    # ================================================================

    async def shutdown(self) -> None:
        await self.stop_recording()
        await self.stop_streaming()
        await self.unassign()
