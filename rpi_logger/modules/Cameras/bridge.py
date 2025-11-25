"""Cameras runtime bridge for the stub (codex) supervisor."""

from __future__ import annotations

import asyncio
import contextlib
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.modules.Cameras.app.services.telemetry import build_snapshot
from rpi_logger.modules.Cameras.app.view import CamerasView
from rpi_logger.modules.Cameras.bridge_controllers import (
    CameraRuntime,
    DiscoveryController,
    LifecycleController,
    PreviewController,
    RecordingController,
)
from rpi_logger.modules.Cameras.runtime.discovery.picam import discover_picam
from rpi_logger.modules.Cameras.runtime.discovery.usb import discover_usb_devices
from rpi_logger.modules.Cameras.runtime.registry import Registry
from rpi_logger.modules.Cameras.runtime.router import Router
from rpi_logger.modules.Cameras.runtime.preview.pipeline import PreviewPipeline
from rpi_logger.modules.Cameras.runtime.preview.worker import PreviewWorker
from rpi_logger.modules.Cameras.runtime.record.pipeline import RecordPipeline
from rpi_logger.modules.Cameras.runtime.record.recorder import Recorder
from rpi_logger.modules.Cameras.storage import DiskGuard, KnownCamerasCache
from rpi_logger.modules.Cameras.config import load_config

# Import ModuleRuntime/RuntimeContext from stub (codex) vmc
try:
    from vmc.runtime import ModuleRuntime, RuntimeContext  # type: ignore
except Exception:  # pragma: no cover - defensive
    ModuleRuntime = object  # type: ignore
    RuntimeContext = Any  # type: ignore


logger = get_module_logger(__name__)


