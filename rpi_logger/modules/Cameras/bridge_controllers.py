"""Controllers that wire discovery, lifecycle, preview, and recording."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.Cameras.runtime import (
    CameraDescriptor,
    CameraId,
    CameraRuntimeState,
    ModeRequest,
    ModeSelection,
    SelectedConfigs,
    select_modes,
    parse_preview_fps,
    CapabilityMode,
)
from rpi_logger.modules.Cameras.runtime.backends import picam_backend, usb_backend
from rpi_logger.modules.Cameras.runtime.router import Router
from rpi_logger.modules.Cameras.runtime.preview.pipeline import PreviewPipeline
from rpi_logger.modules.Cameras.runtime.preview.worker import PreviewWorker
from rpi_logger.modules.Cameras.runtime.record import RecordPipeline
from rpi_logger.modules.Cameras.runtime.record.csv_logger import CSVLogger
from rpi_logger.modules.Cameras.storage import resolve_session_paths
from rpi_logger.modules.Cameras.storage.metadata import build_metadata

DEFAULT_PREVIEW_FPS = 2.0  # Limit preview to 2 FPS by default to reduce load.


@dataclass(slots=True)
class CameraRuntime:
    descriptor: CameraDescriptor
    handle: Any
    selected: SelectedConfigs
    preview_queue: asyncio.Queue
    record_queue: asyncio.Queue
    csv_logger: Optional[CSVLogger] = None
    session_paths: Any = None
    recording_started: bool = False
    tasks: Dict[str, asyncio.Task] = field(default_factory=dict)
    capabilities: Any = None


class DiscoveryController:
    """Performs discovery and hands descriptors to the lifecycle controller."""

    def __init__(self, runtime: "CamerasRuntime", *, logger: LoggerLike = None) -> None:
        self._runtime = runtime
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        await self.refresh()

    async def refresh(self) -> None:
        runtime = self._runtime
        picam_desc = runtime.discover_picam(logger=self._logger)
        usb_desc = runtime.discover_usb_devices(logger=self._logger)
        descriptors = picam_desc + usb_desc
        states = await runtime.registry.apply_discovery(descriptors)
        for desc in descriptors:
            await runtime.lifecycle.ensure_camera(desc)
        # Remove any cameras no longer present
        for key in list(runtime._camera_runtime.keys()):
            if key not in states:
                await runtime.lifecycle.teardown_camera(key)

    async def shutdown(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None


class LifecycleController:
    """Open/close backends, attach router/pipelines, and apply configs."""

    def __init__(
        self,
        runtime: "CamerasRuntime",
        *,
        preview: "PreviewController",
        logger: LoggerLike = None,
    ) -> None:
        self._runtime = runtime
        self._preview = preview
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)

    async def ensure_camera(self, descriptor: CameraDescriptor) -> None:
        key = descriptor.camera_id.key
        if key in self._runtime._camera_runtime:
            return
        caps = await self._probe_capabilities(descriptor)
        if not caps:
            return

        record_defaults = self._runtime.config.record
        record_request = ModeRequest(
            size=record_defaults.resolution,
            fps=record_defaults.fps_cap,
            pixel_format=record_defaults.pixel_format,
            overlay=record_defaults.overlay,
        )

        selected, _ = select_modes(caps, caps.default_preview_mode, record_request)
        if selected.preview.keep_every is None and selected.preview.target_fps is None:
            selected.preview.target_fps = DEFAULT_PREVIEW_FPS
        handle = await self._open_backend(descriptor, selected.record.mode)
        if not handle:
            return
        await self._runtime.registry.attach_backend(
            descriptor.camera_id, handle, caps, selected_configs=selected
        )

        router: Router = self._runtime.router
        router.attach(descriptor.camera_id, handle, selected, preview_queue_size=4, record_queue_size=4)
        preview_q = router.get_preview_queue(descriptor.camera_id)
        record_q = router.get_record_queue(descriptor.camera_id)
        runtime_entry = CameraRuntime(
            descriptor=descriptor,
            handle=handle,
            selected=selected,
            preview_queue=preview_q,
            record_queue=record_q,
            capabilities=caps,
        )
        self._runtime._camera_runtime[key] = runtime_entry
        self._runtime.view.add_camera(key, title=descriptor.camera_id.friendly_name or key)
        self._runtime.view.update_camera_capabilities(key, caps)
        self._preview.start(descriptor.camera_id, selected.preview, preview_q)

    async def _probe_capabilities(self, descriptor: CameraDescriptor):
        backend = descriptor.camera_id.backend
        try:
            if backend == "usb":
                dev_path = descriptor.camera_id.dev_path or descriptor.location_hint
                if not dev_path:
                    self._logger.warning("USB descriptor missing dev_path; skipping probe")
                    return None
                return await usb_backend.probe(dev_path, logger=self._logger)
            if backend == "picam":
                sensor_id = descriptor.camera_id.stable_id
                return await picam_backend.probe(sensor_id, logger=self._logger)
        except Exception:
            self._logger.warning("Capability probe failed for %s", descriptor.camera_id.key, exc_info=True)
        return None

    async def _open_backend(self, descriptor: CameraDescriptor, mode: CapabilityMode):
        backend = descriptor.camera_id.backend
        try:
            if backend == "usb":
                dev_path = descriptor.camera_id.dev_path or descriptor.location_hint
                if not dev_path:
                    self._logger.warning("USB descriptor missing dev_path; cannot open")
                    return None
                return await usb_backend.open_device(dev_path, mode, logger=self._logger)
            if backend == "picam":
                sensor_id = descriptor.camera_id.stable_id
                return await picam_backend.open_device(sensor_id, mode, logger=self._logger)
        except Exception:
            self._logger.warning("Open backend failed for %s", descriptor.camera_id.key, exc_info=True)
        return None

    async def teardown_camera(self, key: str) -> None:
        runtime = self._runtime._camera_runtime.pop(key, None)
        if not runtime:
            return
        try:
            await self._runtime.router.stop(runtime.descriptor.camera_id)
        except Exception:
            pass
        await self._preview.stop(runtime.descriptor.camera_id)
        try:
            stop = getattr(runtime.handle, "stop", None)
            if stop:
                await stop()
        except Exception:
            pass
        self._runtime.view.remove_camera(key)

    async def teardown_all_cameras(self) -> None:
        for key in list(self._runtime._camera_runtime.keys()):
            await self.teardown_camera(key)

    def _settings_to_mode_request(self, settings: Dict[str, str], fallback_mode: CapabilityMode, *, prefix: str) -> ModeRequest:
        """Parse UI settings into a ModeRequest."""

        resolution_raw = settings.get(f"{prefix}_resolution")
        fps_raw = settings.get(f"{prefix}_fps")

        fps_cap, keep_every = parse_preview_fps(fps_raw, fallback_mode.fps)
        width, height = fallback_mode.size
        if resolution_raw:
            try:
                width, height = [int(v) for v in resolution_raw.lower().split("x")]
            except Exception as exc:
                raise ValueError(f"Invalid resolution: {resolution_raw}") from exc

        return ModeRequest(
            size=(width, height),
            fps=fps_cap,
            keep_every=keep_every,
            pixel_format=fallback_mode.pixel_format,
            overlay=True,
            color_convert=True,
        )

    async def apply_camera_config(self, camera_id: str, settings: Dict[str, str]) -> None:
        runtime = self._runtime._camera_runtime.get(camera_id)
        if not runtime:
            return
        current = runtime.selected
        preview_req = self._settings_to_mode_request(settings, current.preview.mode, prefix="preview")
        record_req = self._settings_to_mode_request(settings, current.record.mode, prefix="record")

        def _selection(req: ModeRequest, fallback: CapabilityMode) -> ModeSelection:
            mode = CapabilityMode(
                size=req.size or fallback.size,
                fps=req.fps or fallback.fps,
                pixel_format=req.pixel_format or fallback.pixel_format,
                controls=fallback.controls,
            )
            return ModeSelection(
                mode=mode,
                target_fps=req.fps,
                keep_every=req.keep_every,
                overlay=req.overlay,
                color_convert=req.color_convert,
            )

        runtime.selected = SelectedConfigs(
            preview=_selection(preview_req, current.preview.mode),
            record=_selection(record_req, current.record.mode),
            storage_profile=current.storage_profile,
        )
        new_selected = runtime.selected

        def _mode_signature(sel: ModeSelection):
            mode = sel.mode
            controls_sig = tuple(sorted((mode.controls or {}).items()))
            return (
                mode.size,
                mode.fps,
                mode.pixel_format,
                controls_sig,
            )

        def _preview_mode_changed(old: ModeSelection, new: ModeSelection) -> bool:
            return _mode_signature(old) != _mode_signature(new)

        def _record_selection_changed(old: ModeSelection, new: ModeSelection) -> bool:
            return (
                _mode_signature(old),
                old.target_fps,
                old.keep_every,
                old.overlay,
                old.color_convert,
            ) != (
                _mode_signature(new),
                new.target_fps,
                new.keep_every,
                new.overlay,
                new.color_convert,
            )

        # Apply lightweight updates to the running preview pipeline when only FPS/decimation changes.
        self._runtime.preview_pipeline.set_target_fps(runtime.descriptor.camera_id, new_selected.preview.target_fps)
        self._runtime.preview_pipeline.set_keep_every(runtime.descriptor.camera_id, new_selected.preview.keep_every)

        preview_mode_changed = _preview_mode_changed(current.preview, new_selected.preview)
        record_changed = _record_selection_changed(current.record, new_selected.record)

        if preview_mode_changed or record_changed:
            await self._reconfigure_camera(runtime, new_selected)
        await self._runtime.registry.update_selected_configs(runtime.descriptor.camera_id, new_selected)
        self._runtime.view.update_camera_settings(camera_id, settings)

    async def _reconfigure_camera(self, runtime: CameraRuntime, selected: SelectedConfigs) -> None:
        """Restart backend/router/pipelines to honor new mode selections."""

        camera_id = runtime.descriptor.camera_id
        key = camera_id.key
        was_recording = runtime.recording_started
        if was_recording:
            self._runtime.router.set_record_enabled(camera_id, False)
            await self._runtime.record_pipeline.stop(camera_id)
            runtime.recording_started = False
        await self._preview.stop(camera_id)
        await self._runtime.router.stop(camera_id)
        try:
            stop = getattr(runtime.handle, "stop", None)
            if stop:
                await stop()
        except Exception:
            pass

        handle = await self._open_backend(runtime.descriptor, selected.record.mode)
        if not handle:
            self._logger.warning("Reconfigure failed for %s; camera remains stopped", key)
            return

        runtime.handle = handle
        runtime.selected = selected
        capabilities = runtime.capabilities
        if capabilities is None:
            state = self._runtime.registry.get_state(camera_id)
            capabilities = getattr(state, "capabilities", None)

        await self._runtime.registry.attach_backend(camera_id, handle, capabilities, selected_configs=selected)
        runtime.capabilities = capabilities

        self._runtime.router.attach(camera_id, handle, selected, preview_queue_size=4, record_queue_size=4)
        runtime.preview_queue = self._runtime.router.get_preview_queue(camera_id)
        runtime.record_queue = self._runtime.router.get_record_queue(camera_id)
        self._preview.start(camera_id, selected.preview, runtime.preview_queue)

        if was_recording:
            await self._runtime.recording._start_camera_recording(runtime)


class PreviewController:
    """Connects preview queue to UI consumer."""

    def __init__(
        self,
        runtime: "CamerasRuntime",
        *,
        logger: LoggerLike = None,
    ) -> None:
        self._runtime = runtime
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._pipeline: PreviewPipeline = runtime.preview_pipeline
        self._worker: PreviewWorker = runtime.preview_worker
        self._running: set[str] = set()
        self._active_camera: Optional[str] = None

    def start(self, camera_id: CameraId, selection: ModeSelection, preview_queue: asyncio.Queue) -> None:
        if not preview_queue:
            return

        active = self._runtime.view.get_active_camera_id()
        is_active = active is None or active == camera_id.key
        self._runtime.router.set_preview_enabled(camera_id, is_active)
        if not is_active:
            self._running.discard(camera_id.key)
            return
        if camera_id.key in self._running:
            return

        def consumer(frame: Any):
            self._runtime.view.push_frame(camera_id.key, frame)

        self._pipeline.start(camera_id, preview_queue, consumer, selection)
        self._running.add(camera_id.key)

    async def stop(self, camera_id: CameraId) -> None:
        self._runtime.router.set_preview_enabled(camera_id, False)
        await self._pipeline.stop(camera_id)
        self._running.discard(camera_id.key)

    async def shutdown(self) -> None:
        for key in list(self._runtime._camera_runtime.keys()):
            await self.stop(self._runtime._camera_runtime[key].descriptor.camera_id)

    def handle_active_camera_changed(self, camera_id: Optional[str]) -> None:
        self._active_camera = camera_id
        self._logger.debug("Active camera changed: %s", camera_id)
        loop = self._runtime.loop or asyncio.get_event_loop()
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        coro = self._switch_active_preview(camera_id)
        if running_loop and running_loop is loop:
            loop.create_task(coro)
        else:
            asyncio.run_coroutine_threadsafe(coro, loop)

    async def _switch_active_preview(self, active_camera: Optional[str]) -> None:
        stops = []
        for key, runtime in list(self._runtime._camera_runtime.items()):
            cam_id = runtime.descriptor.camera_id
            if active_camera is None or key != active_camera:
                stops.append(self.stop(cam_id))
        if stops:
            await asyncio.gather(*stops)

        if active_camera:
            runtime = self._runtime._camera_runtime.get(active_camera)
            if runtime:
                cam_id = runtime.descriptor.camera_id
                self._runtime.router.drain_preview_queue(cam_id)
                self._runtime.router.set_preview_enabled(cam_id, True)
                if active_camera not in self._running:
                    self.start(cam_id, runtime.selected.preview, runtime.preview_queue)


class RecordingController:
    """Starts/stops record pipelines across attached cameras."""

    def __init__(self, runtime: "CamerasRuntime", *, logger: LoggerLike = None) -> None:
        self._runtime = runtime
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._session_dir: Path = runtime.ctx.module_dir / "sessions"
        self._trial_number: Optional[int] = None
        self._trial_label: Optional[str] = None

    def update_session_dir(self, path: Path) -> None:
        self._session_dir = Path(path)

    def update_trial_info(self, *, trial_number: Optional[int] = None, trial_label: Optional[str] = None) -> None:
        if trial_number is not None:
            self._trial_number = trial_number
        if trial_label is not None:
            self._trial_label = trial_label

    async def start_recording(self) -> None:
        for runtime in self._runtime._camera_runtime.values():
            await self._start_camera_recording(runtime)

    async def _start_camera_recording(self, runtime: CameraRuntime) -> None:
        if runtime.recording_started:
            return
        if runtime.record_queue is None:
            self._logger.warning("No record queue available for %s; skipping recording", runtime.descriptor.camera_id.key)
            return
        camera_id = runtime.descriptor.camera_id
        session_paths = resolve_session_paths(
            self._session_dir,
            camera_id,
            module_name="Cameras",
            trial_number=self._trial_number or 1,
        )
        runtime.session_paths = session_paths
        guard_status = await self._runtime.disk_guard.ensure_ok(session_paths.camera_dir)
        if not guard_status.ok:
            self._runtime.router.set_record_enabled(camera_id, False)
            return

        csv_logger = CSVLogger(trial_number=self._trial_number, camera_label=camera_id.key, flush_every=16)
        metadata_builder = lambda: build_metadata(
            camera_id,
            selection_preview=runtime.selected.preview,
            selection_record=runtime.selected.record,
            target_fps=runtime.selected.record.target_fps,
            video_path=session_paths.video_path,
            timing_path=session_paths.timing_path,
        )
        try:
            self._runtime.record_pipeline.start(
                camera_id,
                runtime.record_queue,
                runtime.selected.record,
                session_paths=session_paths,
                metadata_builder=metadata_builder,
                csv_logger=csv_logger,
                trial_number=self._trial_number,
            )
        except Exception:
            self._runtime.router.set_record_enabled(camera_id, False)
            await csv_logger.stop()
            raise
        runtime.csv_logger = csv_logger
        runtime.recording_started = True
        self._runtime.router.set_record_enabled(camera_id, True)

    async def stop_recording(self) -> None:
        for runtime in self._runtime._camera_runtime.values():
            self._runtime.router.set_record_enabled(runtime.descriptor.camera_id, False)
        for runtime in self._runtime._camera_runtime.values():
            if runtime.recording_started:
                await self._runtime.record_pipeline.stop(runtime.descriptor.camera_id)
                runtime.recording_started = False

    async def handle_stop_session_command(self) -> None:
        await self.stop_recording()


__all__ = [
    "CameraRuntime",
    "DiscoveryController",
    "LifecycleController",
    "PreviewController",
    "RecordingController",
]
