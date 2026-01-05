"""Neon EyeTracker VMC runtime adapter."""

from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path
from typing import Any, Dict, Optional, TYPE_CHECKING

import numpy as np

from rpi_logger.core.commands import StatusMessage, StatusType
from rpi_logger.core.logging_utils import ensure_structured_logger
from rpi_logger.modules.base.storage_utils import ensure_module_data_dir
from vmc import ModuleRuntime, RuntimeContext
from vmc.runtime_helpers import BackgroundTaskManager, ShutdownGuard

from ..config import EyeTrackerConfig

if TYPE_CHECKING:
    from .view import NeonEyeTrackerView


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
except (ImportError, ModuleNotFoundError) as exc:  # pragma: no cover - missing dependencies
    TrackerConfig = None  # type: ignore[assignment]
    DeviceManager = None  # type: ignore[assignment]
    StreamHandler = None  # type: ignore[assignment]
    FrameProcessor = None  # type: ignore[assignment]
    RecordingManager = None  # type: ignore[assignment]
    TrackerHandler = None  # type: ignore[assignment]
    TRACKER_IMPORT_ERROR = exc
else:
    TRACKER_IMPORT_ERROR = None

# Module constants
MODULE_SUBDIR = "EyeTracker-Neon"


class EyeTrackerRuntime(ModuleRuntime):
    """VMC runtime for Neon: manages connection, streaming, recording (device assigned via commands)."""

    def __init__(self, context: RuntimeContext) -> None:
        self.args = context.args
        self.model = context.model
        self.controller = context.controller
        base_logger = ensure_structured_logger(getattr(context, "logger", None), fallback_name="NeonEyeTrackerRuntime")
        self.logger = base_logger.getChild("Runtime")
        self.view: Optional["NeonEyeTrackerView"] = context.view
        self.display_name = context.display_name
        self.module_dir = context.module_dir

        # Config path for runtime access
        self.config_path = Path(getattr(self.args, "config_path", self.module_dir / "config.txt"))

        # Load typed config via preferences_scope
        scope_fn = getattr(context.model, "preferences_scope", None)
        prefs = scope_fn("neon_eyetracker") if callable(scope_fn) else None
        self.typed_config = EyeTrackerConfig.from_preferences(prefs, self.args) if prefs else EyeTrackerConfig()

        self.task_manager = BackgroundTaskManager("NeonEyeTrackerTasks", self.logger)
        timeout = getattr(self.args, "shutdown_timeout", 20.0)
        self.shutdown_guard = ShutdownGuard(self.logger, timeout=max(5.0, float(timeout)))

        # Event loop reference for model callbacks
        self._loop: Optional[asyncio.AbstractEventLoop] = None

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
        self._session_dir: Optional[Path] = None
        self._module_data_dir: Optional[Path] = None
        self._import_error = TRACKER_IMPORT_ERROR
        self._auto_start_task: Optional[asyncio.Task] = None

        # Assigned device from main UI (network address)
        self._assigned_device_id: Optional[str] = None
        self._assigned_network_address: Optional[str] = None
        self._assigned_network_port: Optional[int] = None

        # Recording state
        self._trial_label: str = ""
        self._recording_active: bool = False

        self.model.subscribe(self._on_model_change)

    # ------------------------------------------------------------------
    # ModuleRuntime interface

    async def start(self) -> None:

        # Store event loop reference for model callbacks
        self._loop = asyncio.get_running_loop()

        if self._import_error:
            self.logger.error("tracker_core dependencies unavailable: %s", self._import_error)
            return

        self._build_tracker_components()

        # Bind runtime to view (DRT pattern)
        if self.view:
            self.view.bind_runtime(self)
            self.view.set_device_status("Waiting for device assignment...", connected=False)
            stub_view = getattr(self.view, '_stub_view', None)
            if stub_view and hasattr(stub_view, 'set_data_subdir'):
                stub_view.set_data_subdir(MODULE_SUBDIR)

        self._device_ready_event = asyncio.Event()

        if getattr(self.args, "auto_start_recording", False):
            self._auto_start_task = self.task_manager.create(self._auto_start_recording())

        # Notify logger that module is ready for commands
        # This is the handshake signal that turns the indicator green
        StatusMessage.send("ready")

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

    async def handle_command(self, command: Dict[str, Any]) -> bool:
        action = (command.get("command") or "").lower()

        # Recording commands
        if action in ("start_recording", "record"):
            return await self._start_recording_flow(command)
        if action in ("stop_recording", "pause"):
            return await self._stop_recording_flow()
        if action == "stop_session":
            if self._recording_manager and self._recording_manager.is_recording:
                await self._stop_recording_flow()
            self._trial_label = ""
            self._session_dir = None
            self._module_data_dir = None
            return True

        # Device commands
        if action == "assign_device":
            command_id = command.get("command_id")
            return await self._assign_device(command, command_id=command_id)
        if action == "unassign_device":
            return await self._unassign_device(command)
        if action == "unassign_all_devices":
            # Single-device module: unassign current device if any
            command_id = command.get("command_id")
            self.logger.info("Unassigning device before shutdown (command_id=%s)", command_id)

            port_released = False
            if self._assigned_device_id:
                await self._unassign_device({"device_id": self._assigned_device_id})
                port_released = True

            # Send ACK to confirm device release
            StatusMessage.send(
                StatusType.DEVICE_UNASSIGNED,
                {
                    "device_id": self._assigned_device_id or "",
                    "port_released": port_released,
                },
                command_id=command_id,
            )
            return True

        # Window commands
        if action == "show_window":
            self._show_window()
            return True
        if action == "hide_window":
            self._hide_window()
            return True

        return False

    def _show_window(self) -> None:
        """Show module window (delegated to stub view)."""
        if self.view and hasattr(self.view, '_stub_view'):
            stub_view = getattr(self.view, '_stub_view', None)
            if stub_view and hasattr(stub_view, 'show_window'):
                stub_view.show_window()

    def _hide_window(self) -> None:
        """Hide module window (delegated to stub view)."""
        if self.view and hasattr(self.view, '_stub_view'):
            stub_view = getattr(self.view, '_stub_view', None)
            if stub_view and hasattr(stub_view, 'hide_window'):
                stub_view.hide_window()

    async def handle_user_action(self, action: str, **kwargs: Any) -> bool:
        return False

    async def healthcheck(self) -> bool:
        return bool(self._device_connected)

    async def on_session_dir_available(self, path: Path) -> None:
        self._session_dir = path
        if self._recording_manager:
            self._recording_manager.set_session_context(path)

    # ------------------------------------------------------------------
    # Tracker lifecycle helpers

    @staticmethod
    def _parse_bool(value: Any) -> bool:
        """Parse a value to boolean, handling string representations."""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"true", "1", "yes", "on"}
        return bool(value)

    def _build_tracker_components(self) -> None:
        config = TrackerConfig(
            fps=float(getattr(self.args, "target_fps", 5.0)),
            eyes_fps=float(getattr(self.args, "eyes_fps", 30.0)),
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
            gaze_circle_radius=int(getattr(self.args, "gaze_circle_radius", 60)),
            gaze_circle_thickness=int(getattr(self.args, "gaze_circle_thickness", 6)),
            gaze_center_radius=int(getattr(self.args, "gaze_center_radius", 4)),
            gaze_shape=str(getattr(self.args, "gaze_shape", "circle")),
            gaze_color_worn_b=int(getattr(self.args, "gaze_color_worn_b", 0)),
            gaze_color_worn_g=int(getattr(self.args, "gaze_color_worn_g", 0)),
            gaze_color_worn_r=int(getattr(self.args, "gaze_color_worn_r", 255)),
            audio_stream_param=str(getattr(self.args, "audio_stream_param", "audio=scene")),
            # Stream viewer enable states (persisted via Controls menu)
            stream_video_enabled=self._parse_bool(getattr(self.args, "stream_video_enabled", True)),
            stream_gaze_enabled=self._parse_bool(getattr(self.args, "stream_gaze_enabled", True)),
            stream_eyes_enabled=self._parse_bool(getattr(self.args, "stream_eyes_enabled", False)),
            stream_imu_enabled=self._parse_bool(getattr(self.args, "stream_imu_enabled", False)),
            stream_events_enabled=self._parse_bool(getattr(self.args, "stream_events_enabled", False)),
            stream_audio_enabled=self._parse_bool(getattr(self.args, "stream_audio_enabled", False)),
        )

        self._tracker_config = config
        self._device_manager = DeviceManager()
        self._device_manager.audio_stream_param = config.audio_stream_param
        self._stream_handler = StreamHandler()
        self._frame_processor = FrameProcessor(config)
        self._recording_manager = RecordingManager(config)
        self._tracker_handler = TrackerHandler(
            config,
            self._device_manager,
            self._stream_handler,
            self._frame_processor,
            self._recording_manager,
        )

    def _clear_device_task(self, completed_task: asyncio.Task) -> None:
        """Clear device task reference only if it matches the completed task."""
        if self._device_task is completed_task:
            self._device_task = None

    def _attempt_reconnect_to_assigned(self) -> None:
        """Attempt to reconnect to the previously assigned device.

        Device discovery is centralized in the main logger. This method
        only attempts to reconnect if we have an assigned device address.
        """
        if self._shutdown.is_set():
            return

        if self._device_connected:
            if self._device_ready_event:
                self._device_ready_event.set()
            return

        # Only reconnect if we have an assigned device
        if not self._assigned_network_address:
            self.logger.debug("No assigned device to reconnect to")
            if self.view:
                self.view.set_device_status("Waiting for device assignment...", connected=False)
            return

        if self._device_task and not self._device_task.done():
            return

        if self._device_ready_event:
            self._device_ready_event.clear()

        task = self.task_manager.create(
            self._reconnect_to_assigned(),
            name="EyeTrackerReconnect",
        )
        self._device_task = task
        task.add_done_callback(lambda t: self._clear_device_task(t))

    async def _reconnect_to_assigned(self) -> None:
        """Reconnect to the assigned device address."""
        if not self._assigned_network_address or self._shutdown.is_set():
            return

        if self.view:
            self.view.set_device_status(
                f"Reconnecting to {self._assigned_network_address}...", connected=False
            )

        success = await self._connect_to_assigned_device()

        if not success:
            self.logger.warning("Failed to reconnect to assigned device")
            if self.view:
                self.view.set_device_status("Reconnect failed", connected=False)

    async def _start_tracker_background(self) -> None:
        if not self._tracker_handler:
            return
        try:
            tracker = await self._tracker_handler.start_background(display_enabled=False)
            task = getattr(self._tracker_handler, "_run_task", None)
            if isinstance(task, asyncio.Task):
                self._tracker_task = self.task_manager.add(task)
                task.add_done_callback(lambda _: self._on_tracker_stopped())
            if self.view:
                self.view.set_device_status("Streaming", connected=True)
        except Exception as exc:
            self.logger.error("Failed to start gaze tracker: %s", exc)
            self._device_connected = False
            if self.view:
                self.view.set_device_status("Tracker error", connected=False)
            raise TrackerInitializationError(str(exc)) from exc

    def _on_tracker_stopped(self) -> None:
        self._device_connected = False
        if self._device_ready_event:
            self._device_ready_event.clear()
        if self.view:
            self.view.set_device_status("Disconnected", connected=False)
        if not self._shutdown.is_set():
            self._attempt_reconnect_to_assigned()

    async def _stop_tracker(self) -> None:
        if self._tracker_handler:
            with contextlib.suppress(Exception):
                await self._tracker_handler.stop()
        self._tracker_task = None
        self._device_connected = False
        if self._device_ready_event:
            self._device_ready_event.clear()
        if self.view:
            self.view.set_device_status("Stopped", connected=False)

    # ------------------------------------------------------------------
    # Device assignment (from main UI)

    async def _assign_device(self, command: Dict[str, Any], *, command_id: str | None = None) -> bool:
        """Assign device from main UI (mDNS discovery handled externally)."""
        device_id = command.get("device_id", "")
        network_address = command.get("network_address", "")
        network_port = command.get("network_port", 8080)

        if not network_address:
            self.logger.error("assign_device: missing network_address")
            StatusMessage.send("device_error", {
                "device_id": device_id,
                "error": "Missing network address",
            }, command_id=command_id)
            return False


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
        if self.view:
            self.view.set_device_status(f"Connecting to {network_address}...", connected=False)

        success = await self._connect_to_assigned_device()

        if success:
            # Update window title: EyeTracker(Network):address
            if self.view:
                short_addr = network_address
                if len(short_addr) > 15:
                    short_addr = short_addr[:12] + "..."
                title = f"EyeTracker-Neon(Network):{short_addr}"
                try:
                    self.view.set_window_title(title)
                except Exception:
                    pass

            # Send acknowledgement to logger that device is ready
            # This turns the indicator from yellow (CONNECTING) to green (CONNECTED)
            StatusMessage.send("device_ready", {"device_id": device_id}, command_id=command_id)
            return True
        else:
            StatusMessage.send("device_error", {
                "device_id": device_id,
                "error": f"Failed to connect to {network_address}:{network_port}",
            }, command_id=command_id)
            return False

    async def _unassign_device(self, command: Dict[str, Any]) -> bool:
        """Handle device unassignment from main UI."""
        device_id = command.get("device_id", "")

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

        if self.view:
            self.view.set_device_status("No device assigned", connected=False)

        StatusMessage.send("device_unassigned", {
            "device_id": old_device_id or device_id,
        })

        return True

    async def _connect_to_assigned_device(self) -> bool:
        """Connect to assigned device (rollback on failure)."""
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

            # Update view with device info
            if self.view:
                self.view.set_device_status("Connected", connected=True)
                device_name = f"Neon @ {address}"
                self.view.set_device_info(device_name)

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
            if self.view:
                error_msg = str(exc)[:50] if len(str(exc)) > 50 else str(exc)
                self.view.set_device_status(f"Failed: {error_msg}", connected=False)
                self.view.set_device_info("None")

            return False

    # ------------------------------------------------------------------
    # Recording helpers

    async def _start_recording_flow(self, payload: Dict[str, Any]) -> bool:
        if not self._recording_manager:
            self.logger.warning("Recording manager unavailable")
            self.model.recording = False
            return False

        if not self._device_connected:
            # Try to reconnect to assigned device if we have one
            if self._assigned_network_address:
                self._attempt_reconnect_to_assigned()
                wait_timeout = max(1.0, float(getattr(self.args, "discovery_timeout", 5.0)))
                ready_event = self._device_ready_event
                if ready_event is not None:
                    try:
                        await asyncio.wait_for(ready_event.wait(), timeout=wait_timeout)
                    except asyncio.TimeoutError:
                        pass
            if not self._device_connected:
                self.logger.warning("Cannot start recording: device not connected (assign device first)")
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

        # Use shared utility to ensure module subdirectory exists
        module_data_dir = ensure_module_data_dir(session_path, MODULE_SUBDIR)
        self._module_data_dir = module_data_dir

        trial_number = int(payload.get("trial_number") or (self.model.trial_number or 1))
        self._trial_label = str(payload.get("trial_label", "") or "")
        self._recording_manager.set_session_context(
            module_data_dir,
            trial_number,
            trial_label=self._trial_label
        )
        self.model.trial_number = trial_number

        try:
            await self._recording_manager.start_recording(module_data_dir, trial_number)
        except Exception as exc:
            self.logger.error("Failed to start recording: %s", exc, exc_info=exc)
            self.model.recording = False
            if self.view:
                self.view.set_recording_state(False)
            return False

        module_session_dir = self._recording_manager.current_session_dir or module_data_dir
        self._session_dir = session_path
        self.model.session_dir = session_path

        StatusMessage.send("recording_started", {
            "module": self.display_name,
            "device_id": self._assigned_device_id,
            "session_dir": str(module_session_dir),
            "trial_number": trial_number,
            "trial_label": self._trial_label,
        })
        if self.view:
            self.view.set_recording_state(True)
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

        StatusMessage.send("recording_stopped", {
            "module": self.display_name,
            "device_id": self._assigned_device_id,
            "session_dir": str(self._module_data_dir) if self._module_data_dir else None,
            "stats": stats,
            "duration": stats.get("duration") if stats else None,
            "frames_written": stats.get("frames_written") if stats else None,
        })
        if self.view:
            self.view.set_recording_state(False)
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

    def _get_latest_eyes_frame(self) -> Optional[np.ndarray]:
        if not self._stream_handler:
            return None
        return self._stream_handler.get_latest_eyes_frame()

    def _get_latest_gaze(self) -> Optional[Any]:
        """Get latest gaze data for stream viewer."""
        if not self._stream_handler:
            return None
        return self._stream_handler.get_latest_gaze()

    def _get_latest_imu(self) -> Optional[Any]:
        """Get latest IMU data for stream viewer."""
        if not self._stream_handler:
            return None
        return self._stream_handler.get_latest_imu()

    def _get_latest_event(self) -> Optional[Any]:
        """Get latest eye event for stream viewer."""
        if not self._stream_handler:
            return None
        return self._stream_handler.get_latest_event()

    def _get_latest_audio(self) -> Optional[Any]:
        """Get latest audio data for stream viewer."""
        if not self._stream_handler:
            return None
        return self._stream_handler.get_latest_audio()

    def _get_metrics(self) -> Dict[str, Any]:
        """Get current FPS metrics for display."""
        if not self._stream_handler or not self._tracker_config:
            return {}

        # Get recording FPS (only when recording)
        is_recording = self._recording_manager and self._recording_manager.is_recording
        fps_record = None
        if is_recording and self._recording_manager:
            fps_record = self._recording_manager.get_record_fps()

        # Get display FPS from tracker handler
        fps_display = 0.0
        if self._tracker_handler:
            fps_display = self._tracker_handler.get_display_fps()

        return {
            # Capture: from Neon device (raw 30Hz stream)
            "fps_capture": self._stream_handler.get_camera_fps(),
            "target_fps": 30.0,  # Neon raw capture rate

            # Record: frames written to video file
            "fps_record": fps_record,
            "target_record_fps": self._tracker_config.fps if is_recording else None,

            # Display: frames shown in GUI preview
            "fps_display": fps_display,
            "target_display_fps": self._tracker_config.preview_fps,
        }

    @property
    def config(self) -> Optional["TrackerConfig"]:
        """Return tracker config for stream controls persistence."""
        return self._tracker_config

    # ------------------------------------------------------------------
    # Recording automation

    async def _auto_start_recording(self) -> None:
        await asyncio.sleep(3.0)
        if self._shutdown.is_set():
            return
        if not self._recording_manager or self._recording_manager.is_recording:
            return
        await self._start_recording_flow({})

    # ------------------------------------------------------------------
    # Model observer

    def _on_model_change(self, prop: str, value: Any) -> None:
        if prop == "recording":
            if self.view:
                self.view.set_recording_state(bool(value))
        elif prop == "session_dir":
            if not value:
                self._session_dir = None
            else:
                self._session_dir = value if isinstance(value, Path) else Path(value)
