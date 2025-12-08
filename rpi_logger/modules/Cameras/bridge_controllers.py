"""
Controllers for the worker-based Cameras module.

With the multiprocess architecture, most of the old controller logic
is now handled by the workers themselves. What remains:
- Discovery: finding cameras and spawning workers
- Recording coordination: session paths, trial info
"""
from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from rpi_logger.core.logging_utils import LoggerLike, ensure_structured_logger
from rpi_logger.modules.Cameras.defaults import DEFAULT_CAPTURE_RESOLUTION, DEFAULT_CAPTURE_FPS
from rpi_logger.modules.Cameras.utils import parse_resolution, parse_fps, parse_bool
from rpi_logger.modules.Cameras.runtime import (
    CameraCapabilities,
    CameraDescriptor,
    CameraId,
    CapabilityMode,
    ModeRequest,
    ModeSelection,
    SelectedConfigs,
    select_modes,
    parse_preview_fps,
)
from rpi_logger.modules.Cameras.runtime.backends import picam_backend, usb_backend
from rpi_logger.modules.Cameras.storage import resolve_session_paths

DEFAULT_PREVIEW_FPS = 10.0


@dataclass(slots=True)
class CameraWorkerState:
    """Tracks state of a camera worker from the main process perspective."""
    descriptor: CameraDescriptor
    worker_key: str
    capabilities: Optional[Any] = None
    selected: Optional[SelectedConfigs] = None
    is_recording: bool = False
    video_path: Optional[str] = None
    csv_path: Optional[str] = None


