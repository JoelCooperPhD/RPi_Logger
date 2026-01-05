"""Single-camera runtime for Cameras module.

Each Cameras instance handles exactly ONE camera. Device assignment
comes from the main logger via assign_device command.

This follows the same pattern as DRT, VOG, and EyeTracker modules.
"""

from __future__ import annotations

import asyncio
import contextlib
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
from rpi_logger.modules.Cameras.camera_models import (
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
    """Single-camera runtime - one camera per module instance.

    Follows the same pattern as DRT, VOG, and EyeTracker modules.
    Device discovery happens in the main logger; this runtime receives
    a single assign_device command with camera details.
    """

    def __init__(self, ctx: RuntimeContext) -> None:
        self.ctx = ctx
        self.logger = ctx.logger.getChild("Cameras") if hasattr(ctx, "logger") else logger
        self.module_dir = ctx.module_dir

        # Build typed config via preferences_scope
        scope_fn = getattr(ctx.model, "preferences_scope", None)
        prefs = scope_fn("cameras") if callable(scope_fn) else None
        self.typed_config = CamerasConfig.from_preferences(prefs, ctx.args, logger=self.logger) if prefs else CamerasConfig.from_preferences(None, ctx.args, logger=self.logger)
        self.config = self.typed_config

        # Single camera state
        self._camera_id: Optional[CameraId] = None
        self._descriptor: Optional[CameraDescriptor] = None
        self._capabilities: Optional[CameraCapabilities] = None
        self._validator: Optional[CapabilityValidator] = None  # For settings validation
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

        # Webcam audio sibling (built-in microphone)
        self._audio_info: Optional[WebcamAudioInfo] = None
        self._audio_recorder: Optional[WebcamAudioRecorder] = None
        self._record_audio: bool = True  # User preference: record audio with video

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
        self.view = CameraView(ctx.view, logger=self.logger)

    # ------------------------------------------------------------------ Lifecycle

    async def start(self) -> None:
        """Start runtime - wait for camera assignment."""
        self.logger.info("=" * 60)
        self.logger.info("CAMERAS RUNTIME STARTING (single-camera architecture)")
        self.logger.info("=" * 60)

        await self.cache.load()

        if self.ctx.view:
            with contextlib.suppress(Exception):
                self.ctx.view.set_preview_title("Camera")
            if hasattr(self.ctx.view, 'set_data_subdir'):
                self.ctx.view.set_data_subdir("Cameras")

        self.view.attach()
        self.view.bind_handlers(
            apply_config=self._on_apply_config,
            control_change=self._on_control_change,
            reprobe=self._on_reprobe,
        )

        self.logger.info("Cameras runtime ready - waiting for device assignment")
        StatusMessage.send("ready")

    async def shutdown(self) -> None:
        """Shutdown runtime - stop recording and release camera."""
        self.logger.info("Shutting down Cameras runtime")

        if self._is_recording:
            await self._stop_recording()

        if self._capture:
            await self._release_camera()

    async def cleanup(self) -> None:
        """Final cleanup."""
        self.logger.debug("Cameras runtime cleanup complete")

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
        """Handle camera assignment from main logger.

        This is called ONCE per instance with the camera to use.
        """
        if self._is_assigned:
            self.logger.warning("Camera already assigned - rejecting new assignment")
            # Still acknowledge since this camera is working
            device_id = command.get("device_id")
            command_id = command.get("command_id")
            StatusMessage.send("device_ready", {"device_id": device_id}, command_id=command_id)
            return True

        command_id = command.get("command_id")
        device_id = command.get("device_id")
        camera_type = command.get("camera_type")  # "usb" or "picam"
        stable_id = command.get("camera_stable_id")
        dev_path = command.get("camera_dev_path")
        display_name = command.get("display_name", "")

        self.logger.info("Assigning camera: %s (type=%s, stable_id=%s)",
                        device_id, camera_type, stable_id)

        # Build camera ID and descriptor
        self._camera_id = CameraId(
            backend=camera_type,
            stable_id=stable_id,
            friendly_name=display_name,
            dev_path=dev_path,
        )
        self._descriptor = CameraDescriptor(
            camera_id=self._camera_id,
            hw_model=command.get("camera_hw_model"),
            location_hint=command.get("camera_location"),
        )

        # Check for built-in microphone (audio sibling)
        self._audio_info = WebcamAudioInfo.from_command(command)
        if self._audio_info:
            self.logger.info(
                "Camera has built-in microphone: sounddevice index=%d, rate=%.0f Hz",
                self._audio_info.sounddevice_index,
                self._audio_info.sample_rate,
            )
            # Create audio recorder if sounddevice is available
            if SOUNDDEVICE_AVAILABLE:
                try:
                    self._audio_recorder = WebcamAudioRecorder(
                        self._audio_info, self.logger
                    )
                    self._audio_recorder.start_stream()
                except Exception as e:
                    self.logger.warning("Failed to initialize webcam audio: %s", e)
                    self._audio_recorder = None
            else:
                self.logger.debug("sounddevice not available - webcam audio disabled")

        try:
            # Check model database for cached capabilities
            model_name = extract_model_name(self._descriptor)
            known_model = self.model_db.lookup(model_name, camera_type) if model_name else None

            # Always probe to verify capabilities (Phase 7: detect hardware swaps)
            probed_caps = await self._probe_camera(camera_type, stable_id, dev_path)

            if known_model and probed_caps:
                # Compare fingerprints to detect hardware changes
                cached_caps = copy_capabilities(known_model.capabilities)
                cached_validator = CapabilityValidator(cached_caps)
                probed_validator = CapabilityValidator(probed_caps)

                if cached_validator.fingerprint() == probed_validator.fingerprint():
                    # Fingerprint matches - use cached (may have more complete data)
                    self._capabilities = cached_caps
                    self._known_model = known_model
                    self.logger.info(
                        "Verified capabilities for '%s' (model: %s)",
                        model_name, known_model.key
                    )
                else:
                    # Fingerprint mismatch - different hardware, use probed
                    self.logger.warning(
                        "Capability mismatch for '%s' - camera hardware may have changed. "
                        "Using probed capabilities.",
                        model_name
                    )
                    self._capabilities = probed_caps
                    self._known_model = self.model_db.add_model(
                        model_name, camera_type, probed_caps, force_update=True
                    )
            elif probed_caps:
                # New camera - use probed capabilities
                self._capabilities = probed_caps
                if model_name:
                    self._known_model = self.model_db.add_model(model_name, camera_type, probed_caps)
                    self.logger.info("Cached new camera model: %s", model_name)
            elif known_model:
                # Probe failed but we have cached - use cached as fallback
                self._capabilities = copy_capabilities(known_model.capabilities)
                self._known_model = known_model
                self.logger.warning(
                    "Probe failed, using cached capabilities for '%s'",
                    model_name
                )
            else:
                # No capabilities available
                self.logger.warning("No capabilities available for camera")
                self._capabilities = None

            # Create validator for capability enforcement
            if self._capabilities:
                self._validator = CapabilityValidator(self._capabilities)
            else:
                self._validator = None

            # Determine capture settings from capabilities (validated)
            self._resolution, self._fps = await self._get_capture_settings()

            # Initialize capture
            await self._init_capture(camera_type, stable_id, dev_path)

            self._is_assigned = True
            self._camera_name = display_name or device_id

            # Update view with camera info
            self.view.set_camera_id(self._camera_id.key)
            self.view.set_camera_info(self._camera_name, self._capabilities)
            if self._capabilities:
                self.view.update_camera_capabilities(
                    self._capabilities,
                    hw_model=self._descriptor.hw_model if self._descriptor else None,
                    backend=camera_type,
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
                name="camera_capture_loop"
            )

            # Acknowledge assignment
            StatusMessage.send("device_ready", {"device_id": device_id}, command_id=command_id)
            self.logger.info("Camera assigned successfully: %s", self._camera_id.key)
            return True

        except Exception as e:
            self.logger.error("Failed to assign camera: %s", e, exc_info=True)
            StatusMessage.send("device_error", {
                "device_id": device_id,
                "error": str(e)
            }, command_id=command_id)
            return False

    async def _probe_camera(
        self,
        camera_type: str,
        stable_id: str,
        dev_path: str
    ) -> Optional[CameraCapabilities]:
        """Probe USB camera capabilities."""
        self.logger.info("Probing USB camera capabilities...")
        try:
            return await usb_backend.probe(dev_path, logger=self.logger)
        except Exception as e:
            self.logger.warning("Failed to probe camera: %s", e)
            return None

    async def _get_capture_settings(self) -> tuple[tuple[int, int], float]:
        """Determine resolution and FPS from capabilities or cache.

        Settings are validated against capabilities using the validator.
        Invalid cached settings are corrected to valid capability modes.
        """
        # If no validator (no capabilities), use safe fallback
        if not self._validator:
            self.logger.info("No capabilities - using default settings: 1280x720 @ 30 fps")
            return (1280, 720), 30.0

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
        self.logger.warning("No valid modes found - using fallback: 1280x720 @ 30 fps")
        return (1280, 720), 30.0

    async def _init_capture(
        self,
        camera_type: str,
        stable_id: str,
        dev_path: str,
    ) -> None:
        """Initialize USB camera capture."""
        self.logger.info("Initializing USB capture @ %dx%d %.1f fps",
                        self._resolution[0], self._resolution[1], self._fps)

        self._capture = USBCapture(dev_path, self._resolution, self._fps)

        await self._capture.start()
        self.logger.info("Capture initialized successfully")

    async def _release_camera(self) -> None:
        """Release camera and cleanup."""
        self.logger.info("Releasing camera")

        # Cancel capture task
        if self._capture_task:
            self._capture_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._capture_task
            self._capture_task = None

        # Stop capture
        if self._capture:
            await self._capture.stop()
            self._capture = None

        # Stop audio recorder if present
        if self._audio_recorder:
            try:
                if self._audio_recorder.is_recording:
                    self._audio_recorder.stop_recording()
                self._audio_recorder.stop_stream()
            except Exception as e:
                self.logger.debug("Error stopping audio recorder: %s", e)
            self._audio_recorder = None
            self._audio_info = None

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

        # Check disk space
        disk_ok = await asyncio.to_thread(self.disk_guard.check, self._session_dir)
        if not disk_ok:
            self.logger.error("Insufficient disk space - cannot start recording")
            return

        # Resolve output paths
        paths = resolve_session_paths(
            session_dir=self._session_dir,
            camera_id=self._camera_id,
            trial_number=self._trial_number,
        )

        # Initialize encoder
        self._encoder = Encoder(
            video_path=str(paths.video_path),
            resolution=self._resolution,
            fps=self._fps,
            overlay_enabled=self._overlay_enabled,
            csv_path=str(paths.timing_path),
            trial_number=self._trial_number,
        )

        await asyncio.to_thread(self._encoder.start)

        # Start audio recording if webcam has built-in mic and audio is enabled
        audio_path = None
        if self._audio_recorder and self._record_audio:
            try:
                self._audio_recorder.start_recording(
                    self._session_dir,
                    self._camera_id.key,
                    self._trial_number,
                )
                audio_path = self._audio_recorder._wave_path
                self.logger.info("Webcam audio recording started")
            except Exception as e:
                self.logger.warning("Failed to start webcam audio recording: %s", e)

        self._is_recording = True
        self.logger.info("Recording started: %s", paths.video_path)
        status_data = {
            "video_path": str(paths.video_path),
            "camera_id": self._camera_id.key,
        }
        if audio_path:
            status_data["audio_path"] = str(audio_path)
        StatusMessage.send("recording_started", status_data)

    async def _stop_recording(self) -> None:
        """Stop video recording."""
        if not self._is_recording:
            return

        self._is_recording = False

        # Stop audio recording first
        audio_path = None
        if self._audio_recorder and self._audio_recorder.is_recording:
            try:
                audio_path = self._audio_recorder.stop_recording()
                if audio_path:
                    self.logger.info("Webcam audio recording stopped: %s", audio_path.name)
            except Exception as e:
                self.logger.warning("Error stopping webcam audio: %s", e)

        if self._encoder:
            frames_dropped = self._encoder.frames_dropped
            await asyncio.to_thread(self._encoder.stop)
            frame_count = self._encoder.frame_count
            duration = self._encoder.duration_sec
            self._encoder = None
            if frames_dropped > 0:
                self.logger.warning(
                    "Recording stopped: %d frames, %.1fs (%d frames dropped due to backpressure)",
                    frame_count, duration, frames_dropped
                )
            else:
                self.logger.info("Recording stopped: %d frames, %.1fs", frame_count, duration)

        StatusMessage.send("recording_stopped", {
            "camera_id": self._camera_id.key if self._camera_id else None,
        })

    # ------------------------------------------------------------------ Settings Handlers

    def _on_apply_config(self, camera_id: str, settings: Dict[str, str]) -> None:
        """Handle resolution/FPS config change from settings window.

        Settings are validated against capabilities before being applied.
        """
        self.logger.debug("_on_apply_config called: camera_id=%s, self._camera_id=%s",
                         camera_id, self._camera_id.key if self._camera_id else None)
        if camera_id != (self._camera_id.key if self._camera_id else None):
            self.logger.warning("Config apply for wrong camera: %s (expected %s)",
                              camera_id, self._camera_id.key if self._camera_id else None)
            return

        # Validate settings against capabilities
        if self._validator:
            validated_settings = self._validator.validate_settings(settings)
            if validated_settings != settings:
                self.logger.info("Settings adjusted for capability compliance: %s -> %s",
                               settings, validated_settings)
            settings = validated_settings

        self.logger.debug("Applying config: %s", settings)

        # Parse record resolution and FPS (affects capture/recording)
        res_str = settings.get("record_resolution", "")
        fps_str = settings.get("record_fps", "")

        if res_str and "x" in res_str:
            try:
                w, h = map(int, res_str.split("x"))
                self._resolution = (w, h)
                self.logger.debug("Record resolution updated to %dx%d", w, h)
            except ValueError:
                self.logger.warning("Invalid record resolution: %s", res_str)

        if fps_str:
            try:
                self._fps = float(fps_str)
                self.logger.debug("Record FPS updated to %.1f", self._fps)
            except ValueError:
                self.logger.warning("Invalid record FPS: %s", fps_str)

        # Parse preview settings (affects display only)
        preview_res_str = settings.get("preview_resolution", "")
        preview_fps_str = settings.get("preview_fps", "")

        if preview_res_str and "x" in preview_res_str:
            try:
                w, h = map(int, preview_res_str.split("x"))
                self._preview_resolution = (w, h)
                self.logger.debug("Preview resolution updated to %dx%d", w, h)
            except ValueError:
                self.logger.warning("Invalid preview resolution: %s", preview_res_str)

        if preview_fps_str:
            try:
                self._preview_fps = float(preview_fps_str)
                self.logger.debug("Preview FPS updated to %.1f", self._preview_fps)
            except ValueError:
                self.logger.warning("Invalid preview FPS: %s", preview_fps_str)

        self._overlay_enabled = settings.get("overlay", "true").lower() == "true"

        # Parse audio recording preference (for webcams with built-in mics)
        record_audio = settings.get("record_audio", "true").lower() == "true"
        if record_audio != self._record_audio:
            self._record_audio = record_audio
            self.logger.info("Webcam audio recording %s", "enabled" if record_audio else "disabled")

        # Save validated settings to cache
        asyncio.create_task(self._save_settings_to_cache(settings))

        # Reinitialize capture only if record settings changed (resolution/fps affect capture)
        # Preview settings don't require reinit - they're applied on-the-fly
        if self._is_assigned and self._capture and (res_str or fps_str):
            asyncio.create_task(self._reinit_capture())

    async def _save_settings_to_cache(self, settings: Dict[str, str]) -> None:
        """Save settings to known cameras cache."""
        if not self._camera_id:
            return
        try:
            await self.cache.set_settings(self._camera_id.key, settings)
            self.logger.debug("Settings saved to cache: %s", self._camera_id.key)
        except Exception as e:
            self.logger.warning("Failed to save settings: %s", e)

    async def _reinit_capture(self) -> None:
        """Reinitialize capture with current settings."""
        if not self._camera_id or not self._descriptor:
            return

        self.logger.debug("Reinitializing capture: %dx%d @ %.1f fps",
                         self._resolution[0], self._resolution[1], self._fps)

        # Stop current capture task
        if self._capture_task:
            self._capture_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._capture_task
            self._capture_task = None

        # Stop and restart capture
        if self._capture:
            await self._capture.stop()
            self._capture = None

        camera_type = self._camera_id.backend
        stable_id = self._camera_id.stable_id
        dev_path = self._camera_id.dev_path

        await self._init_capture(camera_type, stable_id, dev_path)

        # Restart capture loop
        self._capture_task = asyncio.create_task(
            self._capture_loop(),
            name="camera_capture_loop"
        )


    def _on_control_change(self, camera_id: str, control_name: str, value: Any) -> None:
        """Handle camera control change (brightness, contrast, etc.).

        Control values are validated/clamped against capability ranges.
        """
        if camera_id != (self._camera_id.key if self._camera_id else None):
            self.logger.warning("Control change for wrong camera: %s", camera_id)
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
        """Handle reprobe request from settings window."""
        if camera_id != (self._camera_id.key if self._camera_id else None):
            self.logger.warning("Reprobe for wrong camera: %s", camera_id)
            return

        self.logger.debug("Reprobing camera capabilities")
        asyncio.create_task(self._do_reprobe())

    async def _do_reprobe(self) -> None:
        """Perform camera reprobe and update validator."""
        if not self._camera_id:
            return

        camera_type = self._camera_id.backend
        stable_id = self._camera_id.stable_id
        dev_path = self._camera_id.dev_path

        try:
            self._capabilities = await self._probe_camera(camera_type, stable_id, dev_path)
            if self._capabilities:
                # Recreate validator with new capabilities
                self._validator = CapabilityValidator(self._capabilities)

                self.view.set_camera_info(self._camera_name or self._camera_id.key, self._capabilities)
                self.view.set_camera_id(self._camera_id.key)
                self.view.update_camera_capabilities(
                    self._capabilities,
                    hw_model=self._descriptor.hw_model if self._descriptor else None,
                    backend=camera_type,
                    sensor_info=self._known_model.sensor_info if self._known_model else None,
                    display_name=self._known_model.name if self._known_model else self._camera_name,
                )
                self.logger.info("Reprobe complete - validator updated")
            else:
                self.logger.warning("Reprobe failed - no capabilities returned")
        except Exception as e:
            self.logger.error("Reprobe failed: %s", e)

    # ------------------------------------------------------------------ Capture Loop

    async def _capture_loop(self) -> None:
        """Main capture and preview loop."""
        import time

        if not self._capture:
            return

        frame_count = 0
        preview_count = 0
        encode_count = 0

        # Calculate preview interval based on capture FPS and desired preview FPS
        # e.g., if capture is 30fps and preview is 5fps, show every 6th frame
        preview_interval = max(1, int(self._fps / self._preview_fps)) if self._preview_fps > 0 else 2

        # FPS tracking state
        fps_window_start = time.monotonic()
        fps_window_frames = 0
        fps_preview_frames = 0
        fps_encode_frames = 0
        fps_capture = 0.0
        fps_preview = 0.0
        fps_encode = 0.0

        self.logger.debug("Starting capture loop")

        try:
            async for frame in self._capture.frames():
                frame_count += 1
                fps_window_frames += 1
                now = time.monotonic()

                # Recording: submit frame to encode worker
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
                    # Note: backpressure (queue full) is handled by encoder worker

                # Preview: display frame (throttled)
                if frame_count % preview_interval == 0:
                    preview_frame = self._make_preview_frame(frame)
                    if preview_frame is not None:
                        self.view.push_frame(preview_frame)
                        preview_count += 1
                        fps_preview_frames += 1

                # Calculate FPS every second
                elapsed = now - fps_window_start
                if elapsed >= 1.0:
                    fps_capture = fps_window_frames / elapsed
                    fps_preview = fps_preview_frames / elapsed
                    fps_encode = fps_encode_frames / elapsed
                    fps_window_start = now
                    fps_window_frames = 0
                    fps_preview_frames = 0
                    fps_encode_frames = 0

                # Update metrics periodically
                if frame_count % 30 == 0:
                    metrics = {
                        "frames_captured": frame_count,
                        "frames_recorded": encode_count,
                        "is_recording": self._is_recording,
                        # FPS metrics for MetricsDisplay
                        "fps_capture": fps_capture,
                        "fps_encode": fps_encode if self._is_recording else None,
                        "fps_preview": fps_preview,
                        "target_fps": self._fps,
                        "target_record_fps": self._fps if self._is_recording else None,
                        "target_preview_fps": self._fps / preview_interval,
                    }
                    # Include encoder worker stats when recording
                    if self._is_recording and self._encoder:
                        metrics["frames_dropped"] = self._encoder.frames_dropped
                        metrics["encode_queue_depth"] = self._encoder.queue_depth
                    self.view.update_metrics(metrics)

        except asyncio.CancelledError:
            self.logger.info("Capture loop cancelled")
        except Exception as e:
            self.logger.error("Capture loop error: %s", e, exc_info=True)

    def _make_preview_frame(self, frame: CaptureFrame) -> Optional[bytes]:
        """Create preview frame from capture frame.

        Returns PPM bytes ready for tk.PhotoImage(data=...), with:
        - RGB color space (converted from BGR)
        - Scaled to fit canvas dimensions while maintaining aspect ratio
        - Serialized as PPM for fast PhotoImage creation on Tk thread
        """
        import cv2
        import io
        from PIL import Image

        try:
            bgr = frame.data
            h, w = bgr.shape[:2]

            # Get target size from view's canvas, fallback to configured resolution
            target_w, target_h = self.view.get_canvas_size()

            # Scale to fit canvas while maintaining aspect ratio
            if w != target_w or h != target_h:
                scale = min(target_w / w, target_h / h)
                new_w = int(w * scale)
                new_h = int(h * scale)
                if new_w > 0 and new_h > 0:
                    bgr = cv2.resize(bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)

            # Convert BGR to RGB for PIL
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

            # Convert to PPM bytes for fast PhotoImage creation
            img = Image.fromarray(rgb)
            ppm_buffer = io.BytesIO()
            img.save(ppm_buffer, format="PPM")
            return ppm_buffer.getvalue()

        except Exception as e:
            self.logger.debug("Preview frame error: %s", e)
            return None


def factory(ctx: RuntimeContext) -> CamerasRuntime:
    """Factory function for Cameras module."""
    return CamerasRuntime(ctx)
