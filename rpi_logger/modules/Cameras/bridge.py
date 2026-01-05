"""Single-camera runtime: one camera per instance, assigned via assign_device command."""

from __future__ import annotations

import asyncio
import contextlib
import fnmatch
from pathlib import Path
from typing import Any, Dict, Optional

from rpi_logger.core.commands import StatusMessage, StatusType
from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.modules.Cameras.camera_core import (
    CameraId,
    CameraDescriptor,
    CameraCapabilities,
    CaptureHandle,
    CaptureFrame,
    USBCapture,
    Encoder,
)
from rpi_logger.modules.Cameras.camera_core.backends import usb_backend
from rpi_logger.modules.base.camera_models import (
    CameraModelDatabase,
    extract_model_name,
    copy_capabilities,
)
from rpi_logger.modules.Cameras.config import CamerasConfig
from rpi_logger.modules.base.camera_validator import CapabilityValidator
from rpi_logger.modules.Cameras.storage import DiskGuard, KnownCamerasCache
from rpi_logger.modules.Cameras.storage.session_paths import resolve_session_paths
from rpi_logger.modules.Cameras.app.view import CameraView
from rpi_logger.modules.Cameras.webcam_audio import (
    WebcamAudioRecorder,
    WebcamAudioInfo,
    SOUNDDEVICE_AVAILABLE,
)

try:
    from vmc.runtime import ModuleRuntime, RuntimeContext
except Exception:
    ModuleRuntime = object
    RuntimeContext = Any

logger = get_module_logger(__name__)