class DiscoveryController:
    """
    Handles worker spawning for cameras.

    Note: Discovery is now handled by the main logger's DeviceSystem.
    This controller only spawns workers when cameras are assigned via the
    assign_device command.
    """

    def __init__(self, runtime: "CamerasRuntime", *, logger: LoggerLike = None) -> None:
        self._runtime = runtime
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)

    async def _spawn_worker_for(self, desc: CameraDescriptor) -> None:
        """Spawn a worker process for a camera."""
        runtime = self._runtime
        key = desc.camera_id.key

        self._logger.info("[SPAWN] Starting worker spawn for %s", key)
        self._logger.debug("[SPAWN] Descriptor: backend=%s stable_id=%s dev_path=%s location=%s",
                          desc.camera_id.backend, desc.camera_id.stable_id,
                          desc.camera_id.dev_path, desc.location_hint)

        try:
            # Probe capabilities first
            self._logger.debug("[SPAWN] Probing capabilities for %s...", key)
            caps = await self._probe_capabilities(desc)
            self._logger.debug("[SPAWN] Capabilities: %s", caps)

            # Determine camera type and ID for the worker
            camera_type = desc.camera_id.backend
            if camera_type == "usb":
                camera_id = desc.camera_id.dev_path or desc.location_hint or "0"
            else:
                camera_id = desc.camera_id.stable_id

            self._logger.info("[SPAWN] Camera type=%s, id=%s", camera_type, camera_id)

            # Get per-camera capture resolution/fps (uses record settings as capture settings)
            resolution, fps = await self._get_capture_settings(key, caps)
            self._logger.info("[SPAWN] Capture config: resolution=%s, fps=%.1f", resolution, fps)

            # Spawn the worker using the stable camera key
            self._logger.info("[SPAWN] Calling worker_manager.spawn_worker()...")
            handle = await runtime.worker_manager.spawn_worker(
                camera_type=camera_type,
                camera_id=camera_id,
                resolution=resolution,
                fps=fps,
                key=key,
            )
            self._logger.info("[SPAWN] Worker process spawned for %s", key)

            # Track state
            runtime.camera_states[key] = CameraWorkerState(
                descriptor=desc,
                worker_key=key,
                capabilities=caps,
            )

            self._logger.info("[SPAWN] Worker spawn complete for %s - waiting for READY signal", key)

        except asyncio.CancelledError:
            raise  # Don't catch cancellation
        except (OSError, ValueError, RuntimeError) as e:
            self._logger.error("[SPAWN] FAILED to spawn worker for %s: %s", key, e)
        except Exception as e:
            self._logger.error("[SPAWN] Unexpected error spawning worker for %s: %s", key, e, exc_info=True)

    async def _probe_capabilities(self, desc: CameraDescriptor) -> Optional[Any]:
        """Probe camera capabilities (non-blocking)."""
        backend = desc.camera_id.backend
        try:
            if backend == "usb":
                dev_path = desc.camera_id.dev_path or desc.location_hint
                if dev_path:
                    return await usb_backend.probe(dev_path, logger=self._logger)
            elif backend == "picam":
                sensor_id = desc.camera_id.stable_id
                return await picam_backend.probe(sensor_id, logger=self._logger)
        except Exception:
            self._logger.debug("Capability probe failed for %s", desc.camera_id.key, exc_info=True)
        return None

    async def _get_capture_settings(
        self, key: str, capabilities: Optional[CameraCapabilities] = None
    ) -> tuple[tuple[int, int], float]:
        """Get capture resolution and fps for a camera from saved settings.

        If capabilities are provided, validates and adjusts resolution to match
        a supported mode.
        """
        saved = await self._runtime.cache.get_settings(key)
        record_cfg = self._runtime.config.record
        default_resolution = record_cfg.resolution or DEFAULT_CAPTURE_RESOLUTION
        default_fps = record_cfg.fps_cap or DEFAULT_CAPTURE_FPS

        resolution = parse_resolution(
            saved.get("record_resolution") if saved else None,
            default_resolution
        )
        fps = parse_fps(
            saved.get("record_fps") if saved else None,
            default_fps
        )

        if capabilities and capabilities.modes:
            resolution, fps = self._validate_against_capabilities(
                resolution, fps, capabilities, key
            )

        return resolution, fps

    def _validate_against_capabilities(
        self,
        resolution: tuple[int, int],
        fps: float,
        capabilities: CameraCapabilities,
        key: str,
    ) -> tuple[tuple[int, int], float]:
        """Validate and adjust resolution/fps against camera capabilities."""
        # Check for exact match first
        for mode in capabilities.modes:
            if mode.size == resolution and mode.fps >= fps:
                return resolution, fps

        # Check if resolution exists at any fps
        matching_res = [m for m in capabilities.modes if m.size == resolution]
        if matching_res:
            # Use best fps available for this resolution
            best = max(matching_res, key=lambda m: m.fps)
            if best.fps < fps:
                self._logger.warning(
                    "[VALIDATE] %s: Requested fps %.1f not available at %s, using %.1f",
                    key, fps, resolution, best.fps
                )
                return resolution, best.fps
            return resolution, fps

        # Resolution not supported - find best alternative
        self._logger.warning(
            "[VALIDATE] %s: Resolution %s not supported by camera", key, resolution
        )

        # Prefer modes with same or higher resolution, then fallback to default record mode
        larger_modes = [
            m for m in capabilities.modes
            if m.width >= resolution[0] and m.height >= resolution[1]
        ]
        if larger_modes:
            # Pick smallest mode that fits the request
            best = min(larger_modes, key=lambda m: (m.width * m.height, -m.fps))
            self._logger.info(
                "[VALIDATE] %s: Using %s @ %.1f fps instead", key, best.size, best.fps
            )
            return best.size, min(fps, best.fps)

        # No larger mode, use default record mode or largest available
        if capabilities.default_record_mode:
            best = capabilities.default_record_mode
        else:
            best = max(capabilities.modes, key=lambda m: (m.width * m.height, m.fps))

        self._logger.info(
            "[VALIDATE] %s: Using fallback %s @ %.1f fps", key, best.size, best.fps
        )
        return best.size, min(fps, best.fps)

    async def shutdown(self) -> None:
        """Shutdown discovery (no background tasks to cancel in this design)."""
        pass


