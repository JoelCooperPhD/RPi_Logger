"""
Cameras runtime bridge - multiprocess worker architecture.

Each camera runs in its own subprocess with independent GIL.
Communication happens via multiprocessing pipes.
"""
from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any, Dict, Optional

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.core.commands import StatusMessage
from rpi_logger.modules.Cameras.app.view import CamerasView
from rpi_logger.modules.Cameras.defaults import DEFAULT_PREVIEW_SIZE, DEFAULT_PREVIEW_FPS
from rpi_logger.modules.Cameras.utils import parse_resolution, parse_fps, CameraMetrics
from rpi_logger.modules.Cameras.bridge_controllers import (
    CameraWorkerState,
    DiscoveryController,
    RecordingController,
)
from rpi_logger.modules.Cameras.config import load_config
from rpi_logger.modules.Cameras.runtime.coordinator import WorkerManager, PreviewReceiver
from rpi_logger.modules.Cameras.runtime import CameraDescriptor, CameraId
from rpi_logger.modules.Cameras.storage import DiskGuard, KnownCamerasCache
from rpi_logger.modules.Cameras.worker.protocol import (
    RespPreviewFrame,
    RespStateUpdate,
    RespRecordingStarted,
    RespRecordingComplete,
    RespReady,
    RespError,
)

try:
    from vmc.runtime import ModuleRuntime, RuntimeContext
except Exception:
    ModuleRuntime = object
    RuntimeContext = Any

logger = get_module_logger(__name__)


