"""Cameras2 runtime bridge for the stub (codex) supervisor."""

from __future__ import annotations

import asyncio
import contextlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.modules.Cameras2.app.services.telemetry import build_snapshot
from rpi_logger.modules.Cameras2.app.view import Cameras2View
from rpi_logger.modules.Cameras2.runtime import CameraDescriptor, CameraId, ModeRequest, parse_preview_fps, select_modes
from rpi_logger.modules.Cameras2.runtime.backends import open_picam_device, open_usb_device, probe_picam, probe_usb, supports_shared_streams
from rpi_logger.modules.Cameras2.runtime.discovery.picam import discover_picam
from rpi_logger.modules.Cameras2.runtime.discovery.usb import discover_usb_devices
from rpi_logger.modules.Cameras2.runtime.registry import Registry
from rpi_logger.modules.Cameras2.runtime.router import Router
from rpi_logger.modules.Cameras2.runtime.preview.pipeline import PreviewPipeline
from rpi_logger.modules.Cameras2.runtime.preview.worker import PreviewWorker
from rpi_logger.modules.Cameras2.runtime.record.pipeline import RecordPipeline
from rpi_logger.modules.Cameras2.runtime.record.recorder import Recorder
from rpi_logger.modules.Cameras2.storage import DiskGuard, KnownCamerasCache, ensure_dirs, resolve_session_paths
from rpi_logger.modules.Cameras2.config import load_config

# Import ModuleRuntime/RuntimeContext from stub (codex) vmc
try:
    from vmc.runtime import ModuleRuntime, RuntimeContext  # type: ignore
except Exception:  # pragma: no cover - defensive
    ModuleRuntime = object  # type: ignore
    RuntimeContext = Any  # type: ignore


logger = get_module_logger(__name__)


@dataclass(slots=True)
class CameraRuntime:
    descriptor: CameraDescriptor
    capabilities: Any
    selected: Any
    preview_queue: asyncio.Queue
    record_queue: asyncio.Queue
    backend_handle: Any = None