class CamerasRuntime(ModuleRuntime):
    """ModuleRuntime implementation wiring registry/router/pipelines."""

    def __init__(self, ctx: RuntimeContext, config_path: Optional[Path] = None) -> None:
        self.ctx = ctx
        self.logger = ctx.logger.getChild("Cameras") if hasattr(ctx, "logger") else logger
        self.module_dir = ctx.module_dir
        self.cache = KnownCamerasCache(self.module_dir / "storage" / "known_cameras.json", logger=self.logger)
        self.registry = Registry(cache=self.cache, logger=self.logger)
        self.router = Router(logger=self.logger)
        self.preview_pipeline = PreviewPipeline(logger=self.logger)
        self.preview_worker = PreviewWorker(logger=self.logger)
        self.recorder = Recorder(logger=self.logger)
        self.disk_guard = DiskGuard(threshold_gb=1.0, logger=self.logger)
        self.record_pipeline = RecordPipeline(self.recorder, self.disk_guard, logger=self.logger)
        self.view = CamerasView(ctx.view, logger=self.logger)
        self._camera_runtime: Dict[str, CameraRuntime] = {}
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.config = load_config(ctx.model.preferences, overrides=None, logger=self.logger)
        self._telemetry_task: Optional[asyncio.Task] = None

        # Discovery helpers (kept on runtime for easy overriding in tests)
        self.discover_picam = discover_picam
        self.discover_usb_devices = discover_usb_devices

        # Controllers
        self.recording = RecordingController(self)
        self.preview = PreviewController(self)
        self.lifecycle = LifecycleController(self, preview=self.preview)
        self.discovery = DiscoveryController(self)

    async def start(self) -> None:
        self.logger.info("Starting Cameras runtime")
        self.loop = asyncio.get_running_loop()
        await self.cache.load()
        if self.ctx.view:
            with contextlib.suppress(Exception):
                self.ctx.view.set_preview_title("Cameras Preview")
        self.view.bind_handlers(
            refresh=lambda: asyncio.create_task(self.discovery.refresh()),
            apply_config=lambda camera_id, settings: asyncio.create_task(self.lifecycle.apply_camera_config(camera_id, settings)),
            activate_camera=self.preview.handle_active_camera_changed,
        )
        self.view.attach()
        self.view.set_status("Scanning for cameras...")
        await self.discovery.start()
        self._telemetry_task = asyncio.create_task(self._telemetry_loop(), name="cameras_telemetry")

    async def shutdown(self) -> None:
        self.logger.info("Shutting down Cameras runtime")
        await self.discovery.shutdown()
        await self.lifecycle.teardown_all_cameras()
        await self.router.stop_all()
        await self.preview.shutdown()
        if self._telemetry_task:
            self._telemetry_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._telemetry_task
            self._telemetry_task = None

    async def cleanup(self) -> None:
        self.logger.debug("Cameras runtime cleanup")

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
                    self.logger.warning("Invalid trial_number in command: %s", trial_number)
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
        snap = self.registry.snapshot()
        return {"cameras": len(snap)}

    async def on_session_dir_available(self, path: Path) -> None:
        with contextlib.suppress(Exception):
            self.recording.update_session_dir(path)

    async def refresh_cameras(self) -> None:
        await self.discovery.refresh()

    # ------------------------------------------------------------------
    # Backwards-compatible hooks for tests/monkeypatching

    async def _probe_capabilities(self, descriptor):
        return await self.lifecycle._probe_capabilities(descriptor)

    async def _open_backend(self, descriptor, preview_mode):
        return await self.lifecycle._open_backend(descriptor, preview_mode)

    def _settings_to_mode_request(self, settings: Dict[str, Any], fallback_mode, *, prefix: str):
        return self.lifecycle._settings_to_mode_request(settings, fallback_mode, prefix=prefix)

    def collect_metrics(self, camera_key: str) -> Dict[str, Any]:
        runtime = self._camera_runtime.get(camera_key)
        if not runtime:
            return {}
        preview_sel = getattr(runtime.selected, "preview", None)
        record_sel = getattr(runtime.selected, "record", None)
        preview_target = None
        record_target = None
        if preview_sel:
            preview_target = preview_sel.target_fps if preview_sel.target_fps is not None else getattr(getattr(preview_sel, "mode", None), "fps", None)
        if record_sel:
            record_target = record_sel.target_fps if record_sel.target_fps is not None else getattr(getattr(record_sel, "mode", None), "fps", None)
        metrics: Dict[str, Any] = {
            "preview_queue": runtime.preview_queue.qsize() if runtime.preview_queue else 0,
            "record_queue": runtime.record_queue.qsize() if runtime.record_queue else 0,
            "target_preview_fps": preview_target,
            "target_record_fps": record_target,
        }
        router_metrics = self.router.metrics_for(runtime.descriptor.camera_id)
        if router_metrics:
            metrics.update(
                {
                    "preview_dropped": router_metrics.preview_dropped,
                    "record_backpressure": router_metrics.record_backpressure,
                    "record_dropped": router_metrics.record_dropped,
                    "preview_enqueued": router_metrics.preview_enqueued,
                    "record_enqueued": router_metrics.record_enqueued,
                    "ingress_fps_avg": router_metrics.ingress_fps_avg,
                    "ingress_fps_inst": router_metrics.ingress_fps_inst,
                    "ingress_wait_ms": router_metrics.ingress_wait_ms,
                }
            )
        preview_metrics = self.preview_pipeline.metrics(runtime.descriptor.camera_id)
        if preview_metrics:
            metrics.update(preview_metrics)
        record_metrics = self.record_pipeline.metrics(runtime.descriptor.camera_id)
        if record_metrics:
            metrics.update(record_metrics)
        return metrics

    async def _telemetry_loop(self) -> None:
        interval = max(0.5, self.config.telemetry.emit_interval_ms / 1000.0)
        try:
            while True:
                await asyncio.sleep(interval)
                snapshot: Dict[str, Any] = {}
                for key in list(self._camera_runtime.keys()):
                    payload = self.collect_metrics(key)
                    if payload:
                        snapshot[key] = payload
                        # Always push the latest metrics into the view so the Capture Stats
                        # frame stays current, even when telemetry logging is disabled.
                        if self.view:
                            try:
                                self.view.update_metrics(key, payload)
                            except Exception:
                                self.logger.debug("Failed to update view metrics for %s", key, exc_info=True)
                if snapshot and self.config.telemetry.include_metrics:
                    self.logger.debug("Telemetry snapshot: %s", build_snapshot(snapshot))
        except asyncio.CancelledError:
            return


def factory(ctx: RuntimeContext) -> CamerasRuntime:
    return CamerasRuntime(ctx)