class CamerasRuntime(ModuleRuntime):
    """
    Multiprocess ModuleRuntime for Cameras.

    Each camera instance runs in its own module window. The camera
    worker runs in a separate process with its own GIL for optimal
    performance during recording.
    """

    def __init__(self, ctx: RuntimeContext, config_path: Optional[Path] = None) -> None:
        self.ctx = ctx
        self.logger = ctx.logger.getChild("Cameras") if hasattr(ctx, "logger") else logger
        self.module_dir = ctx.module_dir
        self.config = load_config(ctx.model.preferences, overrides=None, logger=self.logger)
        self.cache = KnownCamerasCache(self.module_dir / "storage" / "known_cameras.json", logger=self.logger)
        self.disk_guard = DiskGuard(threshold_gb=self.config.guard.disk_free_gb_min, logger=self.logger)
        self.view = CamerasView(ctx.view, logger=self.logger)
        self.loop: Optional[asyncio.AbstractEventLoop] = None

        # Worker management
        self._preview_receiver = PreviewReceiver()
        self.worker_manager = WorkerManager(
            on_preview_frame=self._on_preview_frame,
            on_state_update=self._on_state_update,
            on_worker_ready=self._on_worker_ready,
            on_recording_started=self._on_recording_started,
            on_recording_complete=self._on_recording_complete,
            on_error=self._on_error,
        )

        # Camera state tracking (key -> CameraWorkerState)
        self.camera_states: Dict[str, CameraWorkerState] = {}

        # Controllers
        self.discovery = DiscoveryController(self, logger=self.logger)
        self.recording = RecordingController(self, logger=self.logger)

        self._telemetry_task: Optional[asyncio.Task] = None
        self._preview_frame_counts: Dict[str, int] = {}
        self._preview_tasks: Dict[str, asyncio.Task] = {}
        self._settings_tasks: Dict[str, asyncio.Task] = {}

    # ------------------------------------------------------------------ Helpers

    async def _cancel_task(self, tasks: Dict[str, asyncio.Task], key: str) -> None:
        """Cancel and await an existing task for key if running."""
        if key in tasks:
            old_task = tasks.pop(key)
            if not old_task.done():
                old_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await old_task

    # ------------------------------------------------------------------ Lifecycle

    async def start(self) -> None:
        self.logger.info("=" * 60)
        self.logger.info("CAMERAS RUNTIME STARTING (multiprocess worker architecture)")
        self.logger.info("=" * 60)
        self.loop = asyncio.get_running_loop()

        self.logger.debug("[STARTUP] Loading camera cache...")
        await self.cache.load()
        self.logger.debug("[STARTUP] Cache loaded")

        if self.ctx.view:
            self.logger.debug("[STARTUP] Setting preview title...")
            with contextlib.suppress(Exception):
                self.ctx.view.set_preview_title("Cameras Preview")

        self.logger.debug("[STARTUP] Binding UI handlers...")
        self.view.bind_handlers(
            apply_config=self._handle_apply_config,
            activate_camera=self._handle_active_camera_changed,
        )

        self.logger.debug("[STARTUP] Attaching view...")
        self.view.attach()
        self.view.set_status("Waiting for camera assignment...")

        self.logger.info("[STARTUP] Cameras module ready - waiting for device assignments from main logger")

        self._telemetry_task = asyncio.create_task(self._telemetry_loop(), name="cameras_telemetry")
        self.logger.info("[STARTUP] Telemetry loop started")
        self.logger.info("=" * 60)
        self.logger.info("CAMERAS RUNTIME STARTED - %d workers active", len(self.worker_manager.workers))
        self.logger.info("=" * 60)

        # Notify logger that module is ready for commands
        # This is the handshake signal that turns the indicator green
        StatusMessage.send("ready")

    async def shutdown(self) -> None:
        self.logger.info("Shutting down Cameras runtime")

        if self._telemetry_task:
            self._telemetry_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._telemetry_task
            self._telemetry_task = None

        # Cancel preview tasks
        for key, task in list(self._preview_tasks.items()):
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._preview_tasks.clear()

        # Cancel settings tasks
        for key, task in list(self._settings_tasks.items()):
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._settings_tasks.clear()

        # Stop recordings first
        if self.recording.is_recording:
            await self.recording.stop_recording()

        # Shutdown all workers
        await self.worker_manager.shutdown_all()

    async def cleanup(self) -> None:
        self.logger.debug("Cameras runtime cleanup")

    # ------------------------------------------------------------------ Commands

    async def handle_command(self, command: Dict[str, Any]) -> bool:
        action = (command.get("command") or "").lower()

        if action == "assign_device":
            command_id = command.get("command_id")
            return await self._assign_camera(command, command_id=command_id)

        if action == "unassign_device":
            return await self._unassign_camera(command)

        if action in {"start_recording", "record"}:
            session_dir = command.get("session_dir")
            trial_number = command.get("trial_number")
            trial_label = str(command.get("trial_label") or "").strip()

            if trial_label:
                self.recording.update_trial_info(trial_label=trial_label)
                setattr(self.ctx.model, "trial_label", trial_label)
            if session_dir:
                with contextlib.suppress(Exception):
                    self.recording.update_session_dir(Path(session_dir))
            if trial_number is not None:
                try:
                    numeric_trial = int(trial_number)
                    setattr(self.ctx.model, "trial_number", numeric_trial)
                    self.recording.update_trial_info(trial_number=numeric_trial)
                except Exception:
                    self.logger.warning("Invalid trial_number: %s", trial_number)

            await self.recording.start_recording()
            return True

        if action in {"stop_recording", "pause", "pause_recording"}:
            await self.recording.stop_recording()
            return True

        if action == "resume_recording":
            await self.recording.start_recording()
            return True

        if action == "start_session":
            session_dir = command.get("session_dir")
            if session_dir:
                with contextlib.suppress(Exception):
                    self.recording.update_session_dir(Path(session_dir))
            return True

        if action == "stop_session":
            await self.recording.handle_stop_session_command()
            return True

        return False

    async def handle_user_action(self, action: str, **kwargs: Any) -> bool:
        return await self.handle_command({"command": action})

    async def healthcheck(self) -> Dict[str, Any]:
        return {"cameras": len(self.worker_manager.workers)}

    async def on_session_dir_available(self, path: Path) -> None:
        with contextlib.suppress(Exception):
            self.recording.update_session_dir(path)

    # ------------------------------------------------------------------ Device Assignment

    async def _assign_camera(self, command: Dict[str, Any], *, command_id: str | None = None) -> bool:
        """Handle camera assignment from main logger.

        Args:
            command: Command payload with camera configuration
            command_id: Correlation ID for acknowledgment tracking

        Returns:
            True if camera was successfully assigned
        """
        device_id = command.get("device_id")
        camera_type = command.get("camera_type")  # "usb" or "picam"
        stable_id = command.get("camera_stable_id")
        dev_path = command.get("camera_dev_path")
        hw_model = command.get("camera_hw_model")
        location = command.get("camera_location")
        display_name = command.get("display_name", "")

        self.logger.info("[ASSIGN] Received camera assignment: %s (type=%s)", device_id, camera_type)

        # Build CameraDescriptor from assignment data
        camera_id = CameraId(
            backend=camera_type,
            stable_id=stable_id,
            friendly_name=display_name,
            dev_path=dev_path,
        )
        descriptor = CameraDescriptor(
            camera_id=camera_id,
            hw_model=hw_model,
            location_hint=location,
        )

        # Check if already assigned
        key = camera_id.key
        if key in self.camera_states:
            self.logger.warning("[ASSIGN] Camera %s already assigned", key)
            # Still send device_ready since the camera is working
            StatusMessage.send("device_ready", {"device_id": device_id}, command_id=command_id)
            return True

        # Spawn worker for this camera
        try:
            await self.discovery._spawn_worker_for(descriptor)
            self.view.set_status("Camera connected")

            # Update window title to show device display name (e.g., "USB: HD PRO Webcam C920")
            if self.ctx.view and display_name:
                with contextlib.suppress(Exception):
                    self.ctx.view.set_window_title(display_name)

            # Send acknowledgement to logger that device is ready
            # This turns the indicator from yellow (CONNECTING) to green (CONNECTED)
            StatusMessage.send("device_ready", {"device_id": device_id}, command_id=command_id)
            return True
        except Exception as e:
            self.logger.error("[ASSIGN] Failed to spawn worker for %s: %s", key, e)
            StatusMessage.send("device_error", {
                "device_id": device_id,
                "error": f"Failed to spawn worker: {e}"
            }, command_id=command_id)
            return False

    async def _unassign_camera(self, command: Dict[str, Any]) -> bool:
        """Handle camera unassignment from main logger."""
        device_id = command.get("device_id")
        self.logger.info("[UNASSIGN] Received camera unassignment: %s", device_id)

        # Find the key for this device_id
        key = self._find_key_for_device(device_id)
        if not key:
            self.logger.warning("[UNASSIGN] Camera %s not found in states", device_id)
            return True

        # Stop recording if active
        state = self.camera_states.get(key)
        if state and state.is_recording:
            await self.worker_manager.stop_recording(key)

        # Shutdown worker
        await self.worker_manager.shutdown_worker(key)
        self.camera_states.pop(key, None)
        self.view.remove_camera(key)
        self.view.set_status("Camera disconnected")
        return True

    def _find_key_for_device(self, device_id: str) -> Optional[str]:
        """Find camera state key matching device_id."""
        # device_id format is "usb:stable_id" or "picam:stable_id"
        # camera_states key format is "backend:stable_id"
        # They should match directly
        if device_id in self.camera_states:
            return device_id
        # Fallback: search by matching stable_id part
        for key in self.camera_states:
            if key == device_id or key.endswith(device_id.split(":")[-1] if ":" in device_id else device_id):
                return key
        return None

    # ------------------------------------------------------------------ Worker Callbacks

    def _on_worker_ready(self, key: str, msg: RespReady) -> None:
        self.logger.info("=" * 40)
        self.logger.info("[WORKER READY] %s", key)
        self.logger.info("  camera_type: %s", msg.camera_type)
        self.logger.info("  camera_id: %s", msg.camera_id)
        self.logger.info("  capabilities: %s", msg.capabilities)
        self.logger.info("=" * 40)

        state = self.camera_states.get(key)
        if state:
            title = state.descriptor.camera_id.friendly_name or key
            self.logger.info("[WORKER READY] Adding camera tab: key=%s title=%s", key, title)
            self.view.add_camera(key, title=title)
            if state.capabilities:
                self.logger.debug("[WORKER READY] Updating capabilities for %s", key)
                self.view.update_camera_capabilities(key, state.capabilities)
        else:
            self.logger.warning("[WORKER READY] No state found for %s - creating tab anyway", key)
            self.view.add_camera(key, title=key)

        # Populate settings window with actual config values
        self._push_config_to_settings(key)

        # Start preview automatically
        self.logger.info("[WORKER READY] Starting preview for %s...", key)
        self._preview_tasks[key] = asyncio.create_task(
            self._start_preview(key), name=f"preview_{key}"
        )

    def _on_preview_frame(self, key: str, msg: RespPreviewFrame) -> None:
        self._preview_frame_counts[key] = self._preview_frame_counts.get(key, 0) + 1
        count = self._preview_frame_counts[key]
        if count == 1 or count % 30 == 0:
            self.logger.debug("[PREVIEW] %s: frame #%d, %dx%d, %d bytes",
                            key, count, msg.width, msg.height, len(msg.frame_data))
        self._preview_receiver.on_preview_frame(key, msg)

    def _on_state_update(self, key: str, msg: RespStateUpdate) -> None:
        self.logger.debug("[STATE] %s: state=%s recording=%s preview=%s fps_cap=%.1f fps_enc=%.1f target=%.1f frames=%d/%d",
                         key, msg.state.name, msg.is_recording, msg.is_previewing,
                         msg.fps_capture, msg.fps_encode, msg.target_fps, msg.frames_captured, msg.frames_recorded)
        metrics = CameraMetrics(
            state=msg.state.name,
            is_recording=msg.is_recording,
            fps_capture=msg.fps_capture,
            fps_encode=msg.fps_encode,
            fps_preview=msg.fps_preview,
            frames_captured=msg.frames_captured,
            frames_recorded=msg.frames_recorded,
            target_fps=msg.target_fps,
            target_record_fps=msg.target_record_fps,
            capture_wait_ms=msg.capture_wait_ms,
        )
        with contextlib.suppress(Exception):
            self.view.update_metrics(key, metrics.to_dict())

    def _on_recording_started(self, key: str, msg: RespRecordingStarted) -> None:
        self.logger.info("[RECORDING STARTED] %s -> %s", key, msg.video_path)
        state = self.camera_states.get(key)
        if state:
            state.video_path = msg.video_path
            state.csv_path = msg.csv_path

    def _on_recording_complete(self, key: str, msg: RespRecordingComplete) -> None:
        self.logger.info("[RECORDING COMPLETE] %s: %d frames, %.1fs", key, msg.frames_total, msg.duration_sec)
        state = self.camera_states.get(key)
        if state:
            state.is_recording = False

    def _on_error(self, key: str, msg: RespError) -> None:
        self.logger.error("[WORKER ERROR] %s: %s (fatal=%s)", key, msg.message, msg.fatal)
        if msg.fatal:
            self.view.set_status(f"Error: {msg.message}")

    # ------------------------------------------------------------------ Preview

    async def _start_preview(self, key: str) -> None:
        """Start preview streaming for a camera."""
        self.logger.info("[PREVIEW START] Setting up preview for %s...", key)

        # Track frames pushed to view for debugging
        frame_count = [0]
        def consumer(frame):
            frame_count[0] += 1
            if frame_count[0] == 1 or frame_count[0] % 30 == 0:
                self.logger.debug("[PREVIEW PUSH] %s: pushing frame #%d to view, shape=%s",
                                key, frame_count[0], frame.shape if hasattr(frame, 'shape') else 'unknown')
            self.view.push_frame(key, frame)

        self._preview_receiver.set_consumer(key, consumer)
        self.logger.debug("[PREVIEW START] Consumer registered for %s", key)

        # Get per-camera settings (or defaults)
        preview_size, target_fps = await self._get_preview_settings(key)

        self.logger.info("[PREVIEW START] Sending start_preview command to worker %s (size=%s, fps=%.1f)",
                        key, preview_size, target_fps)
        await self.worker_manager.start_preview(
            key,
            preview_size=preview_size,
            target_fps=target_fps,
            jpeg_quality=80,
        )
        self.logger.info("[PREVIEW START] Preview started for %s", key)

    async def _get_preview_settings(self, key: str) -> tuple[tuple[int, int], float]:
        """Get preview size and fps for a camera from saved settings or defaults."""
        saved = await self.cache.get_settings(key)

        preview_size = parse_resolution(
            saved.get("preview_resolution") if saved else None,
            DEFAULT_PREVIEW_SIZE
        )
        target_fps = parse_fps(
            saved.get("preview_fps") if saved else None,
            DEFAULT_PREVIEW_FPS
        )

        return preview_size, target_fps

    def _handle_active_camera_changed(self, camera_id: Optional[str]) -> None:
        """Handle UI tab switch - all workers preview simultaneously."""
        self.logger.debug("Active camera: %s", camera_id)

    def _handle_apply_config(self, camera_id: str, settings: Dict[str, Any]) -> None:
        """Handle configuration changes from UI - persist and apply settings."""
        self.logger.info("[CONFIG] Applying settings for %s: %s", camera_id, settings)
        # Cancel existing settings task if any, then apply new settings
        self._settings_tasks[camera_id] = asyncio.create_task(
            self._cancel_and_apply_settings(camera_id, settings),
            name=f"settings_{camera_id}"
        )

    async def _cancel_and_apply_settings(self, camera_id: str, settings: Dict[str, Any]) -> None:
        """Cancel existing settings task and apply new settings."""
        await self._cancel_task(self._settings_tasks, camera_id)
        await self._apply_camera_settings(camera_id, settings)

    async def _apply_camera_settings(self, camera_id: str, settings: Dict[str, Any]) -> None:
        """Persist per-camera settings and restart preview/worker as needed."""
        try:
            # Get old settings to detect record setting changes
            old_settings = await self.cache.get_settings(camera_id) or {}

            # Save to cache
            await self.cache.set_settings(camera_id, settings)
            self.logger.debug("[CONFIG] Settings saved for %s", camera_id)

            # Check if record settings changed (requires worker respawn)
            record_settings_changed = (
                old_settings.get("record_resolution") != settings.get("record_resolution") or
                old_settings.get("record_fps") != settings.get("record_fps")
            )

            if record_settings_changed:
                self.logger.info("[CONFIG] Record settings changed for %s - respawning worker", camera_id)
                await self._respawn_worker(camera_id)
            else:
                # Only preview settings changed - just restart preview
                handle = self.worker_manager.get_worker(camera_id)
                if handle and handle.is_previewing:
                    self.logger.info("[CONFIG] Restarting preview for %s with new settings", camera_id)
                    await self.worker_manager.stop_preview(camera_id)
                    await self._start_preview(camera_id)
        except asyncio.CancelledError:
            raise  # Don't catch cancellation
        except (OSError, ValueError, KeyError) as e:
            self.logger.warning("[CONFIG] Failed to apply settings for %s: %s", camera_id, e)
        except Exception as e:
            self.logger.warning("[CONFIG] Unexpected error applying settings for %s: %s", camera_id, e, exc_info=True)

    async def _respawn_worker(self, camera_id: str) -> None:
        """Shutdown and respawn a worker to apply new capture settings."""
        state = self.camera_states.get(camera_id)
        if not state:
            self.logger.warning("[CONFIG] No state found for %s, cannot respawn", camera_id)
            return

        # Remember the descriptor for respawning
        descriptor = state.descriptor

        # Shutdown existing worker
        self.logger.info("[CONFIG] Shutting down worker for %s", camera_id)
        await self.worker_manager.shutdown_worker(camera_id)
        self.camera_states.pop(camera_id, None)
        self.view.remove_camera(camera_id)

        # Respawn with new settings
        self.logger.info("[CONFIG] Respawning worker for %s", camera_id)
        await self.discovery._spawn_worker_for(descriptor)

    def _push_config_to_settings(self, camera_id: str) -> None:
        """Push config values to settings window for a camera (loads from cache if available)."""
        # Schedule async load from cache - track task for graceful shutdown
        self._settings_tasks[camera_id] = asyncio.create_task(
            self._cancel_and_load_settings(camera_id),
            name=f"load_settings_{camera_id}"
        )

    async def _cancel_and_load_settings(self, camera_id: str) -> None:
        """Cancel existing settings task and load settings."""
        await self._cancel_task(self._settings_tasks, camera_id)
        await self._load_and_push_settings(camera_id)

    async def _load_and_push_settings(self, camera_id: str) -> None:
        """Load per-camera settings from cache, falling back to global config."""
        # Try to load saved per-camera settings first
        saved_settings = await self.cache.get_settings(camera_id)

        if saved_settings:
            self.logger.debug("[CONFIG] Loaded saved settings for %s: %s", camera_id, saved_settings)
            settings = dict(saved_settings)
        else:
            # Fall back to global config defaults
            preview_cfg = self.config.preview
            record_cfg = self.config.record

            preview_res = preview_cfg.resolution
            record_res = record_cfg.resolution
            preview_fps = preview_cfg.fps_cap
            record_fps = record_cfg.fps_cap

            settings = {
                "preview_resolution": f"{preview_res[0]}x{preview_res[1]}" if preview_res else "",
                "preview_fps": str(int(preview_fps)) if preview_fps and float(preview_fps).is_integer() else str(preview_fps) if preview_fps else "5",
                "record_resolution": f"{record_res[0]}x{record_res[1]}" if record_res else "",
                "record_fps": str(int(record_fps)) if record_fps and float(record_fps).is_integer() else str(record_fps) if record_fps else "15",
                "overlay": "true" if record_cfg.overlay else "false",
            }
            self.logger.debug("[CONFIG] Using global config for %s: %s", camera_id, settings)

        self.view.update_camera_settings(camera_id, settings)

    # ------------------------------------------------------------------ Metrics

    def collect_metrics(self, camera_key: str) -> Dict[str, Any]:
        """Collect metrics for a camera (used by telemetry)."""
        handle = self.worker_manager.get_worker(camera_key)
        if not handle:
            return {}

        return {
            "state": handle.state.name,
            "is_recording": handle.is_recording,
            "is_previewing": handle.is_previewing,
            "fps_capture": handle.fps_capture,
            "fps_encode": handle.fps_encode,
            "frames_captured": handle.frames_captured,
            "frames_recorded": handle.frames_recorded,
        }

    async def _telemetry_loop(self) -> None:
        """Periodic telemetry emission."""
        interval = max(0.5, self.config.telemetry.emit_interval_ms / 1000.0)
        try:
            while True:
                await asyncio.sleep(interval)
                # Metrics are pushed via callbacks, but we can log snapshots
                if self.config.telemetry.include_metrics:
                    snapshot = {k: self.collect_metrics(k) for k in self.worker_manager.workers}
                    if snapshot:
                        self.logger.debug("Telemetry: %s", snapshot)
        except asyncio.CancelledError:
            return


def factory(ctx: RuntimeContext) -> CamerasRuntime:
    """Factory function for Cameras module."""
    return CamerasRuntime(ctx)