class Cameras2Runtime(ModuleRuntime):
    """ModuleRuntime implementation wiring registry/router/pipelines."""

    def __init__(self, ctx: RuntimeContext, config_path: Optional[Path] = None) -> None:
        self.ctx = ctx
        self.logger = ctx.logger.getChild("Cameras2") if hasattr(ctx, "logger") else logger
        self.module_dir = ctx.module_dir
        self.cache = KnownCamerasCache(self.module_dir / "storage" / "known_cameras.json", logger=self.logger)
        self.registry = Registry(cache=self.cache, logger=self.logger)
        self.router = Router(logger=self.logger)
        self.preview_pipeline = PreviewPipeline(logger=self.logger)
        self.preview_worker = PreviewWorker(logger=self.logger)
        self.recorder = Recorder(logger=self.logger)
        self.disk_guard = DiskGuard(threshold_gb=1.0, logger=self.logger)
        self.record_pipeline = RecordPipeline(self.recorder, self.disk_guard, logger=self.logger)
        self.view = Cameras2View(ctx.view, logger=self.logger)
        self._camera_runtime: Dict[str, CameraRuntime] = {}
        self._tasks: list[asyncio.Task] = []
        self._frame_counts: Dict[str, int] = {}
        self._fps_window: Dict[str, tuple[int, float]] = {}
        self._monitor_tasks: Dict[str, asyncio.Task] = {}
        self._telemetry_task: Optional[asyncio.Task] = None
        self._active_preview: Optional[str] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._recording_cameras: set[str] = set()
        self._session_dir: Optional[Path] = getattr(ctx.model, "session_dir", None)
        self._trial_number: Optional[int] = getattr(ctx.model, "trial_number", None)
        self._trial_label: str = getattr(ctx.model, "trial_label", "")
        self._preview_logged: set[str] = set()
        self.config = load_config(ctx.model.preferences, overrides=None, logger=self.logger)

    async def start(self) -> None:
        self.logger.info("Starting Cameras2 runtime")
        self._loop = asyncio.get_running_loop()
        await self.cache.load()
        if self.ctx.view:
            try:
                self.ctx.view.set_preview_title("Cameras2 Preview")
            except Exception:
                self.logger.debug("Failed to set preview title", exc_info=True)
        self.view.bind_handlers(
            refresh=lambda: asyncio.create_task(self.refresh_cameras()),
            apply_config=lambda camera_id, settings: asyncio.create_task(self.apply_camera_config(camera_id, settings)),
            activate_camera=self._handle_active_camera_changed,
        )
        self.view.attach()
        await self._discover_and_attach()
        self._telemetry_task = asyncio.create_task(self._telemetry_loop(), name="cameras2_telemetry")

    async def shutdown(self) -> None:
        self.logger.info("Shutting down Cameras2 runtime")
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        for key in list(self._camera_runtime.keys()):
            await self._stop_camera(key, notify_registry=False)
        await self.router.stop_all()
        for task in list(self._monitor_tasks.values()):
            task.cancel()
        await asyncio.gather(*self._monitor_tasks.values(), return_exceptions=True)
        self._monitor_tasks.clear()
        self._camera_runtime.clear()
        self._active_preview = None
        if self._telemetry_task:
            self._telemetry_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._telemetry_task
            self._telemetry_task = None

    async def cleanup(self) -> None:
        self.logger.debug("Cameras2 runtime cleanup")

    async def handle_command(self, command: Dict[str, Any]) -> bool:
        action = (command.get("command") or "").lower()
        if action in {"start_recording", "record"}:
            session_dir = command.get("session_dir")
            trial_number = command.get("trial_number")
            trial_label = str(command.get("trial_label") or "").strip()
            if trial_label:
                self._trial_label = trial_label
                setattr(self.ctx.model, "trial_label", trial_label)
            if session_dir:
                try:
                    self._session_dir = Path(session_dir)
                except Exception:
                    self.logger.warning("Invalid session_dir in command: %s", session_dir)
            if trial_number is not None:
                try:
                    self._trial_number = int(trial_number)
                    setattr(self.ctx.model, "trial_number", self._trial_number)
                except Exception:
                    self.logger.warning("Invalid trial_number in command: %s", trial_number)
            await self._start_recording(
                session_root=self._session_dir,
                trial_number=self._trial_number,
                trial_label=self._trial_label,
            )
            return True
        if action in {"stop_recording", "pause", "pause_recording"}:
            await self._stop_recording()
            return True
        if action == "resume_recording":
            await self._start_recording(session_root=self._session_dir)
            return True
        if action == "start_session":
            session_dir = command.get("session_dir")
            if session_dir:
                with contextlib.suppress(Exception):
                    await self.on_session_dir_available(Path(session_dir))
            return True
        if action == "stop_session":
            await self._handle_stop_session_command()
            return True
        return False

    async def handle_user_action(self, action: str, **kwargs: Any) -> bool:
        return await self.handle_command({"command": action})

    async def healthcheck(self) -> Dict[str, Any]:
        snap = self.registry.snapshot()
        return {"cameras": len(snap)}

    async def on_session_dir_available(self, path: Path) -> None:
        """Accept session directory from supervisor/logger."""

        try:
            self._session_dir = Path(path)
            self.logger.info("Session directory provided -> %s", self._session_dir)
        except Exception:
            self.logger.warning("Invalid session directory received: %s", path)

    # ------------------------------------------------------------------
    # Internal helpers

    def _handle_active_camera_changed(self, camera_id: Optional[str]) -> None:
        if not self._loop or self._loop.is_closed():
            return
        self.logger.info("Activating preview for %s", camera_id or "none")
        try:
            asyncio.run_coroutine_threadsafe(self._activate_preview(camera_id), self._loop)
        except Exception:
            self.logger.debug("Failed to schedule preview activation", exc_info=True)

    async def _discover_and_attach(self, *, allow_retry: bool = True) -> None:
        descriptors: list[CameraDescriptor] = []
        try:
            descriptors.extend(discover_picam(logger=self.logger))
        except Exception:
            self.logger.debug("Picam discovery failed", exc_info=True)
        try:
            descriptors.extend(discover_usb_devices(logger=self.logger))
        except Exception:
            self.logger.debug("USB discovery failed", exc_info=True)

        existing_keys = set(self._camera_runtime.keys())
        discovered_keys = {d.camera_id.key for d in descriptors}
        removed_keys = existing_keys - discovered_keys
        for key in removed_keys:
            await self._stop_camera(key, notify_registry=False)

        if descriptors:
            await self.registry.apply_discovery(descriptors)
            for descriptor in descriptors:
                if descriptor.camera_id.key in self._camera_runtime:
                    continue
                await self._setup_camera(descriptor)
            return

        message = "No cameras detected; connect a device and restart"
        self.logger.warning(message)
        self.view.set_status(message)
        if allow_retry:
            try:
                asyncio.create_task(self._retry_discovery(), name="cameras2_retry_discovery")
            except Exception:
                self.logger.debug("Unable to schedule discovery retry", exc_info=True)

    async def _retry_discovery(self) -> None:
        await asyncio.sleep(1.0)
        await self._discover_and_attach(allow_retry=False)

    async def _setup_camera(self, descriptor: CameraDescriptor) -> None:
        try:
            caps = await self._probe_capabilities(descriptor)
            if not caps or not caps.modes:
                self.logger.warning("Capability probe returned no modes for %s", descriptor.camera_id.key)
                return

            cached_state = self.registry.get_state(descriptor.camera_id)
            cached_selected = getattr(cached_state, "selected_configs", None) if cached_state else None
            preview_req, record_req = self._build_mode_requests(cached_selected)
            try:
                selected, warnings = select_modes(caps, preview_req, record_req)
            except ValueError as exc:
                self.logger.warning("Capability selection failed for %s: %s", descriptor.camera_id.key, exc)
                return

            for warning in warnings:
                self.logger.warning("%s: %s", descriptor.camera_id.key, warning)

            handle = await self._open_backend(descriptor, selected.preview.mode)
            if handle is None:
                self.logger.warning("Unable to open backend for %s", descriptor.camera_id.key)
                return
            await self.registry.attach_backend(descriptor.camera_id, handle, caps, selected_configs=selected)
        except Exception:
            self.logger.warning("Unhandled error while setting up %s", descriptor.camera_id.key, exc_info=True)
            return

        shared = False
        if descriptor.camera_id.backend == "picam":
            try:
                shared = supports_shared_streams(caps, selected.preview.mode, selected.record.mode)
            except Exception:
                shared = False
        self.router.attach(
            descriptor.camera_id,
            handle,
            selected,
            shared=shared,
            preview_enabled=False,
            record_enabled=False,
        )
        preview_q = self.router.get_preview_queue(descriptor.camera_id)
        record_q = self.router.get_record_queue(descriptor.camera_id)
        if preview_q is None or record_q is None:
            self.logger.error("Router queues missing for %s", descriptor.camera_id.key)
            return

        self._camera_runtime[descriptor.camera_id.key] = CameraRuntime(
            descriptor=descriptor,
            capabilities=caps,
            selected=selected,
            preview_queue=preview_q,
            record_queue=record_q,
            backend_handle=handle,
        )
        self._publish_selected_settings(descriptor.camera_id.key, selected)
        try:
            self.view.add_camera(
                descriptor.camera_id.key,
                title=descriptor.camera_id.friendly_name or descriptor.hw_model or descriptor.camera_id.key,
            )
            self.view.update_camera_capabilities(descriptor.camera_id.key, caps)
        except Exception:
            self.logger.debug("View unavailable for %s", descriptor.camera_id.key, exc_info=True)
        active_id = self.view.get_active_camera_id()
        if active_id:
            self._handle_active_camera_changed(active_id)
        self.view.set_status(f"{descriptor.camera_id.key} ready; select the tab to start preview")

    async def _probe_capabilities(self, descriptor: CameraDescriptor):
        backend = descriptor.camera_id.backend
        if backend == "usb" and descriptor.camera_id.dev_path:
            return await probe_usb(descriptor.camera_id.dev_path, logger=self.logger)
        if backend == "picam":
            return await probe_picam(descriptor.camera_id.stable_id, logger=self.logger)
        return None

    async def _open_backend(self, descriptor: CameraDescriptor, preview_mode) -> Any:
        backend = descriptor.camera_id.backend
        if backend == "usb" and descriptor.camera_id.dev_path:
            return await open_usb_device(descriptor.camera_id.dev_path, preview_mode, logger=self.logger)
        if backend == "picam":
            return await open_picam_device(descriptor.camera_id.stable_id, preview_mode, logger=self.logger)
        return None

    def _build_mode_requests(self, cached: Any = None) -> tuple[ModeRequest, ModeRequest]:
        preview_req = None
        record_req = None
        if cached:
            preview_sel = getattr(cached, "preview", None)
            record_sel = getattr(cached, "record", None)
            if preview_sel:
                preview_req = self._selection_to_request(preview_sel)
            if record_sel:
                record_req = self._selection_to_request(record_sel)

        if preview_req is None:
            preview_req = ModeRequest(
                size=self.config.preview.resolution,
                fps=self.config.preview.fps_cap,
                pixel_format=self.config.preview.pixel_format,
                overlay=self.config.preview.overlay,
            )
        if record_req is None:
            record_req = ModeRequest(
                size=self.config.record.resolution,
                fps=self.config.record.fps_cap,
                pixel_format=self.config.record.pixel_format,
                overlay=self.config.record.overlay,
            )
        return preview_req, record_req

    async def _monitor_preview_queue(self, queue: asyncio.Queue, camera_id: CameraId) -> None:
        while True:
            await asyncio.sleep(1)
            key = camera_id.key
            metrics = self._collect_metrics(key)
            if not metrics:
                continue
            self.logger.debug("Metrics for %s: %s", key, metrics)
            try:
                self.view.update_metrics(key, metrics)
            except Exception:
                self.logger.debug("Metrics update failed for %s", key, exc_info=True)

    async def _activate_preview(self, camera_key: Optional[str]) -> None:
        if camera_key == self._active_preview:
            return
        if self._active_preview and self._active_preview != camera_key:
            await self._pause_preview(self._active_preview)
        if not camera_key:
            self._active_preview = None
            return
        runtime = self._camera_runtime.get(camera_key)
        if not runtime:
            self._active_preview = None
            self.logger.debug("Requested preview for %s but runtime is missing", camera_key)
            return
        self.router.set_preview_enabled(runtime.descriptor.camera_id, True)
        monitor = self._monitor_tasks.pop(camera_key, None)
        if monitor:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
        self.preview_pipeline.start(
            runtime.descriptor.camera_id,
            runtime.preview_queue,
            lambda frame, cam=runtime.descriptor.camera_id: self._handle_preview_frame(cam, frame),
            runtime.selected.preview,
        )
        self.logger.info(
            "Preview enabled for %s (queue=%d, mode=%sx%s @ %s fps)",
            camera_key,
            runtime.preview_queue.qsize(),
            runtime.selected.preview.mode.width,
            runtime.selected.preview.mode.height,
            runtime.selected.preview.mode.fps,
        )
        monitor_task = asyncio.create_task(
            self._monitor_preview_queue(runtime.preview_queue, runtime.descriptor.camera_id),
            name=f"monitor_preview:{camera_key}",
        )
        self._monitor_tasks[camera_key] = monitor_task
        self._active_preview = camera_key
        self.view.set_status(f"Previewing {camera_key}")

    async def _pause_preview(self, camera_key: str) -> None:
        runtime = self._camera_runtime.get(camera_key)
        if runtime:
            self.router.set_preview_enabled(runtime.descriptor.camera_id, False)
            await self.preview_pipeline.stop(runtime.descriptor.camera_id)
            while not runtime.preview_queue.empty():
                try:
                    runtime.preview_queue.get_nowait()
                    runtime.preview_queue.task_done()
                except Exception:
                    break
        monitor = self._monitor_tasks.pop(camera_key, None)
        if monitor:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
        if self._active_preview == camera_key:
            self._active_preview = None

    async def _start_recording(
        self,
        *,
        session_root: Path | None = None,
        trial_number: int | None = None,
        trial_label: str | None = None,
    ) -> None:
        if not self._camera_runtime:
            return
        if self._recording_cameras:
            self.logger.info("Recording already active; ignoring start request")
            return

        session_root = session_root or self._session_dir or getattr(self.ctx.model, "session_dir", None)
        if session_root is not None:
            session_root = Path(session_root)
            self._session_dir = session_root
            self.logger.info("Recording session root set to %s", session_root)
        else:
            self.logger.warning("Recording without a session_dir; falling back to storage base path")
        session_name = self.ctx.model.session_name or "session"
        trial_value = trial_number if trial_number is not None else getattr(self.ctx.model, "trial_number", None)
        if trial_value is not None:
            self._trial_number = trial_value
        label_value = (trial_label or self._trial_label or getattr(self.ctx.model, "trial_label", "")) or ""
        self._trial_label = label_value
        base_path = Path(self.config.storage.base_path)

        for runtime in self._camera_runtime.values():
            cam = runtime.descriptor.camera_id
            paths = resolve_session_paths(
                base_path,
                session_name,
                cam,
                module_name="Cameras",
                module_code="CAM",
                trial_number=trial_value,
                session_root=session_root,
                per_camera_subdir=True,
                suffix_on_collision=session_root is None,
            )
            await ensure_dirs(paths)

            def build_metadata(
                camera_key=cam.key,
                mode_signature=runtime.selected.record.mode.signature(),
                trial=trial_value,
                label=label_value,
                session=str(session_root or paths.root),
            ):
                return {"camera": camera_key, "mode": mode_signature, "trial_number": trial, "trial_label": label, "session_dir": session}

            self.router.set_record_enabled(cam, True)
            self._recording_cameras.add(cam.key)
            self.record_pipeline.start(
                cam,
                runtime.record_queue,
                runtime.selected.record,
                session_paths=paths,
                metadata_builder=build_metadata,
                csv_logger=None,
                trial_number=trial_value,
            )
            self.logger.info(
                "Recording started for %s -> %s (trial=%s)",
                cam.key,
                paths.camera_dir,
                trial_value,
            )

    async def _stop_recording(self) -> None:
        if not self._camera_runtime:
            return
        for runtime in self._camera_runtime.values():
            await self.record_pipeline.stop(runtime.descriptor.camera_id)
            self.router.set_record_enabled(runtime.descriptor.camera_id, False)
            self._recording_cameras.discard(runtime.descriptor.camera_id.key)
            self.logger.info("Recording stopped for %s", runtime.descriptor.camera_id.key)
        self._recording_cameras.clear()
        self._trial_label = ""

    async def _handle_stop_session_command(self) -> None:
        await self._stop_recording()
        self._session_dir = None
        self._trial_number = None
        self.logger.info("Session cleared on stop_session command")

    def _handle_preview_frame(self, camera_id: CameraId, frame: Any) -> None:
        key = camera_id.key
        self._frame_counts[key] = self._frame_counts.get(key, 0) + 1
        now = asyncio.get_running_loop().time()
        count, start = self._fps_window.get(key, (0, now))
        count += 1
        if (now - start) >= 1.0:
            fps = count / max(now - start, 1e-6)
            try:
                runtime = self._camera_runtime.get(key)
                preview_q_size = runtime.preview_queue.qsize() if runtime else 0
                self.view.update_metrics(
                    key,
                    {
                        "preview_fps": round(fps, 2),
                        "frames": self._frame_counts.get(key, 0),
                        "preview_queue": preview_q_size,
                    },
                )
            except Exception:
                self.logger.debug("Metrics update failed for %s", key, exc_info=True)
            self._fps_window[key] = (0, now)
        else:
            self._fps_window[key] = (count, start)
        if key not in self._preview_logged:
            data = getattr(frame, "data", frame)
            shape = getattr(data, "shape", None)
            dtype = getattr(data, "dtype", None)
            self.logger.info("First preview frame %s shape=%s dtype=%s", key, shape, dtype)
            self._preview_logged.add(key)
        try:
            self.view.push_frame(key, frame)
        except Exception:
            self.logger.debug("Preview dispatch failed for %s", key, exc_info=True)
        if self._frame_counts[key] % 10 == 0:
            metrics = self._collect_metrics(key)
            if metrics:
                try:
                    self.view.update_metrics(key, metrics)
                except Exception:
                    self.logger.debug("Metrics update failed for %s", key, exc_info=True)

    # ------------------------------------------------------------------
    # User-initiated actions

    async def refresh_cameras(self) -> None:
        self.logger.info("Refresh requested from UI")
        await self._teardown_all_cameras()
        await self._discover_and_attach()

    async def apply_camera_config(self, camera_id: str | None, settings: Dict[str, Any]) -> None:
        if not camera_id:
            self.view.set_status("Select a camera before applying settings")
            return
        runtime = self._camera_runtime.get(camera_id)
        if not runtime:
            self.view.set_status(f"{camera_id} is not active")
            return

        preview_req = self._settings_to_mode_request(settings, runtime.selected.preview.mode, prefix="preview")
        record_req = self._settings_to_mode_request(settings, runtime.selected.record.mode, prefix="record")
        selected, warnings = select_modes(runtime.capabilities, preview_req, record_req)
        for warning in warnings:
            self.logger.warning("%s: %s", camera_id, warning)
            self.view.set_status(f"{camera_id}: {warning}")

        # Fast path: only preview FPS changed, keep backend live.
        if (
            runtime.selected.preview.mode.signature() == selected.preview.mode.signature()
            and runtime.selected.record.mode.signature() == selected.record.mode.signature()
            and (
                runtime.selected.preview.target_fps != selected.preview.target_fps
                or runtime.selected.preview.keep_every != selected.preview.keep_every
            )
        ):
            await self._apply_preview_fps_only(runtime, selected)
            return

        self.logger.info("Applying new settings to %s", camera_id)
        await self._restart_camera(runtime.descriptor, runtime.capabilities, selected)

    # ------------------------------------------------------------------
    # Camera lifecycle helpers

    async def _apply_preview_fps_only(self, runtime: CameraRuntime, selected) -> None:
        key = runtime.descriptor.camera_id.key
        self.logger.info(
            "Applying preview FPS clamp for %s (target_fps=%s keep_every=%s)",
            key,
            selected.preview.target_fps,
            selected.preview.keep_every,
        )
        runtime.selected = selected
        self.preview_pipeline.set_target_fps(runtime.descriptor.camera_id, selected.preview.target_fps)
        self.preview_pipeline.set_keep_every(runtime.descriptor.camera_id, selected.preview.keep_every)
        await self.registry.update_selected_configs(runtime.descriptor.camera_id, selected)
        self._publish_selected_settings(key, selected)
        self.view.set_status(f"{key}: preview FPS updated")

    async def _stop_camera(self, camera_key: str, *, notify_registry: bool = True, remove_from_view: bool = True) -> None:
        runtime = self._camera_runtime.get(camera_key)
        if not runtime:
            return
        await self._pause_preview(camera_key)
        self._recording_cameras.discard(camera_key)
        await self.record_pipeline.stop(runtime.descriptor.camera_id)
        self.router.set_record_enabled(runtime.descriptor.camera_id, False)
        await self.router.stop(runtime.descriptor.camera_id)
        monitor = self._monitor_tasks.pop(camera_key, None)
        if monitor:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
        self._frame_counts.pop(camera_key, None)
        self._fps_window.pop(camera_key, None)
        self._camera_runtime.pop(camera_key, None)
        handle = getattr(runtime, "backend_handle", None)
        stop = getattr(handle, "stop", None)
        if callable(stop):
            try:
                result = stop()
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                self.logger.debug("Backend stop failed for %s", camera_key, exc_info=True)
        if remove_from_view:
            try:
                self.view.remove_camera(camera_key)
            except Exception:
                self.logger.debug("View removal failed for %s", camera_key, exc_info=True)
        if notify_registry:
            await self.registry.handle_unplug(runtime.descriptor.camera_id)

    async def _teardown_all_cameras(self) -> None:
        for key in list(self._camera_runtime.keys()):
            await self._stop_camera(key)
        await self.registry.apply_discovery([])
        self._active_preview = None
        self._recording_cameras.clear()

    async def _restart_camera(self, descriptor: CameraDescriptor, capabilities: Any, selected) -> None:
        was_active = self._active_preview == descriptor.camera_id.key
        await self._stop_camera(descriptor.camera_id.key, notify_registry=False, remove_from_view=False)
        handle = await self._open_backend(descriptor, selected.preview.mode)
        if handle is None:
            self.view.set_status(f"Failed to reopen {descriptor.camera_id.key}")
            return
        await self.registry.attach_backend(descriptor.camera_id, handle, capabilities, selected_configs=selected)
        shared = False
        if descriptor.camera_id.backend == "picam":
            try:
                shared = supports_shared_streams(capabilities, selected.preview.mode, selected.record.mode)
            except Exception:
                shared = False
        self.router.attach(
            descriptor.camera_id,
            handle,
            selected,
            shared=shared,
            preview_enabled=False,
            record_enabled=False,
        )
        preview_q = self.router.get_preview_queue(descriptor.camera_id)
        record_q = self.router.get_record_queue(descriptor.camera_id)
        if not preview_q or not record_q:
            self.view.set_status(f"Router queues unavailable for {descriptor.camera_id.key}")
            return
        self._camera_runtime[descriptor.camera_id.key] = CameraRuntime(
            descriptor=descriptor,
            capabilities=capabilities,
            selected=selected,
            preview_queue=preview_q,
            record_queue=record_q,
            backend_handle=handle,
        )
        self._publish_selected_settings(descriptor.camera_id.key, selected)
        try:
            self.view.add_camera(descriptor.camera_id.key, title=descriptor.camera_id.friendly_name or descriptor.hw_model or descriptor.camera_id.key)
            self.view.update_camera_capabilities(descriptor.camera_id.key, capabilities)
        except Exception:
            self.logger.debug("View add failed during restart for %s", descriptor.camera_id.key, exc_info=True)
        target = self.view.get_active_camera_id() or (descriptor.camera_id.key if was_active else None)
        if target:
            self._handle_active_camera_changed(target)
        self.view.set_status(f"{descriptor.camera_id.key} updated; select the tab to resume preview")

    def _settings_to_mode_request(self, settings: Dict[str, Any], fallback_mode, *, prefix: str) -> ModeRequest:
        res_key = f"{prefix}_resolution"
        fps_key = f"{prefix}_fps"

        resolution = settings.get(res_key) or f"{fallback_mode.width}x{fallback_mode.height}"
        fps_value = settings.get(fps_key)
        fps, keep_every = parse_preview_fps(fps_value, fallback_mode.fps if fallback_mode else 0.0)
        pixel_format = getattr(fallback_mode, "pixel_format", None)
        overlay_raw = str(settings.get("overlay", getattr(fallback_mode, "overlay", True))).lower()
        overlay = overlay_raw in {"1", "true", "yes", "on"}
        return ModeRequest(
            size=self._parse_resolution(resolution),
            fps=fps,
            keep_every=keep_every,
            pixel_format=pixel_format,
            overlay=overlay,
        )

    def _selection_to_request(self, selection: Any) -> ModeRequest:
        """Build a ModeRequest from a previously selected mode."""

        if selection is None:
            return ModeRequest()
        mode = getattr(selection, "mode", None)
        size = getattr(mode, "size", None)
        pixel_format = getattr(mode, "pixel_format", None)
        fps = getattr(selection, "target_fps", None)
        keep_every = getattr(selection, "keep_every", None)
        if fps is None and keep_every is None and mode and hasattr(mode, "fps"):
            fps = getattr(mode, "fps", None)
        overlay = getattr(selection, "overlay", True)
        color_convert = getattr(selection, "color_convert", True)
        return ModeRequest(
            size=size,
            fps=fps,
            keep_every=keep_every,
            pixel_format=pixel_format,
            overlay=overlay,
            color_convert=color_convert,
        )

    def _parse_resolution(self, text: str | None):
        if not text:
            return None
        if "x" in text.lower():
            w, h = text.lower().split("x", 1)
            try:
                return (int(w), int(h))
            except Exception:
                return None
        return None

    def _collect_metrics(self, camera_key: str) -> Dict[str, Any]:
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
            "frames": self._frame_counts.get(camera_key, 0),
            "preview_queue": runtime.preview_queue.qsize(),
            "record_queue": runtime.record_queue.qsize(),
            "target_preview_fps": preview_target,
            "target_record_fps": record_target,
        }
        router_metrics = self.router.metrics_for(runtime.descriptor.camera_id)
        if router_metrics:
            metrics.update(
                {
                    "preview_dropped": router_metrics.preview_dropped,
                    "record_backpressure": router_metrics.record_backpressure,
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

    def _publish_selected_settings(self, camera_key: str, selected) -> None:
        try:
            settings = self._selected_to_settings(selected)
        except Exception:
            self.logger.debug("Failed to convert selected settings for %s", camera_key, exc_info=True)
            return
        try:
            self.view.update_camera_settings(camera_key, settings)
        except Exception:
            self.logger.debug("View settings update failed for %s", camera_key, exc_info=True)

    def _selected_to_settings(self, selected) -> Dict[str, str]:
        def _fmt_res(mode) -> str:
            if not mode or not hasattr(mode, "width") or not hasattr(mode, "height"):
                return ""
            return f"{mode.width}x{mode.height}"

        def _fmt_fps(selection) -> str:
            keep_every = getattr(selection, "keep_every", None)
            if keep_every:
                try:
                    pct = max(1, round(100.0 / float(keep_every)))
                    return f"{pct}%"
                except Exception:
                    pass
            fps_val = getattr(selection, "target_fps", None)
            if fps_val is None:
                mode = getattr(selection, "mode", None)
                fps_val = getattr(mode, "fps", None)
            if fps_val is None:
                return ""
            try:
                return str(int(fps_val)) if float(fps_val).is_integer() else str(round(float(fps_val), 2))
            except Exception:
                return str(fps_val)

        overlay = getattr(getattr(selected, "preview", None), "overlay", True) if selected else True
        record_overlay = getattr(getattr(selected, "record", None), "overlay", True) if selected else True

        return {
            "preview_resolution": _fmt_res(getattr(getattr(selected, "preview", None), "mode", None) if selected else None),
            "preview_fps": _fmt_fps(getattr(selected, "preview", None)),
            "record_resolution": _fmt_res(getattr(getattr(selected, "record", None), "mode", None) if selected else None),
            "record_fps": _fmt_fps(getattr(selected, "record", None)),
            "overlay": "true" if overlay or record_overlay else "false",
        }

    async def _telemetry_loop(self) -> None:
        interval = max(0.5, self.config.telemetry.emit_interval_ms / 1000.0)
        try:
            while True:
                await asyncio.sleep(interval)
                if not self.config.telemetry.include_metrics:
                    continue
                snapshot: Dict[str, Any] = {}
                for key in list(self._camera_runtime.keys()):
                    payload = self._collect_metrics(key)
                    if payload:
                        snapshot[key] = payload
                if snapshot:
                    self.logger.debug("Telemetry snapshot: %s", build_snapshot(snapshot))
        except asyncio.CancelledError:
            return


def factory(ctx: RuntimeContext) -> Cameras2Runtime:
    return Cameras2Runtime(ctx)
