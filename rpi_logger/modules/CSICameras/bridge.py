"""Single-camera runtime for CSI cameras.

Handles one camera per instance. Device assignment via assign_device command.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
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
    yuv420_to_bgr,
)
from rpi_logger.modules.CSICameras.csi_core.backends import picam_backend
from rpi_logger.modules.base.camera_models import (
    CameraModelDatabase,
    extract_model_name,
    copy_capabilities,
)
from rpi_logger.modules.base.camera_capabilities import build_capabilities
from rpi_logger.modules.CSICameras.config import CSICamerasConfig
from rpi_logger.modules.base.camera_validator import CapabilityValidator
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
    """Single-camera runtime for CSI cameras.

    Receives assign_device command from main logger after discovery.
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
        self._validator: Optional[CapabilityValidator] = None  # For settings validation
        self._capture: Optional[PicamCapture] = None
        self._is_assigned: bool = False
        self._is_recording: bool = False
        self._camera_name: Optional[str] = None
        self._known_model = None  # CameraModel from database (has sensor_info)

        # Capture settings (for recording) - default to full IMX296 sensor resolution
        self._resolution: tuple[int, int] = (1456, 1088)
        self._fps: float = 60.0
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

        # Pending device_ready - sent after first frame captured (prevents CSI lock release too early)
        self._pending_device_ready: Optional[tuple[str, Optional[str]]] = None  # (device_id, command_id)

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

    async def start(self) -> None:
        """Start runtime, wait for camera assignment."""
        self.logger.info("=" * 60)
        self.logger.info("CSI CAMERAS RUNTIME STARTING (single-camera architecture)")
        self.logger.info("=" * 60)

        # Log all startup parameters for debugging
        args = self.ctx.args
        self.logger.info("LAUNCH PARAMETERS:")
        self.logger.info("  instance_id:     %s", getattr(args, "instance_id", None))
        self.logger.info("  camera_index:    %s", getattr(args, "camera_index", None))
        self.logger.info("  output_dir:      %s", getattr(args, "output_dir", None))
        self.logger.info("  session_prefix:  %s", getattr(args, "session_prefix", None))
        self.logger.info("  window_geometry: %s", getattr(args, "window_geometry", None))
        self.logger.info("  config_path:     %s", getattr(args, "config_path", None))
        self.logger.info("  enable_commands: %s", getattr(args, "enable_commands", None))
        self.logger.info("  log_level:       %s", getattr(args, "log_level", None))
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

        # Auto-assign for direct testing if --camera-index provided
        test_camera_index = getattr(self.ctx.args, "camera_index", None)
        instance_id = getattr(self.ctx.args, "instance_id", None)

        if test_camera_index is not None:
            self.logger.info("TEST MODE: Auto-assigning CSI camera %d", test_camera_index)
            await self._assign_camera({
                "command_id": "test_auto_assign",
                "device_id": f"picam:{test_camera_index}",
                "camera_type": "picam",
                "camera_stable_id": str(test_camera_index),
                "camera_dev_path": "",
                "display_name": f"CSI Camera {test_camera_index}",
                "camera_hw_model": None,
                "camera_location": f"CSI{test_camera_index}",
            })
        else:
            # Only auto-assign for standalone/menu launches (no device in instance_id)
            # Multi-instance launches (instance_id contains "picam:") will receive
            # assign_device command from parent - don't double-assign
            if not instance_id or "picam:" not in instance_id:
                self.logger.info("AUTO-ASSIGN: Standalone mode, defaulting to camera 0 (instance_id=%s)", instance_id)
                await self._assign_camera({
                    "command_id": "auto_assign_default",
                    "device_id": "picam:0",
                    "camera_type": "picam",
                    "camera_stable_id": "0",
                    "camera_dev_path": "",
                    "display_name": "CSI Camera 0",
                    "camera_hw_model": None,
                    "camera_location": "CSI0",
                })
            else:
                self.logger.info("MULTI-INSTANCE: Waiting for assign_device command (instance_id=%s)", instance_id)

    async def shutdown(self) -> None:
        """Stop recording and release camera."""
        self.logger.info("Shutting down CSI Cameras runtime")

        if self._is_recording:
            await self._stop_recording()

        if self._capture:
            await self._release_camera()

    async def cleanup(self) -> None:
        """Final cleanup."""

    async def handle_command(self, command: Dict[str, Any]) -> bool:
        """Handle commands from main logger."""
        action = (command.get("command") or "").lower()
        self.logger.debug("Received command: %s (keys: %s)", action, list(command.keys()))

        # Detailed logging for command reception

        if action == "assign_device":
            self.logger.info("Processing assign_device command")
            return await self._assign_camera(command)
        if action == "unassign_device":
            await self._release_camera()
            return True
        if action == "unassign_all_devices":
            command_id = command.get("command_id")
            self.logger.info("Unassigning camera before shutdown (command_id=%s)", command_id)
            port_released = bool(self._capture)
            if port_released:
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
        """Handle UI actions."""
        return await self.handle_command({"command": action, **kwargs})

    async def healthcheck(self) -> Dict[str, Any]:
        """Return health status."""
        return {
            "assigned": self._is_assigned,
            "recording": self._is_recording,
            "camera_id": self._camera_id.key if self._camera_id else None,
        }

    async def on_session_dir_available(self, path: Path) -> None:
        """Set session directory."""
        self._session_dir = path

    async def _assign_camera(self, command: Dict[str, Any]) -> bool:
        """Handle camera assignment."""
        if self._is_assigned:
            # Already assigned - don't send device_ready (it's deferred until first frame)
            # The duplicate assign_device commands are expected during startup
            self.logger.debug("Camera already assigned - ignoring duplicate assignment")
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
            # Extract model name for lookup (no probing - use known capabilities)
            model_name = extract_model_name(self._descriptor)

            # Look up known model - skip probing entirely
            known_model = self.model_db.lookup(model_name, "picam") if model_name else None

            if known_model:
                self._capabilities = copy_capabilities(known_model.capabilities)
                self._known_model = known_model
                self.logger.info(
                    "Using known capabilities for '%s' (model: %s, stable_id: %s)",
                    model_name, known_model.key, stable_id
                )
            else:
                # Fallback to hardcoded defaults for imx296 (most common CSI camera)
                self.logger.info("Using default capabilities for '%s' (stable_id: %s)", model_name, stable_id)
                self._capabilities = build_capabilities([{
                    "size": [1456, 1088],
                    "fps": 60.38,
                    "pixel_format": "RGB",
                }])
                self._known_model = None

            # Create validator for capability enforcement
            if self._capabilities:
                self._validator = CapabilityValidator(self._capabilities)
            else:
                self._validator = None

            # Determine capture settings from capabilities (validated)
            self._resolution, self._fps = await self._get_capture_settings()

            # Initialize capture (CSI only - with lores stream)
            init_start = time.time()
            await self._init_capture(stable_id)
            init_ms = int((time.time() - init_start) * 1000)

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

            # Store pending device_ready - will be sent after first frame captured
            # This prevents CSI camera lock from being released before capture is working
            self._pending_device_ready = (device_id, command_id)
            self.logger.info("CSI Camera assigned, waiting for first frame: %s", self._camera_id.key)
            return True

        except Exception as e:
            self.logger.error("Failed to assign CSI camera: %s", e, exc_info=True)
            StatusMessage.send("device_error", {
                "device_id": device_id,
                "error": str(e)
            }, command_id=command_id)
            return False

    async def _probe_camera(self, stable_id: str) -> Optional[CameraCapabilities]:
        """Probe camera capabilities."""
        self.logger.info("Probing CSI camera capabilities...")
        try:
            return await picam_backend.probe(stable_id, logger=self.logger)
        except Exception as e:
            self.logger.warning("Failed to probe CSI camera: %s", e)
            return None

    async def _get_capture_settings(self) -> tuple[tuple[int, int], float]:
        """Get resolution/FPS from capabilities or cache, validated."""
        # If no validator (no capabilities), use full sensor resolution
        if not self._validator:
            self.logger.info("No capabilities - using full sensor resolution: 1456x1088 @ 60 fps")
            return (1456, 1088), 60.0

        # Try cached settings, validated through validator
        if self._camera_id:
            cached = await self.cache.get_settings(self._camera_id.key)
            if cached:
                # Validate cached settings against capabilities
                validated = self._validator.validate_settings(cached)
                res_str = validated.get("record_resolution")
                fps_str = validated.get("record_fps")

                if res_str and "x" in res_str and fps_str:
                    try:
                        w, h = map(int, res_str.split("x"))
                        resolution = (w, h)
                        fps = float(fps_str)

                        # Log if settings were corrected
                        orig_res = cached.get("record_resolution", "")
                        orig_fps = cached.get("record_fps", "")
                        if orig_res != res_str or orig_fps != fps_str:
                            self.logger.info(
                                "Cached settings corrected: %s@%s -> %dx%d @ %.1f fps",
                                orig_res, orig_fps, w, h, fps
                            )
                        else:
                            self.logger.info("Using cached settings: %dx%d @ %.1f fps", w, h, fps)
                        return resolution, fps
                    except Exception:
                        pass

        # Fall back to capability defaults
        if self._capabilities:
            default_mode = self._capabilities.default_record_mode
            if default_mode:
                self.logger.info(
                    "Using capability default: %dx%d @ %.1f fps",
                    default_mode.width, default_mode.height, default_mode.fps
                )
                return default_mode.size, default_mode.fps

            # No default - pick highest resolution, highest fps
            if self._capabilities.modes:
                best = max(self._capabilities.modes, key=lambda m: m.width * m.height)
                resolution = (best.width, best.height)

                # Pick highest FPS for that resolution
                matching = [m for m in self._capabilities.modes
                           if (m.width, m.height) == resolution]
                fps = max(m.fps for m in matching) if matching else best.fps

                self.logger.info("Using best available: %dx%d @ %.1f fps",
                                resolution[0], resolution[1], fps)
                return resolution, fps

        # Absolute fallback (shouldn't reach here if validator exists)
        self.logger.warning("No valid modes found - using full sensor fallback: 1456x1088 @ 60 fps")
        return (1456, 1088), 60.0

    async def _init_capture(self, stable_id: str) -> None:
        """Initialize capture (software scaling for preview)."""
        self.logger.info("Initializing CSI capture: %dx%d @ %.1f fps",
                        self._resolution[0], self._resolution[1], self._fps)

        # No hardware lores stream - use software scaling for preview
        self._capture = PicamCapture(
            stable_id,
            self._resolution,
            self._fps,
            lores_size=None
        )

        await self._capture.start()
        self.logger.info("CSI capture initialized successfully")

    async def _release_camera(self) -> None:
        """Release camera."""
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

    async def _start_recording(self) -> None:
        """Start recording using picamera2's native H.264 pipeline."""
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

        # Use picamera2's native H.264 recording pipeline
        await self._capture.start_recording(
            video_path=str(paths.video_path),
            csv_path=str(paths.timing_path),
            trial_number=self._trial_number,
            device_id=self._camera_id.key,
        )

        self._is_recording = True
        self.logger.info("Recording started (H.264/MP4): %s", paths.video_path)
        StatusMessage.send("recording_started", {
            "video_path": str(paths.video_path),
            "camera_id": self._camera_id.key,
        })

    async def _stop_recording(self) -> None:
        """Stop recording."""
        if not self._is_recording:
            return

        self._is_recording = False

        if self._capture:
            metrics = await self._capture.stop_recording()
            frame_count = metrics.get("frame_count", 0)
            duration = metrics.get("duration_sec", 0.0)
            frames_dropped = metrics.get("frames_dropped", 0)

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

    def _on_apply_config(self, camera_id: str, settings: Dict[str, str]) -> None:
        """Handle settings change (validated against capabilities)."""
        if camera_id != (self._camera_id.key if self._camera_id else None):
            return

        if self._validator:
            validated = self._validator.validate_settings(settings)
            if validated != settings:
                self.logger.info("Settings adjusted for capability compliance: %s -> %s", settings, validated)
            settings = validated

        def parse_res(key: str) -> Optional[tuple[int, int]]:
            if (s := settings.get(key, "")) and "x" in s:
                try:
                    return tuple(map(int, s.split("x")))
                except ValueError:
                    pass
            return None

        if res := parse_res("record_resolution"):
            self._resolution = res
            self.logger.debug("Record resolution updated to %dx%d", *res)
        if fps_str := settings.get("record_fps"):
            try:
                self._fps = float(fps_str)
                self.logger.debug("Record FPS updated to %.1f", self._fps)
            except ValueError:
                pass
        if prev_res := parse_res("preview_resolution"):
            self._preview_resolution = prev_res
            self.logger.debug("Preview resolution updated to %dx%d", *prev_res)
        if prev_fps := settings.get("preview_fps"):
            try:
                self._preview_fps = float(prev_fps)
                self.logger.debug("Preview FPS updated to %.1f", self._preview_fps)
            except ValueError:
                pass

        self._overlay_enabled = settings.get("overlay", "true").lower() == "true"
        asyncio.create_task(self._save_settings_to_cache(settings))
        if self._is_assigned and self._capture and (settings.get("record_resolution") or settings.get("record_fps")):
            asyncio.create_task(self._reinit_capture())

    async def _save_settings_to_cache(self, settings: Dict[str, str]) -> None:
        """Save to cache."""
        if not self._camera_id:
            return
        try:
            await self.cache.set_settings(self._camera_id.key, settings)
        except Exception as e:
            self.logger.warning("Failed to save settings: %s", e)

    async def _reinit_capture(self) -> None:
        """Reinit capture with new settings."""
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
        """Handle control change (validated/clamped)."""
        if camera_id != (self._camera_id.key if self._camera_id else None):
            return

        # Validate and clamp control value against capabilities
        if self._validator:
            result = self._validator.validate_control(control_name, value)
            if not result.valid:
                self.logger.info(
                    "Control %s value %s corrected to %s: %s",
                    control_name, value, result.corrected_value, result.reason
                )
            value = result.corrected_value

        self.logger.debug("Control change: %s = %s", control_name, value)

        if not self._capture:
            self.logger.warning("Cannot apply control - no capture active")
            return

        # Apply validated control to capture backend
        try:
            if hasattr(self._capture, "set_control"):
                self._capture.set_control(control_name, value)
            else:
                self.logger.debug("Capture backend doesn't support set_control")
        except Exception as e:
            self.logger.warning("Failed to set control %s: %s", control_name, e)

    def _on_reprobe(self, camera_id: str) -> None:
        """Handle reprobe."""
        if camera_id != (self._camera_id.key if self._camera_id else None):
            return
        asyncio.create_task(self._do_reprobe())

    async def _do_reprobe(self) -> None:
        """Reprobe and update validator."""
        if not self._camera_id:
            return

        stable_id = self._camera_id.stable_id

        try:
            self._capabilities = await self._probe_camera(stable_id)
            if self._capabilities:
                # Recreate validator with new capabilities
                self._validator = CapabilityValidator(self._capabilities)

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

    async def _capture_loop(self) -> None:
        """Preview loop - recording handled by picamera2's native pipeline."""
        import time


        if not self._capture:
            return

        frame_count = 0

        preview_interval = max(1, int(self._fps / self._preview_fps)) if self._preview_fps > 0 else 2
        self.logger.info("CAPTURE_LOOP: preview_interval=%d, fps=%.1f, preview_fps=%.1f",
                        preview_interval, self._fps, self._preview_fps)

        fps_window_start = time.monotonic()
        fps_window_frames = 0
        fps_preview_frames = 0
        fps_capture = 0.0
        fps_preview = 0.0

        try:
            async for frame in self._capture.frames():
                frame_count += 1

                # Send deferred device_ready after first frame - this releases the CSI lock
                if frame_count == 1 and self._pending_device_ready:
                    device_id, command_id = self._pending_device_ready
                    self._pending_device_ready = None
                    self.logger.info("First frame captured - sending device_ready: %s", device_id)
                    StatusMessage.send("device_ready", {"device_id": device_id}, command_id=command_id)

                    # Now safe to start command listener (camera init complete, frames flowing)
                    # This is deferred when --camera-index is used to prevent stdin interference
                    controller = getattr(self.ctx, "controller", None)
                    if controller and hasattr(controller, "start_command_listener"):
                        await controller.start_command_listener()

                fps_window_frames += 1
                now = time.monotonic()

                # Preview generation (recording handled by picamera2 internally)
                if frame_count % preview_interval == 0:
                    preview_frame = self._make_preview_frame(frame)
                    if preview_frame is not None:
                        self.view.push_frame(preview_frame)
                        fps_preview_frames += 1

                elapsed = now - fps_window_start
                if elapsed >= 1.0:
                    fps_capture = fps_window_frames / elapsed
                    fps_preview = fps_preview_frames / elapsed
                    fps_window_start = now
                    fps_window_frames = 0
                    fps_preview_frames = 0

                # Update metrics every 30 frames
                if frame_count % 30 == 0:
                    metrics = {
                        "frames_captured": frame_count,
                        "is_recording": self._is_recording,
                        "fps_capture": fps_capture,
                        "fps_preview": fps_preview,
                        "target_fps": self._fps,
                        "target_preview_fps": self._fps / preview_interval,
                    }
                    # Get recording metrics from capture if recording
                    if self._is_recording and self._capture:
                        metrics["frames_recorded"] = self._capture.recording_frame_count
                        metrics["fps_encode"] = fps_capture  # Encoder runs at capture rate
                        metrics["target_record_fps"] = self._fps
                    self.view.update_metrics(metrics)

        except asyncio.CancelledError:
            self.logger.info("Capture loop cancelled")
        except Exception as e:
            self.logger.error("Capture loop error: %s", e, exc_info=True)

    def _make_preview_frame(self, frame: CaptureFrame) -> Optional[bytes]:
        """Create preview from capture frame."""
        import cv2
        import io
        from PIL import Image

        try:
            # Convert YUV420 to BGR for display
            if frame.color_format == "yuv420" or frame.lores_format == "yuv420":
                yuv_data = frame.lores_data if frame.lores_data is not None else frame.data
                bgr = yuv420_to_bgr(yuv_data)
            else:
                bgr = frame.data

            # Crop to actual image size (remove stride padding that causes green bar)
            if self._capture and hasattr(self._capture, 'actual_size'):
                actual_w, actual_h = self._capture.actual_size
                buf_h, buf_w = bgr.shape[:2]
                if buf_w > actual_w or buf_h > actual_h:
                    bgr = bgr[:actual_h, :actual_w]

            h, w = bgr.shape[:2]
            target_w, target_h = self.view.get_canvas_size()

            if w != target_w or h != target_h:
                scale = min(target_w / w, target_h / h)
                new_w = int(w * scale)
                new_h = int(h * scale)
                if new_w > 0 and new_h > 0:
                    bgr = cv2.resize(bgr, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

            img = Image.fromarray(rgb)
            ppm_buffer = io.BytesIO()
            img.save(ppm_buffer, format="PPM")
            return ppm_buffer.getvalue()

        except Exception as e:
            self.logger.debug("Preview frame error: %s", e)
            return None


def factory(ctx: RuntimeContext) -> CSICamerasRuntime:
    """Factory for CSICameras."""
    return CSICamerasRuntime(ctx)