class RecordingController:
    """Coordinates recording across all camera workers."""

    def __init__(self, runtime: "CamerasRuntime", *, logger: LoggerLike = None) -> None:
        self._runtime = runtime
        self._logger = ensure_structured_logger(logger, fallback_name=__name__)
        self._session_dir: Path = runtime.ctx.module_dir / "sessions"
        self._trial_number: Optional[int] = None
        self._trial_label: Optional[str] = None
        self._recording = False

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def session_dir(self) -> Path:
        return self._session_dir

    @property
    def trial_number(self) -> Optional[int]:
        return self._trial_number

    def update_session_dir(self, path: Path) -> None:
        self._session_dir = Path(path)

    def update_trial_info(self, *, trial_number: Optional[int] = None, trial_label: Optional[str] = None) -> None:
        if trial_number is not None:
            self._trial_number = trial_number
        if trial_label is not None:
            self._trial_label = trial_label

    async def start_recording(self) -> None:
        """Start recording on all camera workers."""
        if self._recording:
            self._logger.debug("Already recording")
            return

        if not self._session_dir.exists():
            self._session_dir.mkdir(parents=True, exist_ok=True)

        self._recording = True
        record_cfg = self._runtime.config.record

        for key, state in self._runtime.camera_states.items():
            try:
                await self._start_camera_recording(key, state)
            except asyncio.CancelledError:
                raise
            except (OSError, ValueError, RuntimeError) as e:
                self._logger.error("Failed to start recording for %s: %s", key, e)
            except Exception as e:
                self._logger.error("Unexpected error starting recording for %s: %s", key, e, exc_info=True)

        self._runtime.view.set_status("Recording...")

    async def _start_camera_recording(self, key: str, state: CameraWorkerState) -> None:
        """Start recording on a single camera worker."""
        # Generate paths using existing storage utilities
        session_paths = resolve_session_paths(
            self._session_dir,
            state.descriptor.camera_id,
            module_name="Cameras",
            trial_number=self._trial_number or 1,
        )

        # Check disk space
        guard_status = await self._runtime.disk_guard.ensure_ok(session_paths.camera_dir)
        if not guard_status.ok:
            self._logger.warning("Disk guard failed for %s: free=%.2f GB threshold=%.2f GB",
                               key, guard_status.free_gb, guard_status.threshold_gb)
            return

        # Get per-camera record settings (or fall back to global config)
        resolution, fps, overlay_enabled = await self._get_record_settings(key)

        self._logger.info("[RECORDING] Starting %s with resolution=%s fps=%.1f overlay=%s",
                         key, resolution, fps, overlay_enabled)

        # Send start command to worker using worker_key (not state key)
        await self._runtime.worker_manager.start_recording(
            state.worker_key,
            output_dir=str(session_paths.camera_dir),
            filename=session_paths.video_path.name,
            resolution=resolution,
            fps=fps,
            overlay_enabled=overlay_enabled,
            trial_number=self._trial_number,
            csv_enabled=True,
        )

        state.is_recording = True
        state.video_path = str(session_paths.video_path)
        state.csv_path = str(session_paths.timing_path)

    async def _get_record_settings(self, key: str) -> tuple[tuple[int, int], float, bool]:
        """Get record resolution, fps, and overlay setting for a camera."""
        saved = await self._runtime.cache.get_settings(key)
        record_cfg = self._runtime.config.record
        default_resolution = record_cfg.resolution or DEFAULT_CAPTURE_RESOLUTION
        default_fps = record_cfg.fps_cap or DEFAULT_CAPTURE_FPS
        default_overlay = record_cfg.overlay

        resolution = parse_resolution(
            saved.get("record_resolution") if saved else None,
            default_resolution
        )
        fps = parse_fps(
            saved.get("record_fps") if saved else None,
            default_fps
        )
        overlay = parse_bool(
            saved.get("overlay") if saved else None,
            default_overlay
        )

        return resolution, fps, overlay

    async def stop_recording(self) -> None:
        """Stop recording on all camera workers."""
        if not self._recording:
            return

        self._recording = False

        for key, state in self._runtime.camera_states.items():
            if state.is_recording:
                try:
                    await self._runtime.worker_manager.stop_recording(state.worker_key)
                    state.is_recording = False
                except asyncio.CancelledError:
                    raise
                except (OSError, RuntimeError) as e:
                    self._logger.error("Failed to stop recording for %s: %s", key, e)
                except Exception as e:
                    self._logger.error("Unexpected error stopping recording for %s: %s", key, e, exc_info=True)

        self._runtime.view.set_status("Recording stopped")

    async def handle_stop_session_command(self) -> None:
        await self.stop_recording()


__all__ = [
    "CameraWorkerState",
    "DiscoveryController",
    "RecordingController",
]
