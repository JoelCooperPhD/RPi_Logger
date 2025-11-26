"""
Cameras runtime bridge - multiprocess worker architecture.

Each camera runs in its own subprocess with independent GIL.
Communication happens via multiprocessing pipes.
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path
from typing import Any, Dict, Optional

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.modules.Cameras.app.view import CamerasView
from rpi_logger.modules.Cameras.bridge_controllers import (
    CameraWorkerState,
    DiscoveryController,
    RecordingController,
)
from rpi_logger.modules.Cameras.config import load_config
from rpi_logger.modules.Cameras.runtime.coordinator import WorkerManager, PreviewReceiver
from rpi_logger.modules.Cameras.runtime.discovery.picam import discover_picam
from rpi_logger.modules.Cameras.runtime.discovery.usb import discover_usb_devices
from rpi_logger.modules.Cameras.runtime.registry import Registry
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

    Each camera runs in a separate process with its own GIL,
    eliminating GIL contention when recording multiple cameras.
    """

    def __init__(self, ctx: RuntimeContext, config_path: Optional[Path] = None) -> None:
        self.ctx = ctx
        self.logger = ctx.logger.getChild("Cameras") if hasattr(ctx, "logger") else logger
        self.module_dir = ctx.module_dir
        self.cache = KnownCamerasCache(self.module_dir / "storage" / "known_cameras.json", logger=self.logger)
        self.registry = Registry(cache=self.cache, logger=self.logger)
        self.disk_guard = DiskGuard(threshold_gb=1.0, logger=self.logger)
        self.view = CamerasView(ctx.view, logger=self.logger)
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.config = load_config(ctx.model.preferences, overrides=None, logger=self.logger)

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

        # Discovery helpers (can be overridden in tests)
        self.discover_picam = discover_picam
        self.discover_usb_devices = discover_usb_devices

        # Controllers
        self.discovery = DiscoveryController(self, logger=self.logger)
        self.recording = RecordingController(self, logger=self.logger)

        self._telemetry_task: Optional[asyncio.Task] = None

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
            refresh=lambda: asyncio.create_task(self.discovery.refresh()),
            apply_config=self._handle_apply_config,
            activate_camera=self._handle_active_camera_changed,
        )

        self.logger.debug("[STARTUP] Attaching view...")
        self.view.attach()
        self.view.set_status("Scanning for cameras...")

        self.logger.info("[STARTUP] Starting discovery controller - will spawn workers...")
        await self.discovery.start()
        self.logger.info("[STARTUP] Discovery complete, workers spawned")

        self._telemetry_task = asyncio.create_task(self._telemetry_loop(), name="cameras_telemetry")
        self.logger.info("[STARTUP] Telemetry loop started")
        self.logger.info("=" * 60)
        self.logger.info("CAMERAS RUNTIME STARTED - %d workers active", len(self.worker_manager.workers))
        self.logger.info("=" * 60)

    async def shutdown(self) -> None:
        self.logger.info("Shutting down Cameras runtime")

        if self._telemetry_task:
            self._telemetry_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._telemetry_task
            self._telemetry_task = None

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

    async def refresh_cameras(self) -> None:
        await self.discovery.refresh()

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

        # Start preview automatically
        self.logger.info("[WORKER READY] Starting preview for %s...", key)
        asyncio.create_task(self._start_preview(key))

    def _on_preview_frame(self, key: str, msg: RespPreviewFrame) -> None:
        # Log every 30th frame to avoid spam
        if not hasattr(self, '_preview_frame_counts'):
            self._preview_frame_counts: Dict[str, int] = {}
        self._preview_frame_counts[key] = self._preview_frame_counts.get(key, 0) + 1
        count = self._preview_frame_counts[key]
        if count == 1 or count % 30 == 0:
            self.logger.debug("[PREVIEW] %s: frame #%d, %dx%d, %d bytes",
                            key, count, msg.width, msg.height, len(msg.frame_data))
        self._preview_receiver.on_preview_frame(key, msg)

    def _on_state_update(self, key: str, msg: RespStateUpdate) -> None:
        self.logger.debug("[STATE] %s: state=%s recording=%s preview=%s fps_cap=%.1f fps_enc=%.1f frames=%d/%d",
                         key, msg.state.name, msg.is_recording, msg.is_previewing,
                         msg.fps_capture, msg.fps_encode, msg.frames_captured, msg.frames_recorded)
        metrics = {
            # Raw worker metrics
            "fps_capture": msg.fps_capture,
            "fps_encode": msg.fps_encode,
            "frames_captured": msg.frames_captured,
            "frames_recorded": msg.frames_recorded,
            "is_recording": msg.is_recording,
            "state": msg.state.name,
            # UI-expected field names
            "ingress_fps_avg": msg.fps_capture,
            "record_fps_avg": msg.fps_encode,
            "target_record_fps": msg.target_record_fps,
            "preview_fps_avg": msg.fps_preview,
            "preview_queue": 0,  # Not tracked yet
            "record_queue": 0,  # Not tracked yet
            "ingress_wait_ms": msg.capture_wait_ms,
        }
        with contextlib.suppress(Exception):
            self.view.update_metrics(key, metrics)

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

        preview_cfg = self.config.preview if hasattr(self.config, 'preview') else None
        target_fps = getattr(preview_cfg, 'fps_cap', 10.0) if preview_cfg else 10.0

        self.logger.info("[PREVIEW START] Sending start_preview command to worker %s (size=320x180, fps=%.1f)",
                        key, target_fps)
        await self.worker_manager.start_preview(
            key,
            preview_size=(320, 180),
            target_fps=target_fps,
            jpeg_quality=80,
        )
        self.logger.info("[PREVIEW START] Preview started for %s", key)

    def _handle_active_camera_changed(self, camera_id: Optional[str]) -> None:
        """Handle UI tab switch - all workers preview simultaneously."""
        self.logger.debug("Active camera: %s", camera_id)

    def _handle_apply_config(self, camera_id: str, settings: Dict[str, Any]) -> None:
        """Handle configuration changes from UI."""
        self.logger.debug("Config change for %s: %s", camera_id, settings)
        # Workers manage their own config internally
        # Future: send CmdReconfigure to worker

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
