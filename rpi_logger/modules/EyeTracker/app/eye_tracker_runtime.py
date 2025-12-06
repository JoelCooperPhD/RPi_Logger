"""Eye tracker runtime that adapts tracker_core onto the stub (codex) stack."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

from rpi_logger.core.commands import StatusMessage, StatusType
from rpi_logger.core.logging_utils import ensure_structured_logger
from vmc import ModuleRuntime, RuntimeContext
from vmc.runtime_helpers import BackgroundTaskManager, ShutdownGuard

class TrackerInitializationError(RuntimeError):
    """Raised when eye tracker initialization fails."""
    pass


try:  # tracker_core dependencies (optional on dev hosts)
    from rpi_logger.modules.EyeTracker.tracker_core.config.tracker_config import TrackerConfig
    from rpi_logger.modules.EyeTracker.tracker_core.device_manager import DeviceManager
    from rpi_logger.modules.EyeTracker.tracker_core.stream_handler import StreamHandler
    from rpi_logger.modules.EyeTracker.tracker_core.frame_processor import FrameProcessor
    from rpi_logger.modules.EyeTracker.tracker_core.recording import RecordingManager
    from rpi_logger.modules.EyeTracker.tracker_core.tracker_handler import TrackerHandler
except Exception as exc:  # pragma: no cover - defensive import guard
    TrackerConfig = None  # type: ignore[assignment]
    DeviceManager = None  # type: ignore[assignment]
    StreamHandler = None  # type: ignore[assignment]
    FrameProcessor = None  # type: ignore[assignment]
    RecordingManager = None  # type: ignore[assignment]
    TrackerHandler = None  # type: ignore[assignment]
    TRACKER_IMPORT_ERROR = exc
else:
    TRACKER_IMPORT_ERROR = None

from .view_adapter import EyeTrackerViewAdapter


class EyeTrackerRuntime(ModuleRuntime):
    """Glue layer between the logger stub stack and tracker_core."""

    def __init__(self, context: RuntimeContext) -> None:
        self.args = context.args
        self.model = context.model
        self.controller = context.controller
        base_logger = ensure_structured_logger(getattr(context, "logger", None), fallback_name="EyeTrackerRuntime")
        self.logger = base_logger.getChild("Runtime")
        self.view = context.view
        self.display_name = context.display_name
        self.module_dir = context.module_dir

        self.task_manager = BackgroundTaskManager("EyeTrackerTasks", self.logger)
        timeout = getattr(self.args, "shutdown_timeout", 20.0)
        self.shutdown_guard = ShutdownGuard(self.logger, timeout=max(5.0, float(timeout)))

        self._shutdown = asyncio.Event()
        self._device_connected = False
        self._tracker_config: Optional[TrackerConfig] = None
        self._device_manager: Optional[DeviceManager] = None
        self._stream_handler: Optional[StreamHandler] = None
        self._frame_processor: Optional[FrameProcessor] = None
        self._recording_manager: Optional[RecordingManager] = None
        self._tracker_handler: Optional[TrackerHandler] = None
        self._tracker_task: Optional[asyncio.Task] = None
        self._device_task: Optional[asyncio.Task] = None
        self._device_ready_event: Optional[asyncio.Event] = None
        self._view_adapter: Optional[EyeTrackerViewAdapter] = None
        self._session_dir: Optional[Path] = None
        self._import_error = TRACKER_IMPORT_ERROR
        self._auto_start_task: Optional[asyncio.Task] = None

        # Assigned device from main UI (network address)
        self._assigned_device_id: Optional[str] = None
        self._assigned_network_address: Optional[str] = None
        self._assigned_network_port: Optional[int] = None

        self.model.subscribe(self._on_model_change)

    # ------------------------------------------------------------------
    # ModuleRuntime interface

    async def start(self) -> None:
        self.logger.info("Starting %s runtime", self.display_name)

        if self._import_error:
            self.logger.error("tracker_core dependencies unavailable: %s", self._import_error)
            if self.view:
                self._attach_view(disabled_message=str(self._import_error))
            return

        self._build_tracker_components()
        self._attach_view()

        self._device_ready_event = asyncio.Event()

        # Don't auto-start device discovery - wait for assign_device from main UI
        # The main UI handles mDNS discovery and will assign devices via command
        if self._view_adapter:
            self._view_adapter.set_device_status("Waiting for device assignment...", connected=False)

        if getattr(self.args, "auto_start_recording", False):
            self._auto_start_task = self.task_manager.create(self._auto_start_recording())

    async def shutdown(self) -> None:
        if self._shutdown.is_set():
            return
        self._shutdown.set()

        await self.shutdown_guard.start()

        if self._auto_start_task and not self._auto_start_task.done():
            self._auto_start_task.cancel()

        try:
            await self.task_manager.shutdown()
            await self._stop_tracker()

            if self._recording_manager and self._recording_manager.is_recording:
                with contextlib.suppress(Exception):
                    await self._recording_manager.stop_recording()
        finally:
            await self.shutdown_guard.cancel()

    async def cleanup(self) -> None:
        if self._tracker_handler:
            with contextlib.suppress(Exception):
                await self._tracker_handler.cleanup()
        if self._recording_manager:
            with contextlib.suppress(Exception):
                await self._recording_manager.cleanup()
        if self._device_manager and hasattr(self._device_manager, "cleanup"):
            with contextlib.suppress(Exception):
                await self._device_manager.cleanup()  # type: ignore[misc]
        if self._view_adapter:
            self._view_adapter.close()
            self._view_adapter = None

    async def handle_command(self, command: Dict[str, Any]) -> bool:
        action = (command.get("command") or "").lower()
        if action == "start_recording":
            return await self._start_recording_flow(command)
        if action == "stop_recording":
            return await self._stop_recording_flow()
        if action in {"reconnect", "refresh_device", "eye_tracker_reconnect"}:
            await self.request_reconnect()
            return True
        if action == "assign_device":
            return await self._assign_device(command)
        if action == "unassign_device":
            return await self._unassign_device(command)
        return False

    async def handle_user_action(self, action: str, **kwargs: Any) -> bool:
        normalized = (action or "").lower()
        if normalized in {"refresh_device", "eye_tracker_reconnect"}:
            await self.request_reconnect()
            return True
        return False

    async def healthcheck(self) -> bool:
        return bool(self._device_connected)

    async def on_session_dir_available(self, path: Path) -> None:
        self._session_dir = path
        if self._recording_manager:
            self._recording_manager.set_session_context(path)

    # ------------------------------------------------------------------
    # Tracker lifecycle helpers

    def _build_tracker_components(self) -> None:
        config = TrackerConfig(
            fps=float(getattr(self.args, "target_fps", 5.0)),
            resolution=(int(getattr(self.args, "width", 1280)), int(getattr(self.args, "height", 720))),
            output_dir=str(Path(getattr(self.args, "output_dir", self.module_dir / "recordings"))),
            display_width=int(getattr(self.args, "preview_width", 640) or 640),
            preview_width=int(getattr(self.args, "preview_width", 640) or 640),
            preview_height=int(getattr(self.args, "preview_height", 480) or 480),
            enable_recording_overlay=bool(getattr(self.args, "enable_recording_overlay", True)),
            include_gaze_in_recording=bool(getattr(self.args, "include_gaze_in_recording", True)),
            overlay_font_scale=float(getattr(self.args, "overlay_font_scale", 0.6)),
            overlay_thickness=int(getattr(self.args, "overlay_thickness", 1)),
            overlay_color_r=int(getattr(self.args, "overlay_color_r", 0)),
            overlay_color_g=int(getattr(self.args, "overlay_color_g", 0)),
            overlay_color_b=int(getattr(self.args, "overlay_color_b", 0)),
            overlay_margin_left=int(getattr(self.args, "overlay_margin_left", 10)),
            overlay_line_start_y=int(getattr(self.args, "overlay_line_start_y", 30)),
            gaze_circle_radius=int(getattr(self.args, "gaze_circle_radius", 10)),
            gaze_circle_thickness=int(getattr(self.args, "gaze_circle_thickness", 1)),
            gaze_center_radius=int(getattr(self.args, "gaze_center_radius", 1)),
            gaze_shape=str(getattr(self.args, "gaze_shape", "circle")),
            gaze_color_worn_b=int(getattr(self.args, "gaze_color_worn_b", 255)),
            gaze_color_worn_g=int(getattr(self.args, "gaze_color_worn_g", 255)),
            gaze_color_worn_r=int(getattr(self.args, "gaze_color_worn_r", 0)),
            gaze_color_not_worn_b=int(getattr(self.args, "gaze_color_not_worn_b", 0)),
            gaze_color_not_worn_g=int(getattr(self.args, "gaze_color_not_worn_g", 0)),
            gaze_color_not_worn_r=int(getattr(self.args, "gaze_color_not_worn_r", 255)),
            enable_advanced_gaze_logging=bool(getattr(self.args, "enable_advanced_gaze_logging", False)),
            expand_eye_event_details=bool(getattr(self.args, "expand_eye_event_details", True)),
            enable_audio_recording=bool(getattr(self.args, "enable_audio_recording", False)),
            audio_stream_param=str(getattr(self.args, "audio_stream_param", "audio=scene")),
            enable_device_status_logging=bool(getattr(self.args, "enable_device_status_logging", False)),
            device_status_poll_interval=float(getattr(self.args, "device_status_poll_interval", 5.0)),
        )

        self._tracker_config = config
        self._device_manager = DeviceManager()
        self._device_manager.audio_stream_param = config.audio_stream_param
        self._stream_handler = StreamHandler()
        self._frame_processor = FrameProcessor(config)
        self._recording_manager = RecordingManager(config, device_manager=self._device_manager)
        self._tracker_handler = TrackerHandler(
            config,
            self._device_manager,
            self._stream_handler,
            self._frame_processor,
            self._recording_manager,
        )

    def _attach_view(self, disabled_message: Optional[str] = None) -> None:
        if not self.view:
            return
        preview_hz = max(1, int(getattr(self.args, "gui_preview_update_hz", 10)))
        self._view_adapter = EyeTrackerViewAdapter(
            self.view,
            model=self.model,
            logger=self.logger.getChild("ViewAdapter"),
            frame_provider=self._get_latest_frame,
            preview_hz=preview_hz,
            disabled_message=disabled_message,
            runtime=self,
        )
        # Bind runtime for button callbacks
        self._view_adapter.bind_runtime(self)

    def _start_device_monitor(self, *, force: bool = False) -> None:
        if self._shutdown.is_set():
            return

        if self._device_connected:
            if self._device_ready_event:
                self._device_ready_event.set()
            return

        if force and self._device_task and not self._device_task.done():
            self._device_task.cancel()
            self._device_task = None

        if self._device_task and not self._device_task.done():
            return

        if self._device_ready_event:
            self._device_ready_event.clear()

        self._device_task = self.task_manager.create(
            self._ensure_tracker_ready(),
            name="EyeTrackerDeviceConnect",
        )
        self._device_task.add_done_callback(lambda _: setattr(self, "_device_task", None))

    async def _ensure_tracker_ready(self) -> None:
        if self._tracker_handler is None or self._device_manager is None:
            return
        if self._tracker_task and not self._tracker_task.done():
            return
        if self._shutdown.is_set():
            return

        timeout = max(1.0, float(getattr(self.args, "discovery_timeout", 5.0)))
        retry_interval = max(1.0, float(getattr(self.args, "discovery_retry", 3.0)))

        while not self._shutdown.is_set():
            try:
                connected = await asyncio.wait_for(self._device_manager.connect(), timeout=timeout)
            except (asyncio.TimeoutError, Exception) as exc:
                connected = False
                self.logger.debug("Device discovery attempt failed: %s", exc)

            if connected:
                self._device_connected = True
                if self._device_ready_event:
                    self._device_ready_event.set()
                self.logger.info("Eye tracker connected")
                if self._view_adapter:
                    self._view_adapter.set_device_status("Connected", connected=True)
                await self._start_tracker_background()
                return

            if self._view_adapter:
                self._view_adapter.set_device_status("Searching for device...", connected=False)

            self.logger.info("Eye tracker not found; retrying in %.1fs", retry_interval)
            try:
                await asyncio.wait_for(self._shutdown.wait(), timeout=retry_interval)
                return
            except asyncio.TimeoutError:
                continue

    async def _start_tracker_background(self) -> None:
        if not self._tracker_handler:
            return
        try:
            tracker = await self._tracker_handler.start_background(display_enabled=False)
            task = getattr(self._tracker_handler, "_run_task", None)
            if isinstance(task, asyncio.Task):
                self._tracker_task = self.task_manager.add(task)
                task.add_done_callback(lambda _: self._on_tracker_stopped())
            self.logger.info("Gaze tracker loop started")
            if self._view_adapter:
                self._view_adapter.set_device_status("Streaming", connected=True)
        except Exception as exc:
            self.logger.exception("Failed to start gaze tracker: %s", exc)
            self._device_connected = False
            if self._view_adapter:
                self._view_adapter.set_device_status("Tracker error", connected=False)
            raise TrackerInitializationError(str(exc)) from exc

    def _on_tracker_stopped(self) -> None:
        self.logger.info("Gaze tracker loop exited")
        self._device_connected = False
        if self._device_ready_event:
            self._device_ready_event.clear()
        if self._view_adapter:
            self._view_adapter.set_device_status("Disconnected", connected=False)
        if not self._shutdown.is_set():
            self._start_device_monitor()

    async def _stop_tracker(self) -> None:
        if self._tracker_handler:
            with contextlib.suppress(Exception):
                await self._tracker_handler.stop()
        self._tracker_task = None
        self._device_connected = False
        if self._device_ready_event:
            self._device_ready_event.clear()
        if self._view_adapter:
            self._view_adapter.set_device_status("Stopped", connected=False)

    async def request_reconnect(self) -> None:
        if self._shutdown.is_set():
            return

        self.logger.info("Reconnect requested")
        await self._stop_tracker()

        if self._device_manager:
            with contextlib.suppress(Exception):
                await self._device_manager.cleanup()

        if self._view_adapter:
            self._view_adapter.set_device_status("Searching for device...", connected=False)

        self._start_device_monitor(force=True)

    # ------------------------------------------------------------------
    # Device assignment (from main UI)

    async def _assign_device(self, command: Dict[str, Any]) -> bool:
        """Handle device assignment from main UI.

        The main UI discovers eye trackers via mDNS and sends us the
        network address to connect to directly (no discovery needed).
        """
        device_id = command.get("device_id", "")
        network_address = command.get("network_address", "")
        network_port = command.get("network_port", 8080)

        if not network_address:
            self.logger.error("assign_device: missing network_address")
            StatusMessage.send(StatusType.DEVICE_ERROR, {
                "device_id": device_id,
                "message": "Missing network address",
            })
            return False

        self.logger.info(
            "Assigning device %s at %s:%s",
            device_id, network_address, network_port
        )

        # Store assigned device info
        self._assigned_device_id = device_id
        self._assigned_network_address = network_address
        self._assigned_network_port = int(network_port)

        # Stop any existing tracker and reconnect with new address
        await self._stop_tracker()

        if self._device_manager:
            with contextlib.suppress(Exception):
                await self._device_manager.cleanup()

        # Connect using the assigned address
        if self._view_adapter:
            self._view_adapter.set_device_status(f"Connecting to {network_address}...", connected=False)

        success = await self._connect_to_assigned_device()

        if success:
            StatusMessage.send(StatusType.DEVICE_ASSIGNED, {
                "device_id": device_id,
                "device_type": "Pupil_Labs_Neon",
            })
            return True
        else:
            StatusMessage.send(StatusType.DEVICE_ERROR, {
                "device_id": device_id,
                "message": f"Failed to connect to {network_address}:{network_port}",
            })
            return False

    async def _unassign_device(self, command: Dict[str, Any]) -> bool:
        """Handle device unassignment from main UI."""
        device_id = command.get("device_id", "")

        if self._assigned_device_id and self._assigned_device_id != device_id:
            self.logger.warning(
                "Unassign request for %s but current device is %s",
                device_id, self._assigned_device_id
            )

        self.logger.info("Unassigning device %s", device_id or self._assigned_device_id)

        # Stop tracker
        await self._stop_tracker()

        if self._device_manager:
            with contextlib.suppress(Exception):
                await self._device_manager.cleanup()

        # Clear assigned device info
        old_device_id = self._assigned_device_id
        self._assigned_device_id = None
        self._assigned_network_address = None
        self._assigned_network_port = None

        if self._view_adapter:
            self._view_adapter.set_device_status("No device assigned", connected=False)

        StatusMessage.send(StatusType.DEVICE_UNASSIGNED, {
            "device_id": old_device_id or device_id,
        })

        return True

    async def _connect_to_assigned_device(self) -> bool:
        """Connect to the assigned device using stored network address.

        Uses rollback pattern: if connection fails at any point, all state
        changes are reverted to maintain consistency.
        """
        if not self._assigned_network_address or not self._device_manager:
            return False

        address = self._assigned_network_address
        port = self._assigned_network_port or 8080

        # Store previous state for rollback
        prev_device = getattr(self._device_manager, 'device', None)
        prev_ip = getattr(self._device_manager, 'device_ip', None)
        prev_port = getattr(self._device_manager, 'device_port', None)
        prev_connected = self._device_connected

        try:
            # Use direct connection with known address instead of discovery
            from pupil_labs.realtime_api.device import Device

            self.logger.info("Connecting directly to %s:%s", address, port)

            # Create device directly without discovery
            device = Device(address=address, port=str(port))

            # Store the device in the device manager
            self._device_manager.device = device
            self._device_manager.device_ip = address
            self._device_manager.device_port = port

            # Refresh status to verify connection
            status = await self._device_manager.refresh_status()
            if status is None:
                raise ConnectionError("Failed to get device status - device may not be reachable")

            self._device_connected = True
            if self._device_ready_event:
                self._device_ready_event.set()

            self.logger.info("Connected to eye tracker at %s:%s", address, port)

            # Update view with device info
            if self._view_adapter:
                self._view_adapter.set_device_status("Connected", connected=True)
                device_name = f"Neon @ {address}"
                self._view_adapter.set_device_info(device_name)

            # Start the tracker background task
            await self._start_tracker_background()
            return True

        except Exception as exc:
            # Rollback all state changes on failure
            self.logger.error("Failed to connect to assigned device: %s", exc)

            # Restore previous device manager state
            if self._device_manager:
                self._device_manager.device = prev_device
                self._device_manager.device_ip = prev_ip
                self._device_manager.device_port = prev_port

            # Restore connection state
            self._device_connected = prev_connected
            if self._device_ready_event and not prev_connected:
                self._device_ready_event.clear()

            # Update view
            if self._view_adapter:
                error_msg = str(exc)[:50] if len(str(exc)) > 50 else str(exc)
                self._view_adapter.set_device_status(f"Failed: {error_msg}", connected=False)
                self._view_adapter.set_device_info("None")

            return False

    # ------------------------------------------------------------------
    # Recording helpers

    async def _start_recording_flow(self, payload: Dict[str, Any]) -> bool:
        if not self._recording_manager:
            self.logger.warning("Recording manager unavailable")
            self.model.recording = False
            return False

        if not self._device_connected:
            self._start_device_monitor()
            wait_timeout = max(1.0, float(getattr(self.args, "discovery_timeout", 5.0)))
            ready_event = self._device_ready_event
            if ready_event is not None:
                self.logger.info("Waiting up to %.1fs for eye tracker connection", wait_timeout)
                try:
                    await asyncio.wait_for(ready_event.wait(), timeout=wait_timeout)
                except asyncio.TimeoutError:
                    pass
            if not self._device_connected:
                self.logger.warning("Cannot start recording: device not connected")
                self.model.recording = False
                return False

        session_dir = payload.get("session_dir")
        session_path: Optional[Path] = None
        if session_dir:
            session_path = Path(session_dir)
        elif self.model.session_dir:
            session_path = Path(self.model.session_dir)
        elif self._session_dir:
            session_path = self._session_dir
        else:
            session_path = await self._generate_session_dir()

        session_path.mkdir(parents=True, exist_ok=True)
        trial_number = int(payload.get("trial_number") or (self.model.trial_number or 1))
        self._recording_manager.set_session_context(session_path, trial_number)
        self.model.trial_number = trial_number

        try:
            await self._recording_manager.start_recording(session_path, trial_number)
        except Exception as exc:
            self.logger.error("Failed to start recording: %s", exc, exc_info=exc)
            self.model.recording = False
            if self._view_adapter:
                self._view_adapter.set_recording_state(False)
            return False

        module_session_dir = self._recording_manager.current_session_dir or session_path
        self._session_dir = module_session_dir
        self.model.session_dir = module_session_dir

        StatusMessage.send(
            StatusType.RECORDING_STARTED,
            {
                "module": self.display_name,
                "session_dir": str(module_session_dir),
                "trial_number": trial_number,
            },
        )
        if self._view_adapter:
            self._view_adapter.set_recording_state(True)
        self.logger.info("Recording started -> %s", module_session_dir)
        self.model.recording = True
        return True

    async def _stop_recording_flow(self) -> bool:
        if not self._recording_manager or not self._recording_manager.is_recording:
            return False
        try:
            stats = await self._recording_manager.stop_recording()
        except Exception as exc:
            self.logger.error("Failed to stop recording: %s", exc, exc_info=exc)
            return False

        StatusMessage.send(
            StatusType.RECORDING_STOPPED,
            {
                "module": self.display_name,
                "session_dir": str(self._session_dir) if self._session_dir else None,
                "stats": stats,
            },
        )
        if self._view_adapter:
            self._view_adapter.set_recording_state(False)
        self.logger.info("Recording stopped")
        self.model.recording = False
        return True

    async def _generate_session_dir(self) -> Path:
        root = Path(getattr(self.args, "output_dir", self.module_dir / "recordings"))
        root.mkdir(parents=True, exist_ok=True)
        prefix = getattr(self.args, "session_prefix", "session")
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        path = root / f"{prefix}_{timestamp}"
        path.mkdir(parents=True, exist_ok=True)
        self.model.session_dir = path
        return path

    # ------------------------------------------------------------------
    # View helpers

    def _get_latest_frame(self) -> Optional[np.ndarray]:
        if not self._tracker_handler:
            return None
        return self._tracker_handler.get_display_frame()

    # ------------------------------------------------------------------
    # Recording automation

    async def _auto_start_recording(self) -> None:
        await asyncio.sleep(3.0)
        if self._shutdown.is_set():
            return
        if not self._recording_manager or self._recording_manager.is_recording:
            return
        self.logger.info("Auto-starting recording")
        await self._start_recording_flow({})

    # ------------------------------------------------------------------
    # Model observer

    def _on_model_change(self, prop: str, value: Any) -> None:
        if self._view_adapter is None:
            return
        if prop == "recording":
            self._view_adapter.set_recording_state(bool(value))
        elif prop == "session_dir" and isinstance(value, Path):
            self._session_dir = value

    # ------------------------------------------------------------------
    # Properties

    @property
    def view_adapter(self) -> Optional[EyeTrackerViewAdapter]:
        return self._view_adapter
