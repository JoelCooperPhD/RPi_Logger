"""GPS Module Runtime - coordinates handlers for multi-instance support.

This runtime manages GPS handlers and provides the bridge between
the GPS core functionality and the VMC framework.

Device discovery is handled by the main logger. This runtime receives
device assignments via assign_device commands.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Deque, Dict, Optional

# Map rendering throttle (seconds) - limits UI updates, not data logging
_MAP_RENDER_THROTTLE = 0.2  # 200ms = max 5 renders per second

from vmc import ModuleRuntime, RuntimeContext
from vmc.runtime_helpers import BackgroundTaskManager
from rpi_logger.modules.base.storage_utils import ensure_module_data_dir
from rpi_logger.core.commands import StatusMessage, StatusType
from rpi_logger.core.logging_utils import ensure_structured_logger

from gps_core.constants import DEFAULT_NMEA_HISTORY
from gps_core.handlers import GPSHandler
from gps_core.transports import SerialGPSTransport
from gps_core.parsers.nmea_types import GPSFixSnapshot
from gps_core.interfaces.gui import GPSMapRenderer
from rpi_logger.modules.GPS.preferences import GPSPreferences
from rpi_logger.modules.GPS.config import GPSConfig


class GPSModuleRuntime(ModuleRuntime):
    """VMC-compatible runtime for GPS module.

    Manages GPS handlers and coordinates with view/model.
    Devices are assigned by main logger via assign_device command.

    Supports multi-instance: multiple GPS receivers can be connected
    simultaneously, each with its own handler.
    """

    def __init__(self, context: RuntimeContext) -> None:
        self.args = context.args
        self.module_dir = context.module_dir

        base_logger = ensure_structured_logger(
            getattr(context, "logger", None),
            fallback_name="GPSRuntime"
        )
        self.logger = base_logger.getChild("Runtime")

        self.model = context.model
        self.controller = context.controller
        self.view = context.view
        self.display_name = context.display_name

        # Configuration - use typed config via preferences_scope
        scope_fn = getattr(context.model, "preferences_scope", None)
        pref_scope = scope_fn("gps") if callable(scope_fn) else None
        self.preferences = GPSPreferences(pref_scope)

        config_path = getattr(self.args, "config_path", None)
        self.config_path = Path(config_path) if config_path else (self.module_dir / "config.txt" if self.module_dir else Path("config.txt"))
        self.typed_config = GPSConfig.from_preferences(pref_scope, self.args) if pref_scope else GPSConfig()

        # Keep dict config for backward compatibility during migration
        self.config: Dict[str, Any] = self.typed_config.to_dict()

        # Session management
        self.session_prefix = str(getattr(self.args, "session_prefix", self.config.get("session_prefix", "gps")))
        self.output_root: Path = Path(getattr(self.args, "output_dir", Path("gps_data")))
        self.session_dir: Path = self.output_root
        self.module_subdir: str = "GPS"
        self.module_data_dir: Path = self.session_dir

        # Multi-instance device management
        self.handlers: Dict[str, GPSHandler] = {}
        self._transports: Dict[str, SerialGPSTransport] = {}
        self._map_renderers: Dict[str, GPSMapRenderer] = {}

        # Background tasks
        self._task_manager = BackgroundTaskManager(name="GPSRuntimeTasks", logger=self.logger)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._shutdown = asyncio.Event()

        # Recording state
        self._recording_active = False
        self._active_trial_number: int = 1
        self._suppress_recording_event = False
        self._suppress_session_event = False

        # NMEA sentence history (for UI display)
        history_limit = max(1, int(getattr(self.args, "nmea_history", DEFAULT_NMEA_HISTORY)))
        self._recent_sentences: Deque[str] = deque(maxlen=history_limit)

        # Map rendering state
        self._last_render_time: Dict[str, float] = {}  # device_id -> last render timestamp
        initial_zoom = float(getattr(self.args, "zoom", self.config.get("zoom", 13.0)))
        initial_lat = float(getattr(self.args, "center_lat", self.config.get("center_lat", 40.7608)))
        initial_lon = float(getattr(self.args, "center_lon", self.config.get("center_lon", -111.8910)))
        self._current_zoom = self._clamp_zoom(initial_zoom)
        self._current_center = (initial_lat, initial_lon)

        # Offline tiles database
        self._offline_db_path = self._resolve_offline_db_path()

        # UI state
        self._map_widget = None
        self._controls_overlay = None
        self._telemetry_vars: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Lifecycle hooks (VMC ModuleRuntime interface)

    async def start(self) -> None:
        """Start the runtime - bind to view/model and wait for device assignments."""
        self.logger.info("Starting GPS runtime (waiting for device assignments)")
        self._loop = asyncio.get_running_loop()

        if self.view:
            bind_runtime = getattr(self.view, "bind_runtime", None)
            if callable(bind_runtime):
                bind_runtime(self)

        await self._ensure_session_dir(self.model.session_dir)

        self.model.subscribe(self._on_model_change)

        self.logger.info("GPS runtime ready; waiting for device assignments")

        # Notify logger that module is ready for commands
        StatusMessage.send("ready")

    async def shutdown(self) -> None:
        """Shutdown the runtime - stop recording and disconnect all devices."""
        if self._shutdown.is_set():
            return

        self._shutdown.set()
        self.logger.info("Shutting down GPS runtime")

        # Stop recording
        await self._stop_recording()

        # Disconnect all devices
        for device_id in list(self.handlers.keys()):
            await self.unassign_device(device_id)

        await self._task_manager.shutdown()
        self.logger.info("GPS runtime shutdown complete")

    async def cleanup(self) -> None:
        """Final cleanup after shutdown."""
        pass

    # ------------------------------------------------------------------
    # Command handling (VMC ModuleRuntime interface)

    async def handle_command(self, command: Dict[str, Any]) -> bool:
        """Handle VMC commands."""
        action = (command.get("command") or "").lower()

        if action == "assign_device":
            return await self.assign_device(
                device_id=command.get("device_id", ""),
                port=command.get("port", ""),
                baudrate=command.get("baudrate", 9600),
                command_id=command.get("command_id"),
                display_name=command.get("display_name", ""),
            )

        if action == "unassign_device":
            await self.unassign_device(command.get("device_id", ""))
            return True

        if action == "unassign_all_devices":
            command_id = command.get("command_id")
            self.logger.info("Unassigning all devices before shutdown (command_id=%s)", command_id)

            device_ids = list(self.handlers.keys())
            for device_id in device_ids:
                await self.unassign_device(device_id)

            # Send ACK to confirm port release
            StatusMessage.send(
                StatusType.DEVICE_UNASSIGNED,
                {
                    "device_ids": device_ids,
                    "port_released": True,
                },
                command_id=command_id,
            )
            return True

        if action == "start_recording":
            self._active_trial_number = self._coerce_trial_number(command.get("trial_number"))
            session_dir = command.get("session_dir")
            if session_dir:
                await self._ensure_session_dir(Path(session_dir), update_model=False)
            await self._start_recording()
            return True

        if action == "stop_recording":
            await self._stop_recording()
            return True

        if action == "show_window":
            self._show_window()
            return True

        if action == "hide_window":
            self._hide_window()
            return True

        return False

    async def handle_user_action(self, action: str, **kwargs: Any) -> bool:
        """Handle user actions from the view."""
        return False

    # ------------------------------------------------------------------
    # Model observation

    def _on_model_change(self, prop: str, value: Any) -> None:
        """Handle model property changes."""
        if prop == "recording":
            if self._suppress_recording_event:
                return
            if self._loop:
                self._loop.create_task(self._apply_recording_state(bool(value)))
        elif prop == "session_dir":
            if self._suppress_session_event:
                return
            if not value:
                return
            path = Path(value)
            if self._loop:
                self._loop.create_task(self._ensure_session_dir(path, update_model=False))

    async def _apply_recording_state(self, active: bool) -> None:
        """Apply recording state from model changes."""
        if active:
            await self._start_recording()
        else:
            await self._stop_recording()

    # ------------------------------------------------------------------
    # Device Assignment

    async def assign_device(
        self,
        device_id: str,
        port: str,
        baudrate: int,
        command_id: str | None = None,
        display_name: str = "",
    ) -> bool:
        """Assign a GPS device to this module.

        Args:
            device_id: Unique device identifier
            port: Serial port path
            baudrate: Serial baudrate
            command_id: Correlation ID for acknowledgment tracking
            display_name: Display name for the device

        Returns:
            True if device was successfully assigned
        """
        if device_id in self.handlers:
            self.logger.warning("Device %s already assigned", device_id)
            return True

        self.logger.info(
            "Assigning GPS device: id=%s, port=%s, baudrate=%d, display_name=%r",
            device_id, port, baudrate, display_name
        )

        try:
            # Create transport
            transport = SerialGPSTransport(port, baudrate)
            if not await transport.connect():
                error = transport.last_error or f"Failed to connect on {port}"
                self.logger.error("Failed to connect to GPS %s: %s", device_id, error)
                StatusMessage.send("device_error", {"device_id": device_id, "error": error}, command_id=command_id)
                return False

            self._transports[device_id] = transport

            # Create handler
            handler = GPSHandler(device_id, self.module_data_dir, transport)
            handler.data_callback = self._on_device_data

            # Start handler
            await handler.start()
            self.handlers[device_id] = handler

            # Create map renderer for this device
            if self._offline_db_path.exists():
                renderer = GPSMapRenderer(self._offline_db_path)
                renderer.set_center(*self._current_center)
                renderer.set_zoom(self._current_zoom)
                self._map_renderers[device_id] = renderer

            self.logger.info("GPS device %s assigned and started", device_id)

            # Update window title
            if self.view and display_name:
                try:
                    self.view.set_window_title(display_name)
                except Exception as e:
                    self.logger.warning("Failed to set window title: %s", e)

            # Notify view
            if self.view:
                on_connected = getattr(self.view, "on_device_connected", None)
                if callable(on_connected):
                    on_connected(device_id, port)

            # Send acknowledgement
            StatusMessage.send("device_ready", {"device_id": device_id}, command_id=command_id)

            # If recording is active, start recording on new device
            if self._recording_active:
                handler.start_recording(self._active_trial_number)

            return True

        except Exception as e:
            self.logger.error("Failed to assign GPS device %s: %s", device_id, e, exc_info=True)
            # Clean up on failure
            if device_id in self._transports:
                transport = self._transports.pop(device_id)
                await transport.disconnect()
            StatusMessage.send("device_error", {"device_id": device_id, "error": str(e)}, command_id=command_id)
            return False

    async def unassign_device(self, device_id: str) -> None:
        """Unassign a GPS device from this module.

        Args:
            device_id: The device to unassign
        """
        if device_id not in self.handlers:
            self.logger.debug("Device %s not assigned", device_id)
            return

        self.logger.info("Unassigning GPS device: %s", device_id)

        try:
            handler = self.handlers.pop(device_id)
            await handler.stop()

            # Clean up transport
            if device_id in self._transports:
                transport = self._transports.pop(device_id)
                await transport.disconnect()

            # Clean up map renderer
            self._map_renderers.pop(device_id, None)

            # Notify view
            if self.view:
                on_disconnected = getattr(self.view, "on_device_disconnected", None)
                if callable(on_disconnected):
                    on_disconnected(device_id)

            self.logger.info("GPS device %s unassigned", device_id)

        except Exception as e:
            self.logger.error("Error unassigning GPS device %s: %s", device_id, e, exc_info=True)

    # ------------------------------------------------------------------
    # Recording control

    async def _start_recording(self) -> None:
        """Start recording on all connected devices."""
        if self._recording_active:
            return

        if not self.handlers:
            self.logger.warning("Cannot start recording - no GPS devices connected")
            return

        for device_id, handler in self.handlers.items():
            result = await asyncio.to_thread(handler.start_recording, self._active_trial_number)
            if result:
                self.logger.info("Started recording on %s", device_id)
            else:
                self.logger.error("Failed to start recording on %s", device_id)

        self._recording_active = True

        if self.view:
            update_state = getattr(self.view, "update_recording_state", None)
            if callable(update_state):
                update_state()
        StatusMessage.send(StatusType.RECORDING_STARTED, {
            "device_ids": list(self.handlers.keys()),
            "trial_number": self._active_trial_number,
            "session_dir": str(self.module_data_dir) if self.module_data_dir else None,
        })

    async def _stop_recording(self) -> None:
        """Stop recording on all connected devices."""
        if not self._recording_active:
            return

        for device_id, handler in self.handlers.items():
            await asyncio.to_thread(handler.stop_recording)
            self.logger.info("Stopped recording on %s", device_id)

        self._recording_active = False

        if self.view:
            update_state = getattr(self.view, "update_recording_state", None)
            if callable(update_state):
                update_state()
        StatusMessage.send(StatusType.RECORDING_STOPPED, {
            "device_ids": list(self.handlers.keys()),
            "trial_number": self._active_trial_number,
            "session_dir": str(self.module_data_dir) if self.module_data_dir else None,
        })

    # ------------------------------------------------------------------
    # Data callbacks

    async def _on_device_data(
        self,
        device_id: str,
        fix: GPSFixSnapshot,
        update: Dict[str, Any],
    ) -> None:
        """Handle data from a GPS handler.

        Args:
            device_id: Device that produced the data
            fix: Current GPS fix
            update: Dictionary of updated values
        """
        # Update map center if we have a valid position
        if fix.fix_valid and fix.latitude is not None and fix.longitude is not None:
            self._current_center = (fix.latitude, fix.longitude)

            # Update trajectory
            renderer = self._map_renderers.get(device_id)
            if renderer:
                renderer.add_position_to_trajectory(fix.latitude, fix.longitude)
                renderer.set_center(fix.latitude, fix.longitude)

        # Update NMEA history
        raw_sentence = update.get("raw_sentence", "")
        if raw_sentence:
            timestamp = datetime.now().strftime("%H:%M:%S")
            self._recent_sentences.append(f"[{timestamp}] {raw_sentence}")

        # Render map and notify view (throttled to reduce CPU)
        if self.view:
            on_data = getattr(self.view, "on_gps_data", None)
            if callable(on_data):
                pil_image = None
                info_str = ""
                renderer = self._map_renderers.get(device_id)
                if renderer:
                    current_time = time.monotonic()
                    last_render = self._last_render_time.get(device_id, 0.0)
                    if current_time - last_render >= _MAP_RENDER_THROTTLE:
                        try:
                            pil_image, info_str = renderer.render(fix)
                            self._last_render_time[device_id] = current_time
                        except Exception as e:
                            self.logger.warning("Map render failed: %s", e)
                on_data(device_id, fix, pil_image, info_str)

    # ------------------------------------------------------------------
    # Session helpers

    async def _ensure_session_dir(self, new_dir: Optional[Path], update_model: bool = True) -> None:
        """Ensure session directory exists and update handlers."""
        if new_dir is None:
            self.output_root.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.session_dir = self.output_root / f"{self.session_prefix}_{timestamp}"
        else:
            self.session_dir = Path(new_dir)

        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.module_data_dir = ensure_module_data_dir(self.session_dir, self.module_subdir)

        # Update all handler output directories
        for handler in self.handlers.values():
            handler.update_output_dir(self.module_data_dir)

        # Sync to model if requested
        if update_model:
            self._suppress_session_event = True
            self.model.session_dir = self.session_dir
            self._suppress_session_event = False

    # ------------------------------------------------------------------
    # GUI helpers

    def get_current_fix(self, device_id: Optional[str] = None) -> Optional[GPSFixSnapshot]:
        """Get current GPS fix for a device.

        Args:
            device_id: Device ID, or None for first available device

        Returns:
            Current GPS fix or None
        """
        if device_id:
            handler = self.handlers.get(device_id)
            return handler.fix if handler else None

        # Return first handler's fix
        for handler in self.handlers.values():
            return handler.fix
        return None

    def get_map_renderer(self, device_id: Optional[str] = None) -> Optional[GPSMapRenderer]:
        """Get map renderer for a device.

        Args:
            device_id: Device ID, or None for first available

        Returns:
            Map renderer or None
        """
        if device_id:
            return self._map_renderers.get(device_id)

        # Return first available
        for renderer in self._map_renderers.values():
            return renderer
        return None

    @property
    def recording(self) -> bool:
        """Whether recording is active."""
        return self._recording_active

    # ------------------------------------------------------------------
    # Window visibility

    def _show_window(self) -> None:
        """Show the GPS window."""
        if self.view and hasattr(self.view, "show_window"):
            self.view.show_window()
            self.logger.debug("GPS window shown")

    def _hide_window(self) -> None:
        """Hide the GPS window."""
        if self.view and hasattr(self.view, "hide_window"):
            self.view.hide_window()
            self.logger.debug("GPS window hidden")

    # ------------------------------------------------------------------
    # Utility methods

    def _clamp_zoom(self, value: float) -> float:
        """Clamp zoom level to valid range."""
        from gps_core.constants import MIN_ZOOM_LEVEL, MAX_ZOOM_LEVEL
        return max(MIN_ZOOM_LEVEL, min(MAX_ZOOM_LEVEL, float(value)))

    def _resolve_offline_db_path(self) -> Path:
        """Resolve the offline tiles database path."""
        # Check args first
        arg_db = getattr(self.args, "offline_db", None)
        if arg_db:
            path = Path(arg_db)
            if path.is_absolute() and path.exists():
                return path
            # Try relative to module dir
            module_path = self.module_dir / path
            if module_path.exists():
                return module_path

        # Check config
        config_db = self.config.get("offline_db", "offline_tiles.db")
        if config_db:
            path = self.module_dir / config_db
            if path.exists():
                return path

        # Default
        return self.module_dir / "offline_tiles.db"

    def _coerce_trial_number(self, value: Any) -> int:
        """Coerce a value to a valid trial number."""
        try:
            candidate = int(value)
        except (TypeError, ValueError):
            candidate = getattr(self.model, "trial_number", None)
            try:
                candidate = int(candidate) if candidate is not None else 0
            except (TypeError, ValueError):
                candidate = 0
        if candidate <= 0:
            candidate = 1
        return candidate