class CamerasRuntime(ModuleRuntime):
    """Single-camera runtime receiving assign_device command with camera details."""

    def __init__(self, ctx: RuntimeContext) -> None:
        self.ctx = ctx
        self.logger = ctx.logger.getChild("Cameras") if hasattr(ctx, "logger") else logger
        self.module_dir = ctx.module_dir
        scope_fn = getattr(ctx.model, "preferences_scope", None)
        prefs = scope_fn("cameras") if callable(scope_fn) else None
        self.config = CamerasConfig.from_preferences(prefs, ctx.args, logger=self.logger)
        self._camera_id: Optional[CameraId] = None
        self._descriptor: Optional[CameraDescriptor] = None
        self._capabilities: Optional[CameraCapabilities] = None
        self._validator: Optional[CapabilityValidator] = None
        self._capture: Optional[CaptureHandle] = None
        self._encoder: Optional[Encoder] = None
        self._is_assigned: bool = False
        self._is_recording: bool = False
        self._camera_name: Optional[str] = None
        self._known_model = None
        self._resolution: tuple[int, int] = (1280, 720)
        self._fps: float = 30.0
        self._overlay_enabled: bool = True
        self._preview_resolution: tuple[int, int] = (640, 480)
        self._preview_fps: float = 5.0
        self._session_dir: Optional[Path] = None
        self._trial_number: int = 1
        self._trial_label: str = ""
        self._capture_task: Optional[asyncio.Task] = None
        self._audio_info: Optional[WebcamAudioInfo] = None
        self._audio_recorder: Optional[WebcamAudioRecorder] = None
        self._record_audio: bool = True
        self.cache = KnownCamerasCache(self.module_dir / "storage" / "known_cameras.json", logger=self.logger)
        self.model_db = CameraModelDatabase(self.module_dir / "storage" / "camera_models.json", logger=self.logger)
        self.disk_guard = DiskGuard(threshold_gb=self.config.guard.disk_free_gb_min, logger=self.logger)
        self.view = CameraView(ctx.view, logger=self.logger)

    async def start(self) -> None:
        """Start runtime - wait for camera assignment."""
        self.logger.info("CAMERAS RUNTIME STARTING")
        await self.cache.load()
        if self.ctx.view:
            with contextlib.suppress(Exception):
                self.ctx.view.set_preview_title("Camera")
            if hasattr(self.ctx.view, 'set_data_subdir'):
                self.ctx.view.set_data_subdir("Cameras")
        self.view.attach()
        self.view.bind_handlers(apply_config=self._on_apply_config, control_change=self._on_control_change, reprobe=self._on_reprobe)
        self.logger.info("Cameras runtime ready")
        StatusMessage.send("ready")

    async def shutdown(self) -> None:
        self.logger.info("Shutting down Cameras runtime")
        if self._is_recording:
            await self._stop_recording()
        if self._capture:
            await self._release_camera()

    async def cleanup(self) -> None:
        pass

    async def handle_command(self, command: Dict[str, Any]) -> bool:
        action = (command.get("command") or "").lower()
        if action == "assign_device":
            return await self._assign_camera(command)
        if action == "unassign_device":
            await self._release_camera()
            return True
        if action == "unassign_all_devices":
            command_id = command.get("command_id")
            port_released = bool(self._capture)
            if self._capture:
                await self._release_camera()
            StatusMessage.send(StatusType.DEVICE_UNASSIGNED, {
                "device_id": self._camera_id.stable_id if self._camera_id else "",
                "port_released": port_released,
            }, command_id=command_id)
            return True
        if action in {"start_recording", "record"}:
            if sd := command.get("session_dir"):
                self._session_dir = Path(sd)
            if (tn := command.get("trial_number")) is not None:
                self._trial_number = int(tn)
            self._trial_label = str(command.get("trial_label", ""))
            await self._start_recording()
            return True
        if action in {"stop_recording", "pause", "pause_recording"}:
            await self._stop_recording()
            return True
        if action == "resume_recording":
            await self._start_recording()
            return True
        if action == "start_session":
            if sd := command.get("session_dir"):
                self._session_dir = Path(sd)
            return True
        if action == "stop_session":
            if self._is_recording:
                await self._stop_recording()
            return True
        return False

    async def handle_user_action(self, action: str, **kwargs: Any) -> bool:
        return await self.handle_command({"command": action, **kwargs})

    async def healthcheck(self) -> Dict[str, Any]:
        return {"assigned": self._is_assigned, "recording": self._is_recording,
                "camera_id": self._camera_id.key if self._camera_id else None}

    async def on_session_dir_available(self, path: Path) -> None:
        self._session_dir = path

    async def _assign_camera(self, command: Dict[str, Any]) -> bool:
        """Handle camera assignment (called once per instance)."""
        if self._is_assigned:
            StatusMessage.send("device_ready", {"device_id": command.get("device_id")}, command_id=command.get("command_id"))
            return True
        command_id, device_id = command.get("command_id"), command.get("device_id")
        camera_type, stable_id = command.get("camera_type"), command.get("camera_stable_id")
        dev_path, display_name = command.get("camera_dev_path"), command.get("display_name", "")
        self.logger.info("Assigning camera: %s (type=%s)", device_id, camera_type)
        self._camera_id = CameraId(backend=camera_type, stable_id=stable_id, friendly_name=display_name, dev_path=dev_path)
        self._descriptor = CameraDescriptor(camera_id=self._camera_id, hw_model=command.get("camera_hw_model"), location_hint=command.get("camera_location"))
        self._audio_info = WebcamAudioInfo.from_command(command)
        if self._audio_info and SOUNDDEVICE_AVAILABLE:
            try:
                self._audio_recorder = WebcamAudioRecorder(self._audio_info, self.logger)
                self._audio_recorder.start_stream()
            except Exception as e:
                self.logger.warning("Failed to initialize webcam audio: %s", e)
                self._audio_recorder = None

        try:
            model_name = extract_model_name(self._descriptor)
            camera_key = self._camera_id.key
            cached_model_key = await self.cache.get_model_key(camera_key)
            use_fast_path, known_model = False, None
            if cached_model_key and model_name:
                known_model = self.model_db.get(cached_model_key)
                if known_model and any(fnmatch.fnmatch(model_name, p) for p in known_model.match_patterns):
                    use_fast_path = self.model_db.can_trust_cache(cached_model_key)
            if use_fast_path:
                self._capabilities = copy_capabilities(known_model.capabilities)
                self._known_model = known_model
                self.logger.info("Using cached capabilities for '%s'", model_name)
            else:
                known_model = self.model_db.lookup(model_name, camera_type) if model_name else None
                probed_caps = await self._probe_camera(camera_type, stable_id, dev_path)
                if known_model and probed_caps:
                    cached_caps = copy_capabilities(known_model.capabilities)
                    if CapabilityValidator(cached_caps).fingerprint() == CapabilityValidator(probed_caps).fingerprint():
                        self._capabilities, self._known_model = cached_caps, known_model
                    else:
                        self._capabilities = probed_caps
                        self._known_model = self.model_db.add_model(model_name, camera_type, probed_caps, force_update=True)
                elif probed_caps:
                    self._capabilities = probed_caps
                    if model_name:
                        self._known_model = self.model_db.add_model(model_name, camera_type, probed_caps)
                elif known_model:
                    self._capabilities = copy_capabilities(known_model.capabilities)
                    self._known_model = known_model
                else:
                    self._capabilities = None
                if self._known_model and self._capabilities:
                    await self.cache.set_model_association(camera_key, self._known_model.key, CapabilityValidator(self._capabilities).fingerprint())
            self._validator = CapabilityValidator(self._capabilities) if self._capabilities else None
            self._resolution, self._fps = await self._get_capture_settings()
            await self._init_capture(camera_type, stable_id, dev_path)
            self._is_assigned = True
            self._camera_name = display_name or device_id
            self.view.set_camera_id(self._camera_id.key)
            self.view.set_camera_info(self._camera_name, self._capabilities)
            if self._capabilities:
                self.view.update_camera_capabilities(self._capabilities, hw_model=self._descriptor.hw_model if self._descriptor else None, backend=camera_type, sensor_info=self._known_model.sensor_info if self._known_model else None, display_name=self._known_model.name if self._known_model else self._camera_name)
            self.view.set_has_audio_sibling(self._audio_info is not None)
            if self.ctx.view and display_name:
                with contextlib.suppress(Exception):
                    self.ctx.view.set_window_title(display_name)
            self._capture_task = asyncio.create_task(self._capture_loop(), name="camera_capture_loop")
            StatusMessage.send("device_ready", {"device_id": device_id}, command_id=command_id)
            self.logger.info("Camera assigned: %s", self._camera_id.key)
            return True
        except Exception as e:
            self.logger.error("Failed to assign camera: %s", e, exc_info=True)
            StatusMessage.send("device_error", {"device_id": device_id, "error": str(e)}, command_id=command_id)
            return False

    async def _probe_camera(self, camera_type: str, stable_id: str, dev_path: str) -> Optional[CameraCapabilities]:
        """Probe camera capabilities."""
        try:
            return await usb_backend.probe(dev_path, logger=self.logger)
        except Exception as e:
            self.logger.warning("Failed to probe camera: %s", e)
            return None

    async def _get_capture_settings(self) -> tuple[tuple[int, int], float]:
        """Get resolution/FPS from cache or capabilities (validated)."""
        if not self._validator:
            return (1280, 720), 30.0
        if self._camera_id and (cached := await self.cache.get_settings(self._camera_id.key)):
            validated = self._validator.validate_settings(cached)
            res_str, fps_str = validated.get("record_resolution"), validated.get("record_fps")
            if res_str and "x" in res_str and fps_str:
                try:
                    w, h = map(int, res_str.split("x"))
                    return (w, h), float(fps_str)
                except Exception:
                    pass
        if self._capabilities:
            if (dm := self._capabilities.default_record_mode):
                return dm.size, dm.fps
            if self._capabilities.modes:
                best = max(self._capabilities.modes, key=lambda m: m.width * m.height)
                res = (best.width, best.height)
                fps = max((m.fps for m in self._capabilities.modes if (m.width, m.height) == res), default=best.fps)
                return res, fps
        return (1280, 720), 30.0

    async def _init_capture(self, camera_type: str, stable_id: str, dev_path: str) -> None:
        self._capture = USBCapture(dev_path, self._resolution, self._fps)
        await self._capture.start()

    async def _release_camera(self) -> None:
        if self._capture_task:
            self._capture_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._capture_task
            self._capture_task = None
        if self._capture:
            await self._capture.stop()
            self._capture = None
        if self._audio_recorder:
            try:
                if self._audio_recorder.is_recording:
                    self._audio_recorder.stop_recording()
                self._audio_recorder.stop_stream()
            except Exception:
                pass
            self._audio_recorder = None
            self._audio_info = None
        self._is_assigned = False

    async def _start_recording(self) -> None:
        if self._is_recording or not self._capture or not self._session_dir or not self._camera_id:
            return
        if not await asyncio.to_thread(self.disk_guard.check, self._session_dir):
            self.logger.error("Insufficient disk space")
            return
        paths = resolve_session_paths(session_dir=self._session_dir, camera_id=self._camera_id, trial_number=self._trial_number)
        self._encoder = Encoder(video_path=str(paths.video_path), resolution=self._resolution, fps=self._fps, overlay_enabled=self._overlay_enabled, csv_path=str(paths.timing_path), trial_number=self._trial_number)
        await asyncio.to_thread(self._encoder.start)
        audio_path = None
        if self._audio_recorder and self._record_audio:
            try:
                self._audio_recorder.start_recording(self._session_dir, self._camera_id.key, self._trial_number)
                audio_path = self._audio_recorder._wave_path
            except Exception as e:
                self.logger.warning("Failed to start webcam audio: %s", e)
        self._is_recording = True
        status_data = {"video_path": str(paths.video_path), "camera_id": self._camera_id.key}
        if audio_path:
            status_data["audio_path"] = str(audio_path)
        StatusMessage.send("recording_started", status_data)

    async def _stop_recording(self) -> None:
        if not self._is_recording:
            return
        self._is_recording = False
        if self._audio_recorder and self._audio_recorder.is_recording:
            with contextlib.suppress(Exception):
                self._audio_recorder.stop_recording()
        if self._encoder:
            await asyncio.to_thread(self._encoder.stop)
            self._encoder = None
        StatusMessage.send("recording_stopped", {"camera_id": self._camera_id.key if self._camera_id else None})

    def _on_apply_config(self, camera_id: str, settings: Dict[str, str]) -> None:
        """Handle resolution/FPS config change."""
        if camera_id != (self._camera_id.key if self._camera_id else None):
            return
        if self._validator:
            settings = self._validator.validate_settings(settings)
        res_str, fps_str = settings.get("record_resolution", ""), settings.get("record_fps", "")

        if res_str and "x" in res_str:
            with contextlib.suppress(ValueError):
                w, h = map(int, res_str.split("x"))
                self._resolution = (w, h)
        if fps_str:
            with contextlib.suppress(ValueError):
                self._fps = float(fps_str)
        preview_res, preview_fps = settings.get("preview_resolution", ""), settings.get("preview_fps", "")
        if preview_res and "x" in preview_res:
            with contextlib.suppress(ValueError):
                self._preview_resolution = tuple(map(int, preview_res.split("x")))
        if preview_fps:
            with contextlib.suppress(ValueError):
                self._preview_fps = float(preview_fps)
        self._overlay_enabled = settings.get("overlay", "true").lower() == "true"
        self._record_audio = settings.get("record_audio", "true").lower() == "true"
        asyncio.create_task(self._save_settings_to_cache(settings))
        if self._is_assigned and self._capture and (res_str or fps_str):
            asyncio.create_task(self._reinit_capture())

    async def _save_settings_to_cache(self, settings: Dict[str, str]) -> None:
        if self._camera_id:
            with contextlib.suppress(Exception):
                await self.cache.set_settings(self._camera_id.key, settings)

    async def _reinit_capture(self) -> None:
        if not self._camera_id:
            return
        if self._capture_task:
            self._capture_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._capture_task
            self._capture_task = None
        if self._capture:
            await self._capture.stop()
            self._capture = None
        await self._init_capture(self._camera_id.backend, self._camera_id.stable_id, self._camera_id.dev_path)
        self._capture_task = asyncio.create_task(self._capture_loop(), name="camera_capture_loop")

    def _on_control_change(self, camera_id: str, control_name: str, value: Any) -> None:
        """Handle camera control change."""
        if camera_id != (self._camera_id.key if self._camera_id else None) or not self._capture:
            return
        if self._validator:
            value = self._validator.validate_control(control_name, value).corrected_value
        with contextlib.suppress(Exception):
            if hasattr(self._capture, "set_control"):
                self._capture.set_control(control_name, value)

    def _on_reprobe(self, camera_id: str) -> None:
        if camera_id == (self._camera_id.key if self._camera_id else None):
            asyncio.create_task(self._do_reprobe())

    async def _do_reprobe(self) -> None:
        if not self._camera_id:
            return
        try:
            self._capabilities = await self._probe_camera(self._camera_id.backend, self._camera_id.stable_id, self._camera_id.dev_path)
            if self._capabilities:
                self._validator = CapabilityValidator(self._capabilities)
                self.view.set_camera_info(self._camera_name or self._camera_id.key, self._capabilities)
                self.view.set_camera_id(self._camera_id.key)
                self.view.update_camera_capabilities(self._capabilities, hw_model=self._descriptor.hw_model if self._descriptor else None, backend=self._camera_id.backend, sensor_info=self._known_model.sensor_info if self._known_model else None, display_name=self._known_model.name if self._known_model else self._camera_name)
        except Exception as e:
            self.logger.error("Reprobe failed: %s", e)

    async def _capture_loop(self) -> None:
        """Main capture and preview loop."""
        import time
        if not self._capture:
            return
        frame_count, encode_count = 0, 0
        preview_interval = max(1, int(self._fps / self._preview_fps)) if self._preview_fps > 0 else 2
        fps_start, fps_frames, fps_preview, fps_encode = time.monotonic(), 0, 0, 0
        fps_vals = [0.0, 0.0, 0.0]  # capture, preview, encode
        try:
            async for frame in self._capture.frames():
                frame_count += 1
                fps_frames += 1
                now = time.monotonic()
                if self._is_recording and self._encoder:
                    if self._encoder.write_frame(frame.data, timestamp=frame.wall_time, pts_time_ns=frame.sensor_timestamp_ns, color_format=frame.color_format):
                        encode_count += 1
                        fps_encode += 1
                if frame_count % preview_interval == 0:
                    if (pf := self._make_preview_frame(frame)) is not None:
                        self.view.push_frame(pf)
                        fps_preview += 1
                elapsed = now - fps_start
                if elapsed >= 1.0:
                    fps_vals = [fps_frames / elapsed, fps_preview / elapsed, fps_encode / elapsed]
                    fps_start, fps_frames, fps_preview, fps_encode = now, 0, 0, 0
                if frame_count % 30 == 0:
                    metrics = {"frames_captured": frame_count, "frames_recorded": encode_count, "is_recording": self._is_recording, "fps_capture": fps_vals[0], "fps_encode": fps_vals[2] if self._is_recording else None, "fps_preview": fps_vals[1], "target_fps": self._fps, "target_record_fps": self._fps if self._is_recording else None, "target_preview_fps": self._fps / preview_interval}
                    if self._is_recording and self._encoder:
                        metrics["frames_dropped"] = self._encoder.frames_dropped
                        metrics["encode_queue_depth"] = self._encoder.queue_depth
                    self.view.update_metrics(metrics)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.error("Capture loop error: %s", e, exc_info=True)

    def _make_preview_frame(self, frame: CaptureFrame) -> Optional[bytes]:
        """Create PPM preview frame scaled to canvas size."""
        import cv2, io
        from PIL import Image
        try:
            bgr = frame.data
            h, w = bgr.shape[:2]
            target_w, target_h = self.view.get_canvas_size()
            if w != target_w or h != target_h:
                scale = min(target_w / w, target_h / h)
                new_w, new_h = int(w * scale), int(h * scale)
                if new_w > 0 and new_h > 0:
                    bgr = cv2.resize(bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)
            buf = io.BytesIO()
            Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)).save(buf, format="PPM")
            return buf.getvalue()
        except Exception:
            return None


def factory(ctx: RuntimeContext) -> CamerasRuntime:
    return CamerasRuntime(ctx)
