"""Bridge controllers that keep the Cameras runtime organized."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Iterable, Optional

from rpi_logger.modules.Cameras.runtime import CameraDescriptor, CameraId, ModeRequest, merge_capabilities, parse_preview_fps, select_modes
from rpi_logger.modules.Cameras.runtime.backends import open_picam_device, open_usb_device, probe_picam, probe_usb, supports_shared_streams
from rpi_logger.modules.Cameras.storage import ensure_dirs, resolve_session_paths

if TYPE_CHECKING:  # pragma: no cover - type checking only
    from rpi_logger.modules.Cameras.bridge import CamerasRuntime


@dataclass(slots=True)
class CameraRuntime:
    descriptor: CameraDescriptor
    capabilities: Any
    selected: Any
    preview_queue: asyncio.Queue
    record_queue: asyncio.Queue
    backend_handle: Any = None


class PreviewController:
    """Owns preview activation/metrics and per-camera monitors."""

    def __init__(self, runtime: "CamerasRuntime") -> None:
        self.rt = runtime
        self.logger = runtime.logger
        self._active_preview: Optional[str] = None
        self._monitor_tasks: Dict[str, asyncio.Task] = {}
        self._frame_counts: Dict[str, int] = {}
        self._fps_window: Dict[str, tuple[int, float]] = {}
        self._first_frame_events: Dict[str, asyncio.Event] = {}
        self._first_frame_watch: Dict[str, asyncio.Task] = {}
        self._preview_logged: set[str] = set()

    # ------------------------------------------------------------------ UI hooks

    def handle_active_camera_changed(self, camera_id: Optional[str]) -> None:
        loop = self.rt.loop
        if not loop or loop.is_closed():
            return
        self.logger.info("Activating preview for %s", camera_id or "none")
        try:
            asyncio.run_coroutine_threadsafe(self.activate_preview(camera_id), loop)
        except Exception:
            self.logger.debug("Failed to schedule preview activation", exc_info=True)

    async def activate_preview(self, camera_key: Optional[str]) -> None:
        if camera_key == self._active_preview:
            return
        if self._active_preview and self._active_preview != camera_key:
            await self.pause_preview(self._active_preview)
        if not camera_key:
            self._active_preview = None
            return
        runtime = self.rt._camera_runtime.get(camera_key)
        if not runtime:
            self._active_preview = None
            self.logger.debug("Requested preview for %s but runtime is missing", camera_key)
            return
        self.rt.router.set_preview_enabled(runtime.descriptor.camera_id, True)
        monitor = self._monitor_tasks.pop(camera_key, None)
        if monitor:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
        self.rt.preview_pipeline.start(
            runtime.descriptor.camera_id,
            runtime.preview_queue,
            lambda frame, cam=runtime.descriptor.camera_id: self.handle_preview_frame(cam, frame),
            runtime.selected.preview,
        )
        self.start_first_frame_watch(camera_key)
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
        self.rt.view.set_status(f"Previewing {camera_key}")

    async def pause_preview(self, camera_key: str) -> None:
        runtime = self.rt._camera_runtime.get(camera_key)
        if runtime:
            self.rt.router.set_preview_enabled(runtime.descriptor.camera_id, False)
            await self.rt.preview_pipeline.stop(runtime.descriptor.camera_id)
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
        watch = self._first_frame_watch.pop(camera_key, None)
        if watch:
            watch.cancel()
            await asyncio.gather(watch, return_exceptions=True)
        self._first_frame_events.pop(camera_key, None)
        if self._active_preview == camera_key:
            self._active_preview = None

    # ------------------------------------------------------------------ Frame handling

    async def _monitor_preview_queue(self, queue: asyncio.Queue, camera_id: CameraId) -> None:
        while True:
            await asyncio.sleep(1)
            key = camera_id.key
            metrics = self.rt.collect_metrics(key)
            if not metrics:
                continue
            self.logger.debug("Metrics for %s: %s", key, metrics)
            try:
                self.rt.view.update_metrics(key, metrics)
            except Exception:
                self.logger.debug("Metrics update failed for %s", key, exc_info=True)

    def handle_preview_frame(self, camera_id: CameraId, frame: Any) -> None:
        key = camera_id.key
        self._frame_counts[key] = self._frame_counts.get(key, 0) + 1
        event = self._first_frame_events.get(key)
        if event and not event.is_set():
            event.set()
        now = asyncio.get_running_loop().time()
        count, start = self._fps_window.get(key, (0, now))
        count += 1
        if (now - start) >= 1.0:
            fps = count / max(now - start, 1e-6)
            try:
                runtime = self.rt._camera_runtime.get(key)
                preview_q_size = runtime.preview_queue.qsize() if runtime else 0
                self.rt.view.update_metrics(
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
            self.rt.view.push_frame(key, frame)
        except Exception:
            self.logger.debug("Preview dispatch failed for %s", key, exc_info=True)
        if self._frame_counts[key] % 10 == 0:
            metrics = self.rt.collect_metrics(key)
            if metrics:
                try:
                    self.rt.view.update_metrics(key, metrics)
                except Exception:
                    self.logger.debug("Metrics update failed for %s", key, exc_info=True)

    # ------------------------------------------------------------------ First-frame watchdogs

    def start_first_frame_watch(self, camera_key: str, *, timeout: float = 5.0) -> None:
        event = self._first_frame_events.get(camera_key) or asyncio.Event()
        event.clear()
        self._first_frame_events[camera_key] = event
        existing = self._first_frame_watch.get(camera_key)
        if existing and not existing.done():
            return
        try:
            task = asyncio.create_task(self._wait_for_first_frame(camera_key, timeout), name=f"first_frame:{camera_key}")
            self._first_frame_watch[camera_key] = task
        except Exception:
            self.logger.debug("Failed to schedule first-frame watch for %s", camera_key, exc_info=True)

    async def _wait_for_first_frame(self, camera_key: str, timeout: float) -> None:
        event = self._first_frame_events.get(camera_key)
        if not event:
            return
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            runtime = self.rt._camera_runtime.get(camera_key)
            if not runtime:
                return
            self.logger.warning("No preview frames from %s after %.1fs; restarting camera", camera_key, timeout)
            asyncio.create_task(
                self.rt.lifecycle.restart_camera(runtime.descriptor, runtime.capabilities, runtime.selected),
                name=f"restart_camera:{camera_key}",
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            self.logger.debug("First-frame watch failed for %s", camera_key, exc_info=True)

    # ------------------------------------------------------------------

    async def cleanup_camera(self, camera_key: str) -> None:
        self._frame_counts.pop(camera_key, None)
        self._fps_window.pop(camera_key, None)
        watch = self._first_frame_watch.pop(camera_key, None)
        if watch:
            if watch is asyncio.current_task():
                self.logger.debug("Skipping self-cancel for first-frame watch %s", camera_key)
            else:
                watch.cancel()
                await asyncio.gather(watch, return_exceptions=True)
        self._first_frame_events.pop(camera_key, None)
        self._preview_logged.discard(camera_key)
        monitor = self._monitor_tasks.pop(camera_key, None)
        if monitor:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
        if self._active_preview == camera_key:
            self._active_preview = None

    async def shutdown(self) -> None:
        for task in list(self._monitor_tasks.values()):
            task.cancel()
        await asyncio.gather(*self._monitor_tasks.values(), return_exceptions=True)
        self._monitor_tasks.clear()
        for task in list(self._first_frame_watch.values()):
            task.cancel()
        await asyncio.gather(*self._first_frame_watch.values(), return_exceptions=True)
        self._first_frame_watch.clear()
        self._first_frame_events.clear()
        self._active_preview = None


class RecordingController:
    """Recording lifecycle handling for the runtime."""

    def __init__(self, runtime: "CamerasRuntime") -> None:
        self.rt = runtime
        self.logger = runtime.logger
        self._recording_cameras: set[str] = set()
        self._session_dir: Optional[Path] = getattr(runtime.ctx.model, "session_dir", None)
        self._trial_number: Optional[int] = getattr(runtime.ctx.model, "trial_number", None)
        self._trial_label: str = getattr(runtime.ctx.model, "trial_label", "")

    async def start_recording(
        self,
        *,
        session_root: Path | None = None,
        trial_number: int | None = None,
        trial_label: str | None = None,
    ) -> None:
        if not self.rt._camera_runtime:
            return
        if self._recording_cameras:
            self.logger.info("Recording already active; ignoring start request")
            return

        session_root = session_root or self._session_dir or getattr(self.rt.ctx.model, "session_dir", None)
        if session_root is not None:
            session_root = Path(session_root)
            self._session_dir = session_root
            self.logger.info("Recording session root set to %s", session_root)
        else:
            self.logger.warning("Recording without a session_dir; falling back to storage base path")
        session_name = self.rt.ctx.model.session_name or "session"
        trial_value = trial_number
        if trial_value is None:
            trial_value = self._trial_number if self._trial_number is not None else getattr(self.rt.ctx.model, "trial_number", None)
        if trial_value is not None:
            self._trial_number = trial_value
        label_value = (trial_label or self._trial_label or getattr(self.rt.ctx.model, "trial_label", "")) or ""
        self._trial_label = label_value
        base_path = Path(self.rt.config.storage.base_path)

        for runtime in self.rt._camera_runtime.values():
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

            self.rt.router.set_record_enabled(cam, True)
            self._recording_cameras.add(cam.key)
            self.rt.record_pipeline.start(
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

    async def stop_recording(self) -> None:
        if not self.rt._camera_runtime:
            return
        for runtime in self.rt._camera_runtime.values():
            await self.rt.record_pipeline.stop(runtime.descriptor.camera_id)
            self.rt.router.set_record_enabled(runtime.descriptor.camera_id, False)
            self._recording_cameras.discard(runtime.descriptor.camera_id.key)
            self.logger.info("Recording stopped for %s", runtime.descriptor.camera_id.key)
        self._recording_cameras.clear()
        self._trial_label = ""

    async def handle_stop_session_command(self) -> None:
        await self.stop_recording()
        self._session_dir = None
        self._trial_number = None
        self.logger.info("Session cleared on stop_session command")

    def on_camera_stopped(self, camera_key: str) -> None:
        self._recording_cameras.discard(camera_key)

    def update_session_dir(self, path: Path) -> None:
        try:
            self._session_dir = Path(path)
            self.logger.info("Session directory provided -> %s", self._session_dir)
        except Exception:
            self.logger.warning("Invalid session directory received: %s", path)

    def update_trial_info(self, *, trial_number: int | None = None, trial_label: str | None = None) -> None:
        if trial_number is not None:
            try:
                self._trial_number = int(trial_number)
            except Exception:
                self.logger.debug("Unable to parse trial number from %s", trial_number)
        if trial_label is not None:
            self._trial_label = trial_label


class LifecycleController:
    """Per-camera lifecycle helpers (setup, restart, teardown, config)."""

    def __init__(self, runtime: "CamerasRuntime", *, preview: Optional[PreviewController] = None) -> None:
        self.rt = runtime
        self.logger = runtime.logger
        self.preview = preview

    def set_preview(self, preview: PreviewController) -> None:
        self.preview = preview

    # ------------------------------------------------------------------ Camera setup/teardown

    async def setup_camera(self, descriptor: CameraDescriptor) -> None:
        cached_state = self.rt.registry.get_state(descriptor.camera_id)
        cached_caps = getattr(cached_state, "capabilities", None) if cached_state else None
        caps = cached_caps if self._capabilities_fresh(cached_caps) else None

        probed_caps = await self.rt._probe_capabilities(descriptor) if caps is None else None
        if probed_caps and caps:
            caps = merge_capabilities(probed_caps, caps)
        elif probed_caps:
            caps = probed_caps
        elif caps is None:
            self.logger.warning("Capability probe returned no modes for %s", descriptor.camera_id.key)
            return
        if not getattr(caps, "modes", None):
            self.logger.warning("Capability probe returned no modes for %s", descriptor.camera_id.key)
            return

        cached_selected = getattr(cached_state, "selected_configs", None) if cached_state else None
        preview_req, record_req = self._build_mode_requests(cached_selected)
        try:
            selected, warnings = select_modes(caps, preview_req, record_req)
        except ValueError as exc:
            self.logger.warning("Capability selection failed for %s: %s", descriptor.camera_id.key, exc)
            return

        for warning in warnings:
            self.logger.warning("%s: %s", descriptor.camera_id.key, warning)

        handle = await self.rt._open_backend(descriptor, selected.preview.mode)
        if handle is None:
            self.logger.warning("Unable to open backend for %s", descriptor.camera_id.key)
            return
        await self.rt.registry.attach_backend(descriptor.camera_id, handle, caps, selected_configs=selected)

        shared = False
        if descriptor.camera_id.backend == "picam":
            try:
                shared = supports_shared_streams(caps, selected.preview.mode, selected.record.mode)
            except Exception:
                shared = False
        self.rt.router.attach(
            descriptor.camera_id,
            handle,
            selected,
            shared=shared,
            preview_enabled=False,
            record_enabled=False,
        )
        preview_q = self.rt.router.get_preview_queue(descriptor.camera_id)
        record_q = self.rt.router.get_record_queue(descriptor.camera_id)
        if preview_q is None or record_q is None:
            self.logger.error("Router queues missing for %s", descriptor.camera_id.key)
            return

        self.rt._camera_runtime[descriptor.camera_id.key] = CameraRuntime(
            descriptor=descriptor,
            capabilities=caps,
            selected=selected,
            preview_queue=preview_q,
            record_queue=record_q,
            backend_handle=handle,
        )
        self._publish_selected_settings(descriptor.camera_id.key, selected)
        try:
            self.rt.view.add_camera(
                descriptor.camera_id.key,
                title=descriptor.camera_id.friendly_name or descriptor.hw_model or descriptor.camera_id.key,
            )
            self.rt.view.update_camera_capabilities(descriptor.camera_id.key, caps)
        except Exception:
            self.logger.debug("View unavailable for %s", descriptor.camera_id.key, exc_info=True)
        active_id = self.rt.view.get_active_camera_id()
        if descriptor.camera_id.backend == "picam" and (not active_id or active_id.startswith("usb:")):
            active_id = descriptor.camera_id.key
        if active_id and self.preview:
            self.preview.handle_active_camera_changed(active_id)
        self.rt.view.set_status(f"{descriptor.camera_id.key} ready; select the tab to start preview")

    async def stop_camera(self, camera_key: str, *, notify_registry: bool = True, remove_from_view: bool = True) -> None:
        runtime = self.rt._camera_runtime.get(camera_key)
        if not runtime:
            return
        if self.preview:
            await self.preview.pause_preview(camera_key)
            await self.preview.cleanup_camera(camera_key)
        self.rt.recording.on_camera_stopped(camera_key)
        await self.rt.record_pipeline.stop(runtime.descriptor.camera_id)
        self.rt.router.set_record_enabled(runtime.descriptor.camera_id, False)
        await self.rt.router.stop(runtime.descriptor.camera_id)
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
                self.rt.view.remove_camera(camera_key)
            except Exception:
                self.logger.debug("View removal failed for %s", camera_key, exc_info=True)
        if notify_registry:
            await self.rt.registry.handle_unplug(runtime.descriptor.camera_id)
        self.rt._camera_runtime.pop(camera_key, None)

    async def teardown_all_cameras(self) -> None:
        for key in list(self.rt._camera_runtime.keys()):
            await self.stop_camera(key)
        await self.rt.registry.apply_discovery([])
        if self.preview:
            self.preview._active_preview = None
        self.rt.recording._recording_cameras.clear()

    async def restart_camera(self, descriptor: CameraDescriptor, capabilities: Any, selected) -> None:
        was_active = self.preview and self.preview._active_preview == descriptor.camera_id.key
        await self.stop_camera(descriptor.camera_id.key, notify_registry=False, remove_from_view=False)
        handle = await self.rt._open_backend(descriptor, selected.preview.mode)
        if handle is None:
            self.rt.view.set_status(f"Failed to reopen {descriptor.camera_id.key}")
            return
        await self.rt.registry.attach_backend(descriptor.camera_id, handle, capabilities, selected_configs=selected)
        shared = False
        if descriptor.camera_id.backend == "picam":
            try:
                shared = supports_shared_streams(capabilities, selected.preview.mode, selected.record.mode)
            except Exception:
                shared = False
        self.rt.router.attach(
            descriptor.camera_id,
            handle,
            selected,
            shared=shared,
            preview_enabled=False,
            record_enabled=False,
        )
        preview_q = self.rt.router.get_preview_queue(descriptor.camera_id)
        record_q = self.rt.router.get_record_queue(descriptor.camera_id)
        if not preview_q or not record_q:
            self.rt.view.set_status(f"Router queues unavailable for {descriptor.camera_id.key}")
            return
        self.rt._camera_runtime[descriptor.camera_id.key] = CameraRuntime(
            descriptor=descriptor,
            capabilities=capabilities,
            selected=selected,
            preview_queue=preview_q,
            record_queue=record_q,
            backend_handle=handle,
        )
        self._publish_selected_settings(descriptor.camera_id.key, selected)
        try:
            self.rt.view.add_camera(descriptor.camera_id.key, title=descriptor.camera_id.friendly_name or descriptor.hw_model or descriptor.camera_id.key)
            self.rt.view.update_camera_capabilities(descriptor.camera_id.key, capabilities)
        except Exception:
            self.logger.debug("View add failed during restart for %s", descriptor.camera_id.key, exc_info=True)
        target = self.rt.view.get_active_camera_id() or (descriptor.camera_id.key if was_active else None)
        if target and self.preview:
            self.preview.handle_active_camera_changed(target)
        self.rt.view.set_status(f"{descriptor.camera_id.key} updated; select the tab to resume preview")
        if self.preview:
            self.preview.start_first_frame_watch(descriptor.camera_id.key)

    # ------------------------------------------------------------------ Config application helpers

    async def apply_camera_config(self, camera_id: str | None, settings: Dict[str, Any]) -> None:
        if not camera_id:
            self.rt.view.set_status("Select a camera before applying settings")
            return
        runtime = self.rt._camera_runtime.get(camera_id)
        if not runtime:
            self.rt.view.set_status(f"{camera_id} is not active")
            return

        preview_req = self._settings_to_mode_request(settings, runtime.selected.preview.mode, prefix="preview")
        record_req = self._settings_to_mode_request(settings, runtime.selected.record.mode, prefix="record")
        selected, warnings = select_modes(runtime.capabilities, preview_req, record_req)
        for warning in warnings:
            self.logger.warning("%s: %s", camera_id, warning)
            self.rt.view.set_status(f"{camera_id}: {warning}")

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
        await self.restart_camera(runtime.descriptor, runtime.capabilities, selected)

    async def _apply_preview_fps_only(self, runtime: CameraRuntime, selected) -> None:
        key = runtime.descriptor.camera_id.key
        self.logger.info(
            "Applying preview FPS clamp for %s (target_fps=%s keep_every=%s)",
            key,
            selected.preview.target_fps,
            selected.preview.keep_every,
        )
        runtime.selected = selected
        self.rt.preview_pipeline.set_target_fps(runtime.descriptor.camera_id, selected.preview.target_fps)
        self.rt.preview_pipeline.set_keep_every(runtime.descriptor.camera_id, selected.preview.keep_every)
        await self.rt.registry.update_selected_configs(runtime.descriptor.camera_id, selected)
        self._publish_selected_settings(key, selected)
        self.rt.view.set_status(f"{key}: preview FPS updated")

    # ------------------------------------------------------------------ Internal helpers

    def _capabilities_fresh(self, capabilities: Any) -> bool:
        if capabilities is None:
            return False
        ttl_ms = max(0, self.rt.config.discovery.cache_ttl_ms)
        if ttl_ms <= 0:
            return False
        timestamp = float(getattr(capabilities, "timestamp_ms", 0.0) or 0.0)
        if not timestamp:
            return False
        age_ms = (time.time() * 1000) - timestamp
        return age_ms <= ttl_ms

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
                size=self.rt.config.preview.resolution,
                fps=self.rt.config.preview.fps_cap,
                pixel_format=self.rt.config.preview.pixel_format,
                overlay=self.rt.config.preview.overlay,
            )
        if record_req is None:
            record_req = ModeRequest(
                size=self.rt.config.record.resolution,
                fps=self.rt.config.record.fps_cap,
                pixel_format=self.rt.config.record.pixel_format,
                overlay=self.rt.config.record.overlay,
            )
        return preview_req, record_req

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

    def _publish_selected_settings(self, camera_key: str, selected) -> None:
        try:
            settings = self._selected_to_settings(selected)
        except Exception:
            self.logger.debug("Failed to convert selected settings for %s", camera_key, exc_info=True)
            return
        try:
            self.rt.view.update_camera_settings(camera_key, settings)
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


class DiscoveryController:
    """Discovery loop and hotplug handling."""

    def __init__(self, runtime: "CamerasRuntime") -> None:
        self.rt = runtime
        self.logger = runtime.logger
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._discovery_failures = 0
        self._reported_empty = False

    # ------------------------------------------------------------------ Lifecycle

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        try:
            await self._discover_and_attach()
        except Exception:
            self.logger.warning("Initial camera discovery failed", exc_info=True)
        self._task = asyncio.create_task(self._discovery_loop(), name="cameras_discovery")

    async def shutdown(self) -> None:
        task = self._task
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._task = None

    async def refresh(self) -> None:
        self.logger.info("Refresh requested from UI")
        await self.shutdown()
        await self.rt.lifecycle.teardown_all_cameras()
        self._reported_empty = False
        await self.start()

    # ------------------------------------------------------------------ Discovery loop

    async def _discovery_loop(self) -> None:
        idle_delay = max(0.5, self.rt.config.discovery.interval_ms / 1000.0)
        backoff = max(idle_delay, self.rt.config.discovery.reprobe_backoff_ms / 1000.0)
        try:
            while True:
                delay = idle_delay
                try:
                    await self._discover_and_attach()
                    self._reported_empty = False
                    self._discovery_failures = 0
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self._discovery_failures += 1
                    delay = min(backoff, idle_delay * (self._discovery_failures + 1))
                    self.logger.warning("Camera discovery iteration failed (streak=%s)", self._discovery_failures, exc_info=True)
                await asyncio.sleep(delay)
        finally:
            self._task = None

    async def _discover_and_attach(self) -> None:
        async with self._lock:
            descriptors: list[CameraDescriptor] = []
            discovery_tasks = {
                "picam": asyncio.to_thread(self.rt.discover_picam, logger=self.logger),
                "usb": asyncio.to_thread(self.rt.discover_usb_devices, logger=self.logger),
            }
            results = await asyncio.gather(*discovery_tasks.values(), return_exceptions=True)
            for name, result in zip(discovery_tasks.keys(), results):
                if isinstance(result, Exception):
                    self.logger.debug("%s discovery failed", name.upper(), exc_info=True)
                    continue
                for desc in result or []:
                    desc.seen_at = time.monotonic() * 1000
                    descriptors.append(desc)

            existing_keys = set(self.rt._camera_runtime.keys())
            discovered_keys = {d.camera_id.key for d in descriptors}
            removed_keys = existing_keys - discovered_keys
            for key in removed_keys:
                await self.rt.lifecycle.stop_camera(key, notify_registry=False)

            await self.rt.registry.apply_discovery(descriptors)
            if descriptors:
                new_descriptors = [d for d in descriptors if d.camera_id.key not in existing_keys]
                if new_descriptors:
                    await self._setup_cameras_concurrently(new_descriptors)
                return

            if not self._reported_empty:
                message = "No cameras detected; connect a device to start preview"
                self.logger.warning(message)
                self.rt.view.set_status(message)
                self._reported_empty = True

    async def _setup_cameras_concurrently(self, descriptors: list[CameraDescriptor]) -> None:
        if not descriptors:
            return
        semaphore = asyncio.Semaphore(3)
        tasks = [
            asyncio.create_task(self._setup_camera_guarded(desc, semaphore), name=f"setup:{desc.camera_id.key}")
            for desc in descriptors
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _setup_camera_guarded(self, descriptor: CameraDescriptor, semaphore: asyncio.Semaphore) -> None:
        async with semaphore:
            try:
                await self.rt.lifecycle.setup_camera(descriptor)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger.warning("Unhandled error while setting up %s", descriptor.camera_id.key, exc_info=True)
