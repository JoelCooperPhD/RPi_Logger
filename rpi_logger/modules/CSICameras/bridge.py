"""Single-camera runtime for CSICameras module.

Each CSICameras instance handles exactly ONE CSI/Raspberry Pi camera.
Device assignment comes from the main logger via assign_device command.

This follows the same pattern as DRT, VOG, and EyeTracker modules.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any, Dict, Optional

from rpi_logger.core.commands import StatusMessage, StatusType
from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.modules.CSICameras.csi_core import (
    CameraId,
    CameraDescriptor,
    CameraCapabilities,
    CaptureHandle,
    CaptureFrame,
    PicamCapture,
    Encoder,
    yuv420_to_bgr,
)
from rpi_logger.modules.CSICameras.csi_core.backends import picam_backend
from rpi_logger.modules.base.camera_models import (
    CameraModelDatabase,
    extract_model_name,
    copy_capabilities,
)
from rpi_logger.modules.CSICameras.config import CSICamerasConfig
from rpi_logger.modules.base.camera_storage import DiskGuard, KnownCamerasCache
from rpi_logger.modules.CSICameras.storage.session_paths import resolve_session_paths
from rpi_logger.modules.CSICameras.app.view import CSICameraView

try:
    from vmc.runtime import ModuleRuntime, RuntimeContext
except Exception:
    ModuleRuntime = object
    RuntimeContext = Any

logger = get_module_logger(__name__)


class CSICamerasRuntime(ModuleRuntime):
    """Single-camera runtime for CSI/Raspberry Pi cameras.

    Follows the same pattern as DRT, VOG, and EyeTracker modules.
    Device discovery happens in the main logger; this runtime receives
    a single assign_device command with camera details.
    """

    def __init__(self, ctx: RuntimeContext) -> None:
        self.ctx = ctx
        self.logger = ctx.logger.getChild("CSICameras") if hasattr(ctx, "logger") else logger
        self.module_dir = ctx.module_dir

        # Build typed config via preferences_scope
        scope_fn = getattr(ctx.model, "preferences_scope", None)
        prefs = scope_fn("csicameras") if callable(scope_fn) else None
        self.typed_config = CSICamerasConfig.from_preferences(prefs, ctx.args, logger=self.logger) if prefs else CSICamerasConfig.from_preferences(None, ctx.args, logger=self.logger)
        self.config = self.typed_config

        # Single camera state
        self._camera_id: Optional[CameraId] = None
        self._descriptor: Optional[CameraDescriptor] = None
        self._capabilities: Optional[CameraCapabilities] = None
        self._capture: Optional[CaptureHandle] = None
        self._encoder: Optional[Encoder] = None
        self._is_assigned: bool = False
        self._is_recording: bool = False
        self._camera_name: Optional[str] = None
        self._known_model = None  # CameraModel from database (has sensor_info)

        # Capture settings (for recording)
        self._resolution: tuple[int, int] = (1280, 720)
        self._fps: float = 30.0
        self._overlay_enabled: bool = True

        # Preview settings (for display only)
        self._preview_resolution: tuple[int, int] = (640, 480)
        self._preview_fps: float = 5.0

        # Session/recording state
        self._session_dir: Optional[Path] = None
        self._trial_number: int = 1
        self._trial_label: str = ""

        # Background tasks
        self._capture_task: Optional[asyncio.Task] = None

        # Storage
        self.cache = KnownCamerasCache(
            self.module_dir / "storage" / "known_cameras.json",
            logger=self.logger
        )
        self.model_db = CameraModelDatabase(
            self.module_dir / "storage" / "camera_models.json",
            logger=self.logger
        )
        self.disk_guard = DiskGuard(
            threshold_gb=self.config.guard.disk_free_gb_min,
            logger=self.logger
        )

        # View
        self.view = CSICameraView(ctx.view, logger=self.logger)

    # ------------------------------------------------------------------ Lifecycle

    async def start(self) -> None:
        """Start runtime - wait for camera assignment."""
        self.logger.info("=" * 60)
        self.logger.info("CSI CAMERAS RUNTIME STARTING (single-camera architecture)")
        self.logger.info("=" * 60)

        await self.cache.load()

        if self.ctx.view:
            with contextlib.suppress(Exception):
                self.ctx.view.set_preview_title("CSI Camera")
            if hasattr(self.ctx.view, 'set_data_subdir'):
                self.ctx.view.set_data_subdir("CSICameras")

        self.view.attach()
        self.view.bind_handlers(
            apply_config=self._on_apply_config,
            control_change=self._on_control_change,
            reprobe=self._on_reprobe,
        )

        self.logger.info("CSI Cameras runtime ready - waiting for device assignment")
        StatusMessage.send("ready")

    async def shutdown(self) -> None:
        """Shutdown runtime - stop recording and release camera."""
        self.logger.info("Shutting down CSI Cameras runtime")

        if self._is_recording:
            await self._stop_recording()

        if self._capture:
            await self._release_camera()

    async def cleanup(self) -> None:
        """Final cleanup."""
        self.logger.debug("CSI Cameras runtime cleanup complete")

    # ------------------------------------------------------------------ Commands

    async def handle_command(self, command: Dict[str, Any]) -> bool:
        """Handle commands from main logger."""
        action = (command.get("command") or "").lower()
        self.logger.debug("Received command: %s (keys: %s)", action, list(command.keys()))

        if action == "assign_device":
            self.logger.info("Processing assign_device command")
            return await self._assign_camera(command)

        if action == "unassign_device":
            await self._release_camera()
            return True

        if action == "unassign_all_devices":
            # Single-camera module: release current camera if any
            command_id = command.get("command_id")
            self.logger.info("Unassigning camera before shutdown (command_id=%s)", command_id)

            port_released = False
            if self._capture:
                await self._release_camera()
                port_released = True

            # Send ACK to confirm camera release
            StatusMessage.send(
                StatusType.DEVICE_UNASSIGNED,
                {
                    "device_id": self._camera_id.stable_id if self._camera_id else "",
                    "port_released": port_released,
                },
                command_id=command_id,
            )
            return True

        if action in {"start_recording", "record"}:
            session_dir = command.get("session_dir")
            if session_dir:
                self._session_dir = Path(session_dir)
            trial_number = command.get("trial_number")
            if trial_number is not None:
                self._trial_number = int(trial_number)
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
            session_dir = command.get("session_dir")
            if session_dir:
                self._session_dir = Path(session_dir)
            return True

        if action == "stop_session":
            if self._is_recording:
                await self._stop_recording()
            return True

        return False

    async def handle_user_action(self, action: str, **kwargs: Any) -> bool:
        """Handle user actions from UI."""
        return await self.handle_command({"command": action, **kwargs})

    async def healthcheck(self) -> Dict[str, Any]:
        """Return health status."""
        return {
            "assigned": self._is_assigned,
            "recording": self._is_recording,
            "camera_id": self._camera_id.key if self._camera_id else None,
        }

    async def on_session_dir_available(self, path: Path) -> None:
        """Called when session directory becomes available."""
        self._session_dir = path

    # ------------------------------------------------------------------ Camera Assignment

    async def _assign_camera(self, command: Dict[str, Any]) -> bool:
        """Handle camera assignment from main logger."""
        if self._is_assigned:
            self.logger.warning("Camera already assigned - rejecting new assignment")
            device_id = command.get("device_id")
            command_id = command.get("command_id")
            StatusMessage.send("device_ready", {"device_id": device_id}, command_id=command_id)
            return True

        command_id = command.get("command_id")
        device_id = command.get("device_id")
        camera_type = command.get("camera_type")  # Should be "picam" for CSI cameras
        stable_id = command.get("camera_stable_id")
        dev_path = command.get("camera_dev_path")
        display_name = command.get("display_name", "")

        # Verify this is a CSI camera
        if camera_type != "picam":
            self.logger.error("CSICameras only handles picam cameras, got: %s", camera_type)
            StatusMessage.send("device_error", {
                "device_id": device_id,
                "error": f"CSICameras only handles picam cameras, not {camera_type}"
            }, command_id=command_id)
            return False

        self.logger.info("Assigning CSI camera: %s (stable_id=%s)", device_id, stable_id)

        # Build camera ID and descriptor
        self._camera_id = CameraId(
            backend="picam",
            stable_id=stable_id,
            friendly_name=display_name,
            dev_path=dev_path,
        )
        self._descriptor = CameraDescriptor(
            camera_id=self._camera_id,
            hw_model=command.get("camera_hw_model"),
            location_hint=command.get("camera_location"),
        )

        try:
            # Check model database for cached capabilities
            model_name = extract_model_name(self._descriptor)
            known_model = self.model_db.lookup(model_name, "picam") if model_name else None

            if known_model:
                self._capabilities = copy_capabilities(known_model.capabilities)
                self._known_model = known_model
                self.logger.info(
                    "Using cached capabilities for '%s' (model: %s)",
                    model_name, known_model.key
                )
            else:
                self._capabilities = await self._probe_camera(stable_id)
                if self._capabilities and model_name:
                    self._known_model = self.model_db.add_model(model_name, "picam", self._capabilities)
                    self.logger.info("Cached new camera model: %s", model_name)

            # Determine capture settings from capabilities or cache
            self._resolution, self._fps = await self._get_capture_settings()

            # Initialize capture (CSI only - with lores stream)
            await self._init_capture(stable_id)

            self._is_assigned = True
            self._camera_name = display_name or device_id

            # Update view with camera info
            self.view.set_camera_id(self._camera_id.key)
            self.view.set_camera_info(self._camera_name, self._capabilities)
            if self._capabilities:
                self.view.update_camera_capabilities(
                    self._capabilities,
                    hw_model=self._descriptor.hw_model if self._descriptor else None,
                    backend="picam",
                    sensor_info=self._known_model.sensor_info if self._known_model else None,
                    display_name=self._known_model.name if self._known_model else self._camera_name,
                )

            # Update window title
            if self.ctx.view and display_name:
                with contextlib.suppress(Exception):
                    self.ctx.view.set_window_title(display_name)

            # Start capture/preview loop
            self._capture_task = asyncio.create_task(
                self._capture_loop(),
                name="csi_camera_capture_loop"
            )

            # Acknowledge assignment
            StatusMessage.send("device_ready", {"device_id": device_id}, command_id=command_id)
            self.logger.info("CSI Camera assigned successfully: %s", self._camera_id.key)
            return True

        except Exception as e:
            self.logger.error("Failed to assign CSI camera: %s", e, exc_info=True)
            StatusMessage.send("device_error", {
                "device_id": device_id,
                "error": str(e)
            }, command_id=command_id)
            return False

    async def _probe_camera(self, stable_id: str) -> Optional[CameraCapabilities]:
        """Probe CSI camera capabilities using Picamera2."""
        self.logger.info("Probing CSI camera capabilities...")
        try:
            return await picam_backend.probe(stable_id, logger=self.logger)
        except Exception as e:
            self.logger.warning("Failed to probe CSI camera: %s", e)
            return None

    async def _get_capture_settings(self) -> tuple[tuple[int, int], float]:
        """Determine resolution and FPS from capabilities or cache."""
        # Try cached settings first
        if self._camera_id:
            cached = await self.cache.get_settings(self._camera_id.key)
            if cached:
                res_str = cached.get("record_resolution")
                fps_str = cached.get("record_fps")
                if res_str and "x" in res_str:
                    try:
                        w, h = map(int, res_str.split("x"))
                        resolution = (w, h)
                        fps = float(fps_str) if fps_str else 30.0
                        self.logger.info("Using cached settings: %dx%d @ %.1f fps", w, h, fps)
                        return resolution, fps
                    except Exception:
                        pass

        # Fall back to capabilities
        if self._capabilities and self._capabilities.modes:
            best = max(self._capabilities.modes, key=lambda m: m.width * m.height)
            resolution = (best.width, best.height)
            matching = [m for m in self._capabilities.modes if (m.width, m.height) == resolution]
            fps = max(m.fps for m in matching) if matching else best.fps
            self.logger.info("Using probed settings: %dx%d @ %.1f fps", resolution[0], resolution[1], fps)
            return resolution, fps

        self.logger.info("Using default settings: 1280x720 @ 30 fps")
        return (1280, 720), 30.0

    async def _init_capture(self, stable_id: str) -> None:
        """Initialize CSI camera capture with lores stream for preview."""
        self.logger.info("Initializing CSI capture: %dx%d @ %.1f fps",
                        self._resolution[0], self._resolution[1], self._fps)

        # CSI cameras use lores stream for efficient preview
        lores_size = (320, 240)
        self._capture = PicamCapture(
            stable_id,
            self._resolution,
            self._fps,
            lores_size=lores_size
        )

        await self._capture.start()
        self.logger.info("CSI capture initialized successfully")

    async def _release_camera(self) -> None:
        """Release camera and cleanup."""
        self.logger.info("Releasing CSI camera")

        if self._capture_task:
            self._capture_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._capture_task
            self._capture_task = None

        if self._capture:
            await self._capture.stop()
            self._capture = None

        self._is_assigned = False

    # ------------------------------------------------------------------ Recording

    async def _start_recording(self) -> None:
        """Start video recording."""
        if self._is_recording:
            self.logger.debug("Already recording")
            return

        if not self._capture or not self._session_dir or not self._camera_id:
            self.logger.warning("Cannot start recording: camera not ready or no session")
            return

        disk_ok = await asyncio.to_thread(self.disk_guard.check, self._session_dir)
        if not disk_ok:
            self.logger.error("Insufficient disk space - cannot start recording")
            return

        paths = resolve_session_paths(
            session_dir=self._session_dir,
            camera_id=self._camera_id,
            trial_number=self._trial_number,
        )

        self._encoder = Encoder(
            video_path=str(paths.video_path),
            resolution=self._resolution,
            fps=self._fps,
            overlay_enabled=self._overlay_enabled,
            csv_path=str(paths.timing_path),
            trial_number=self._trial_number,
            module_name="CSICameras",
        )

        await asyncio.to_thread(self._encoder.start)

        self._is_recording = True
        self.logger.info("Recording started: %s", paths.video_path)
        StatusMessage.send("recording_started", {
            "video_path": str(paths.video_path),
            "camera_id": self._camera_id.key,
        })

    async def _stop_recording(self) -> None:
        """Stop video recording."""
        if not self._is_recording:
            return

        self._is_recording = False

        if self._encoder:
            frames_dropped = self._encoder.frames_dropped
            await asyncio.to_thread(self._encoder.stop)
            frame_count = self._encoder.frame_count
            duration = self._encoder.duration_sec
            self._encoder = None
            if frames_dropped > 0:
                self.logger.warning(
                    "Recording stopped: %d frames, %.1fs (%d frames dropped)",
                    frame_count, duration, frames_dropped
                )
            else:
                self.logger.info("Recording stopped: %d frames, %.1fs", frame_count, duration)

        StatusMessage.send("recording_stopped", {
            "camera_id": self._camera_id.key if self._camera_id else None,
        })

    # ------------------------------------------------------------------ Settings Handlers

    def _on_apply_config(self, camera_id: str, settings: Dict[str, str]) -> None:
        """Handle resolution/FPS config change from settings window."""
        if camera_id != (self._camera_id.key if self._camera_id else None):
            return

        res_str = settings.get("record_resolution", "")
        fps_str = settings.get("record_fps", "")

        if res_str and "x" in res_str:
            try:
                w, h = map(int, res_str.split("x"))
                self._resolution = (w, h)
            except ValueError:
                pass

        if fps_str:
            try:
                self._fps = float(fps_str)
            except ValueError:
                pass

        preview_res_str = settings.get("preview_resolution", "")
        preview_fps_str = settings.get("preview_fps", "")

        if preview_res_str and "x" in preview_res_str:
            try:
                w, h = map(int, preview_res_str.split("x"))
                self._preview_resolution = (w, h)
            except ValueError:
                pass

        if preview_fps_str:
            try:
                self._preview_fps = float(preview_fps_str)
            except ValueError:
                pass

        self._overlay_enabled = settings.get("overlay", "true").lower() == "true"

        asyncio.create_task(self._save_settings_to_cache(settings))

        if self._is_assigned and self._capture and (res_str or fps_str):
            asyncio.create_task(self._reinit_capture())

    async def _save_settings_to_cache(self, settings: Dict[str, str]) -> None:
        """Save settings to cache."""
        if not self._camera_id:
            return
        try:
            await self.cache.set_settings(self._camera_id.key, settings)
        except Exception as e:
            self.logger.warning("Failed to save settings: %s", e)

    async def _reinit_capture(self) -> None:
        """Reinitialize capture with current settings."""
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

        stable_id = self._camera_id.stable_id
        await self._init_capture(stable_id)

        self._capture_task = asyncio.create_task(
            self._capture_loop(),
            name="csi_camera_capture_loop"
        )

    def _on_control_change(self, camera_id: str, control_name: str, value: Any) -> None:
        """Handle camera control change."""
        if camera_id != (self._camera_id.key if self._camera_id else None):
            return

        if not self._capture:
            return

        try:
            if hasattr(self._capture, "set_control"):
                self._capture.set_control(control_name, value)
        except Exception as e:
            self.logger.warning("Failed to set control %s: %s", control_name, e)

    def _on_reprobe(self, camera_id: str) -> None:
        """Handle reprobe request."""
        if camera_id != (self._camera_id.key if self._camera_id else None):
            return
        asyncio.create_task(self._do_reprobe())

    async def _do_reprobe(self) -> None:
        """Perform camera reprobe."""
        if not self._camera_id:
            return

        stable_id = self._camera_id.stable_id

        try:
            self._capabilities = await self._probe_camera(stable_id)
            if self._capabilities:
                self.view.set_camera_info(self._camera_name or self._camera_id.key, self._capabilities)
                self.view.set_camera_id(self._camera_id.key)
                self.view.update_camera_capabilities(
                    self._capabilities,
                    hw_model=self._descriptor.hw_model if self._descriptor else None,
                    backend="picam",
                    sensor_info=self._known_model.sensor_info if self._known_model else None,
                    display_name=self._known_model.name if self._known_model else self._camera_name,
                )
        except Exception as e:
            self.logger.error("Reprobe failed: %s", e)

    # ------------------------------------------------------------------ Capture Loop

    async def _capture_loop(self) -> None:
        """Main capture and preview loop."""
        import time

        if not self._capture:
            return

        frame_count = 0
        encode_count = 0

        preview_interval = max(1, int(self._fps / self._preview_fps)) if self._preview_fps > 0 else 2

        fps_window_start = time.monotonic()
        fps_window_frames = 0
        fps_preview_frames = 0
        fps_encode_frames = 0
        fps_capture = 0.0
        fps_preview = 0.0
        fps_encode = 0.0

        try:
            async for frame in self._capture.frames():
                frame_count += 1
                fps_window_frames += 1
                now = time.monotonic()

                if self._is_recording and self._encoder:
                    queued = self._encoder.write_frame(
                        frame.data,
                        timestamp=frame.wall_time,
                        pts_time_ns=frame.sensor_timestamp_ns,
                        color_format=frame.color_format,
                    )
                    if queued:
                        encode_count += 1
                        fps_encode_frames += 1

                if frame_count % preview_interval == 0:
                    preview_frame = self._make_preview_frame(frame)
                    if preview_frame is not None:
                        self.view.push_frame(preview_frame)
                        fps_preview_frames += 1

                elapsed = now - fps_window_start
                if elapsed >= 1.0:
                    fps_capture = fps_window_frames / elapsed
                    fps_preview = fps_preview_frames / elapsed
                    fps_encode = fps_encode_frames / elapsed
                    fps_window_start = now
                    fps_window_frames = 0
                    fps_preview_frames = 0
                    fps_encode_frames = 0

                if frame_count % 30 == 0:
                    metrics = {
                        "frames_captured": frame_count,
                        "frames_recorded": encode_count,
                        "is_recording": self._is_recording,
                        "fps_capture": fps_capture,
                        "fps_encode": fps_encode if self._is_recording else None,
                        "fps_preview": fps_preview,
                        "target_fps": self._fps,
                        "target_record_fps": self._fps if self._is_recording else None,
                        "target_preview_fps": self._fps / preview_interval,
                    }
                    if self._is_recording and self._encoder:
                        metrics["frames_dropped"] = self._encoder.frames_dropped
                        metrics["encode_queue_depth"] = self._encoder.queue_depth
                    self.view.update_metrics(metrics)

        except asyncio.CancelledError:
            self.logger.info("Capture loop cancelled")
        except Exception as e:
            self.logger.error("Capture loop error: %s", e, exc_info=True)

    def _make_preview_frame(self, frame: CaptureFrame) -> Optional[bytes]:
        """Create preview frame from capture frame."""
        import cv2
        import io
        from PIL import Image

        try:
            if frame.lores_data is not None and frame.lores_format == "yuv420":
                bgr = yuv420_to_bgr(frame.lores_data)
            else:
                bgr = frame.data

            h, w = bgr.shape[:2]
            target_w, target_h = self.view.get_canvas_size()

            if w != target_w or h != target_h:
                scale = min(target_w / w, target_h / h)
                new_w = int(w * scale)
                new_h = int(h * scale)
                if new_w > 0 and new_h > 0:
                    bgr = cv2.resize(bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)

            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

            img = Image.fromarray(rgb)
            ppm_buffer = io.BytesIO()
            img.save(ppm_buffer, format="PPM")
            return ppm_buffer.getvalue()

        except Exception as e:
            self.logger.debug("Preview frame error: %s", e)
            return None


def factory(ctx: RuntimeContext) -> CSICamerasRuntime:
    """Factory function for CSICameras module."""
    return CSICamerasRuntime(ctx)
