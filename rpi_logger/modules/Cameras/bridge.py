"""Camera runtime - Logger integration bridge.

Connects the simplified camera architecture to the Logger system.
Uses stub (codex) view integration pattern from Cameras_CSI.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional
import logging

_module_dir = Path(__file__).resolve().parent
if str(_module_dir) not in sys.path:
    sys.path.insert(0, str(_module_dir))

try:
    from rpi_logger.core.commands import StatusMessage
except ImportError:
    StatusMessage = None

try:
    from rpi_logger.core.logging_utils import get_module_logger
except ImportError:

    def get_module_logger(name):
        return logging.getLogger(name)


try:
    from rpi_logger.core.paths import USER_MODULE_CONFIG_DIR
except ImportError:
    USER_MODULE_CONFIG_DIR = Path.home() / ".config" / "rpi_logger"

try:
    from rpi_logger.modules.base.storage_utils import ensure_module_data_dir
except ImportError:
    ensure_module_data_dir = None

from .core import (
    CameraController,
    CameraState,
    Settings,
    Phase,
    RecordingPhase,
    settings_to_persistable,
    settings_from_persistable,
)
from .ui import CameraView

try:
    from vmc.runtime import ModuleRuntime, RuntimeContext
except Exception:
    ModuleRuntime = object
    RuntimeContext = Any

logger = get_module_logger(__name__)


class CamerasRuntime(ModuleRuntime):
    """Logger runtime for cameras.

    Integrates the camera controller with Logger's command system
    and stub (codex) view framework.
    """

    def __init__(self, ctx: RuntimeContext) -> None:
        """Initialize runtime.

        Args:
            ctx: Logger runtime context
        """
        self.ctx = ctx
        self.logger = (
            ctx.logger.getChild("Cameras")
            if hasattr(ctx, "logger") and ctx.logger
            else logger
        )
        self.module_dir = ctx.module_dir if hasattr(ctx, "module_dir") else _module_dir

        # Load preferences
        self._preferences = (
            getattr(ctx.model, "preferences", None) if hasattr(ctx, "model") else None
        )

        # Create controller with default settings, then restore from config
        self.controller = CameraController()
        self._restore_settings_from_config()

        # State tracking
        self._pending_device_ready: Optional[tuple[str, Optional[str]]] = None
        self._session_dir: Optional[Path] = None
        self._trial_number: int = 1
        self._auto_record: bool = False
        self._current_device_info: dict = {}

        # Create view with stub view from context
        self.view = CameraView(ctx.view, logger_instance=self.logger)

    @staticmethod
    def _parse_int(val: Any, default: int) -> int:
        if val is None:
            return default
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _parse_float(val: Any, default: float) -> float:
        if val is None:
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    def _restore_settings_from_config(self) -> None:
        """Restore settings from preferences on startup."""
        if not self._preferences:
            self.logger.debug("No preferences available, using default settings")
            return

        try:
            config = self._preferences.snapshot()
            restored = settings_from_persistable(config, Settings())
            self.controller._state.settings = restored
            self.logger.debug(
                "Restored camera settings: %dx%d @ %dfps, audio=%s",
                restored.resolution[0],
                restored.resolution[1],
                restored.frame_rate,
                restored.audio_enabled,
            )
        except Exception as e:
            self.logger.warning("Failed to restore camera settings: %s", e)

    def _detect_cli_audio_device(
        self,
        camera_device: int | str,
        audio_device_arg: Optional[str],
        audio_mode: str,
    ) -> dict:
        """Detect audio device for CLI-specified camera.

        Uses the camera backend's VID:PID matching to find the webcam's
        associated microphone, just like the DeviceSystem does.

        Args:
            camera_device: Camera device index or path
            audio_device_arg: Explicit audio device from --audio-device arg
            audio_mode: Audio mode from --audio arg (auto/on/off)

        Returns:
            Dict with has_audio, audio_device_index, audio_channels, supported_sample_rates
        """
        if audio_mode == "off":
            self.logger.info("Audio disabled via --audio=off")
            return {"has_audio": False}

        # If explicit audio device provided, use it
        if audio_device_arg is not None:
            try:
                audio_index = int(audio_device_arg)
                self.logger.debug("Using explicit audio device: %d", audio_index)
                try:
                    import sounddevice as sd
                    devices = sd.query_devices()
                    if 0 <= audio_index < len(devices):
                        dev = devices[audio_index]
                        if dev.get("max_input_channels", 0) > 0:
                            return {
                                "has_audio": True,
                                "audio_device_index": audio_index,
                                "audio_channels": dev.get("max_input_channels", 1),
                                "supported_sample_rates": (int(dev.get("default_samplerate", 48000)),),
                            }
                except ImportError:
                    pass
                # Fallback - trust the user's device index
                return {
                    "has_audio": True,
                    "audio_device_index": audio_index,
                    "audio_channels": 1,
                    "supported_sample_rates": (48000,),
                }
            except ValueError:
                self.logger.warning("Invalid audio device index: %s", audio_device_arg)

        # Auto-detect using camera backend's VID:PID matching
        if audio_mode in ("auto", "on"):
            try:
                camera_index = int(camera_device) if isinstance(camera_device, str) else camera_device
            except (ValueError, TypeError):
                camera_index = None

            if camera_index is not None:
                audio_info = self._discover_camera_audio_sibling(camera_index)
                if audio_info:
                    return audio_info

            # Fallback for "on" mode: use first input device
            if audio_mode == "on":
                try:
                    import sounddevice as sd
                    devices = sd.query_devices()
                    for idx, dev in enumerate(devices):
                        if dev.get("max_input_channels", 0) > 0:
                            self.logger.debug(
                                "Using first audio input (--audio=on): %s (index=%d)",
                                dev.get("name"), idx
                            )
                            return {
                                "has_audio": True,
                                "audio_device_index": idx,
                                "audio_channels": dev.get("max_input_channels", 1),
                                "supported_sample_rates": (int(dev.get("default_samplerate", 48000)),),
                            }
                except ImportError:
                    self.logger.warning("sounddevice not available")
                except Exception as e:
                    self.logger.warning("Audio fallback failed: %s", e)

        return {"has_audio": False}

    def _discover_camera_audio_sibling(self, camera_index: int) -> Optional[dict]:
        """Use camera backend to find the webcam's associated microphone.

        This uses VID:PID matching - the same method the DeviceSystem uses.

        Args:
            camera_index: OpenCV camera index

        Returns:
            Audio info dict or None if no audio sibling found
        """
        try:
            import sys
            if sys.platform == "win32" or "microsoft" in sys.version.lower():
                from .discovery.backends.windows import WindowsCameraBackend
                backend = WindowsCameraBackend()
            else:
                from .discovery.backends.linux import LinuxCameraBackend
                backend = LinuxCameraBackend()

            cameras = backend.discover_cameras(max_devices=camera_index + 1)

            for cam in cameras:
                if cam.camera_index == camera_index and cam.audio_sibling:
                    sibling = cam.audio_sibling
                    self.logger.debug(
                        "Found audio sibling via VID:PID matching: %s (index=%d)",
                        sibling.name, sibling.sounddevice_index
                    )
                    return {
                        "has_audio": True,
                        "audio_device_index": sibling.sounddevice_index,
                        "audio_channels": sibling.channels,
                        "supported_sample_rates": (int(sibling.sample_rate),),
                    }

            self.logger.debug("No audio sibling found for camera index %d", camera_index)
        except ImportError as e:
            self.logger.debug("Camera backend not available: %s", e)
        except Exception as e:
            self.logger.warning("Audio sibling discovery failed: %s", e)

        return None

    async def start(self) -> None:
        """Start the runtime."""
        self.logger.debug("=" * 60)
        self.logger.debug("CAMERAS RUNTIME STARTING")
        self.logger.debug("=" * 60)

        args = self.ctx.args
        self.logger.debug("LAUNCH PARAMETERS:")
        self.logger.debug("  device:       %s", getattr(args, "device", None))
        self.logger.debug("  audio:        %s", getattr(args, "audio", "auto"))
        self.logger.debug("  output_dir:   %s", getattr(args, "output_dir", None))
        self.logger.debug("  record:       %s", getattr(args, "record", False))
        self.logger.debug("=" * 60)

        self._auto_record = getattr(args, "record", False)
        if output_dir := getattr(args, "output_dir", None):
            self._session_dir = Path(output_dir)

        # Update audio setting from CLI
        audio_mode = getattr(args, "audio", "auto")
        if audio_mode == "off":
            settings = self.controller.state.settings
            self.controller._state.settings = Settings(
                resolution=settings.resolution,
                frame_rate=settings.frame_rate,
                preview_divisor=settings.preview_divisor,
                preview_scale=settings.preview_scale,
                audio_enabled=False,
                sample_rate=settings.sample_rate,
            )

        # Setup stub view
        if self.ctx.view:
            with contextlib.suppress(Exception):
                self.ctx.view.set_preview_title("Camera")
            if hasattr(self.ctx.view, "set_data_subdir"):
                self.ctx.view.set_data_subdir("Cameras")

        # Attach view to stub and connect callbacks
        self.view.attach()
        self.controller.subscribe(self.view.render)
        self.controller.set_preview_callback(self.view.push_frame)
        self.view.set_settings_callback(self._on_settings_changed)

        self.logger.info("Cameras runtime ready")
        if StatusMessage:
            StatusMessage.send("ready")

        # Handle CLI device argument
        device_arg = getattr(self.ctx.args, "device", None)
        if device_arg:
            self.logger.debug("Auto-assigning camera %s via CLI arg", device_arg)
            try:
                device = int(device_arg)
            except ValueError:
                device = device_arg

            # Detect audio device - check CLI arg first, then auto-detect
            audio_device_arg = getattr(self.ctx.args, "audio_device", None)
            audio_mode = getattr(self.ctx.args, "audio", "auto")

            audio_info = self._detect_cli_audio_device(
                device, audio_device_arg, audio_mode
            )

            device_info = {
                "device": device,
                "name": f"Camera ({device_arg})",
                "stable_id": str(device_arg),
                "has_audio": audio_info.get("has_audio", False),
                "audio_device_index": audio_info.get("audio_device_index"),
                "audio_channels": audio_info.get("audio_channels", 1),
                "supported_sample_rates": audio_info.get("supported_sample_rates", ()),
            }

            if audio_info.get("has_audio"):
                self.logger.debug(
                    "Audio device detected: index=%s, channels=%s",
                    audio_info.get("audio_device_index"),
                    audio_info.get("audio_channels"),
                )

            self._pending_device_ready = (str(device_arg), "cli_auto_assign")
            await self._start_camera(device, device_info)
        else:
            self.logger.debug("Waiting for assign_device command")

    async def shutdown(self) -> None:
        """Shutdown the runtime."""
        self.logger.info("Shutting down Cameras runtime")
        # Save current settings before shutdown
        self._save_settings(self.controller.state.settings)
        await self.controller.stop_streaming()

    async def cleanup(self) -> None:
        """Cleanup resources before view is destroyed."""
        # Mark view as shutting down to prevent UI updates to destroyed widgets
        self.view.mark_shutdown()

        # Clear preview callback to prevent frames being pushed to destroyed view
        self.controller.set_preview_callback(None)

        # Unsubscribe view from state updates
        self.controller.unsubscribe(self.view.render)

        # Ensure streaming is stopped (idempotent - may already be stopped by shutdown())
        if self.controller.state.phase != Phase.IDLE:
            await self.controller.stop_streaming()

    async def handle_command(self, command: Dict[str, Any]) -> bool:
        """Handle commands from Logger.

        Args:
            command: Command dictionary

        Returns:
            True if command was handled
        """
        action = (command.get("command") or "").lower()

        if action == "assign_device":
            return await self._handle_assign_device(command)

        if action == "unassign_device":
            await self.controller.stop_streaming()
            return True

        if action in {"start_recording", "record"}:
            return await self._handle_start_recording(command)

        if action in {"stop_recording", "stop"}:
            await self.controller.stop_recording()
            if StatusMessage:
                StatusMessage.send(
                    "recording_stopped",
                    {"frames": self.controller.state.metrics.frames_recorded},
                )
            return True

        if action == "set_audio":
            mode = command.get("mode", "auto")
            settings = self.controller.state.settings
            new_settings = Settings(
                resolution=settings.resolution,
                frame_rate=settings.frame_rate,
                preview_divisor=settings.preview_divisor,
                preview_scale=settings.preview_scale,
                audio_enabled=(mode != "off"),
                sample_rate=settings.sample_rate,
            )
            await self.controller.apply_settings(new_settings)
            return True

        if action == "start_streaming":
            if self._current_device_info:
                device = self._current_device_info.get("device")
                if device is not None:
                    await self.controller.start_streaming(
                        device, self._current_device_info
                    )
            return True

        if action == "stop_streaming":
            await self.controller.stop_streaming()
            return True

        if action == "shutdown":
            await self.shutdown()
            return True

        return False

    async def _handle_assign_device(self, command: Dict[str, Any]) -> bool:
        """Handle assign_device command.

        Uses device data directly from Logger's core DeviceSystem.
        """
        command_id = command.get("command_id")

        # Extract device identification
        camera_index = command.get("camera_index")
        camera_dev_path = command.get("camera_dev_path") or command.get("device_path")
        stable_id = (
            command.get("camera_stable_id")
            or command.get("stable_id")
            or command.get("device_id", "")
        )
        display_name = command.get("display_name") or f"Camera ({stable_id})"

        self.logger.debug(
            "assign_device: camera_index=%s, dev_path=%s, stable_id=%s",
            camera_index,
            camera_dev_path,
            stable_id,
        )

        # Acknowledge command
        if StatusMessage:
            device_id = stable_id or str(camera_index) or camera_dev_path or "unknown"
            StatusMessage.send(
                "device_ack", {"device_id": device_id}, command_id=command_id
            )

        # Determine device identifier
        if camera_index is not None:
            device = camera_index
        elif camera_dev_path:
            device = camera_dev_path
        else:
            self.logger.error("assign_device: no camera_index or camera_dev_path")
            if StatusMessage:
                StatusMessage.send(
                    "device_error",
                    {"error": "Missing camera_index or camera_dev_path"},
                    command_id=command_id,
                )
            return False

        self._pending_device_ready = (stable_id or str(device), command_id)

        # Extract audio info from command (pre-discovered by DeviceSystem)
        audio_index = command.get("camera_audio_index")
        audio_channels = command.get("camera_audio_channels")
        audio_sample_rate = command.get("camera_audio_sample_rate")

        has_audio = audio_index is not None
        if has_audio:
            self.logger.debug(
                "Audio device available: index=%s, channels=%s, rate=%s",
                audio_index,
                audio_channels,
                audio_sample_rate,
            )

        # Build device info
        device_info = {
            "device": device,
            "name": display_name,
            "stable_id": stable_id or str(device),
            "has_audio": has_audio,
            "audio_device_index": audio_index,
            "audio_channels": audio_channels or 1,
            "supported_sample_rates": (audio_sample_rate,) if audio_sample_rate else (),
        }

        await self._start_camera(device, device_info)
        return True

    async def _start_camera(self, device: int | str, device_info: dict) -> None:
        """Start camera with given device."""
        # If already streaming, just acknowledge - don't send error
        if self.controller.state.phase == Phase.STREAMING:
            self.logger.debug("Camera already streaming, ignoring duplicate assign")
            if self._pending_device_ready:
                device_id, command_id = self._pending_device_ready
                self._pending_device_ready = None
                if StatusMessage:
                    StatusMessage.send(
                        "device_ready", {"device_id": device_id}, command_id=command_id
                    )
            return

        self._current_device_info = device_info

        # Update state with audio availability
        self.controller._state.has_audio = device_info.get("has_audio", False)
        self.controller._state.device_name = device_info.get("name", str(device))

        # Update settings with audio device if available
        if device_info.get("audio_device_index") is not None:
            settings = self.controller.state.settings
            new_settings = Settings(
                resolution=settings.resolution,
                frame_rate=settings.frame_rate,
                preview_divisor=settings.preview_divisor,
                preview_scale=settings.preview_scale,
                audio_enabled=settings.audio_enabled,
                audio_device_index=device_info.get("audio_device_index"),
                sample_rate=device_info.get("supported_sample_rates", (48000,))[0]
                if device_info.get("supported_sample_rates")
                else settings.sample_rate,
                audio_channels=device_info.get("audio_channels", 1),
            )
            self.controller._state.settings = new_settings

        # Start streaming
        success = await self.controller.start_streaming(device, device_info)

        # Send status based on result
        if success and self._pending_device_ready:
            device_id, command_id = self._pending_device_ready
            self._pending_device_ready = None
            if StatusMessage:
                StatusMessage.send(
                    "device_ready", {"device_id": device_id}, command_id=command_id
                )

            # Auto-start recording if requested
            if self._auto_record and self._session_dir:
                self.logger.info("Auto-starting recording")
                await asyncio.sleep(1.0)
                # Create proper directory structure
                if ensure_module_data_dir:
                    cameras_dir = ensure_module_data_dir(self._session_dir, "Cameras")
                else:
                    cameras_dir = self._session_dir / "Cameras"
                    cameras_dir.mkdir(parents=True, exist_ok=True)
                stable_id = self._current_device_info.get("stable_id", "camera")
                device_subdir = self._sanitize_stable_id(stable_id)
                output_dir = cameras_dir / device_subdir
                output_dir.mkdir(parents=True, exist_ok=True)
                await self.controller.start_recording(
                    output_dir, self._trial_number, cameras_dir=cameras_dir
                )
                self._trial_number += 1

        elif not success and self._pending_device_ready:
            device_id, command_id = self._pending_device_ready
            self._pending_device_ready = None
            if StatusMessage:
                StatusMessage.send(
                    "device_error",
                    {"device_id": device_id, "error": self.controller.state.error},
                    command_id=command_id,
                )

    def _sanitize_stable_id(self, stable_id: str) -> str:
        """Sanitize stable_id for use as directory name."""
        # Replace special characters with underscores
        safe = stable_id.replace(":", "_").replace("/", "_").replace("\\", "_")
        safe = safe.replace("(", "").replace(")", "").replace(" ", "_")
        # Remove consecutive underscores
        while "__" in safe:
            safe = safe.replace("__", "_")
        return safe.strip("_").lower() or "camera"

    async def _handle_start_recording(self, command: Dict[str, Any]) -> bool:
        """Handle start_recording command."""
        state = self.controller.state

        # Ensure streaming before recording
        if state.phase != Phase.STREAMING:
            if self._current_device_info:
                device = self._current_device_info.get("device")
                if device is not None:
                    await self.controller.start_streaming(
                        device, self._current_device_info
                    )
                    await asyncio.sleep(0.5)

        # Get session directory
        session_dir = command.get("session_dir")
        if session_dir:
            self._session_dir = Path(session_dir)
        elif not self._session_dir:
            self._session_dir = Path(tempfile.gettempdir()) / "logger_cameras"

        trial = command.get("trial_number", self._trial_number)
        trial_label = command.get("trial_label", "")

        # Create proper directory structure: session_dir/Cameras/device_id/
        if ensure_module_data_dir:
            cameras_dir = ensure_module_data_dir(self._session_dir, "Cameras")
        else:
            cameras_dir = self._session_dir / "Cameras"
            cameras_dir.mkdir(parents=True, exist_ok=True)

        # Create device-specific subdirectory
        stable_id = self._current_device_info.get("stable_id", "camera")
        device_subdir = self._sanitize_stable_id(stable_id)
        output_dir = cameras_dir / device_subdir
        output_dir.mkdir(parents=True, exist_ok=True)

        success = await self.controller.start_recording(
            output_dir, trial, trial_label=trial_label, cameras_dir=cameras_dir
        )
        if success:
            self._trial_number = trial + 1
            if StatusMessage:
                StatusMessage.send(
                    "recording_started",
                    {
                        "session_dir": str(self._session_dir),
                        "trial": trial,
                    },
                )

        return success

    def _on_settings_changed(self, settings: Settings) -> None:
        """Handle settings changes from UI.

        Args:
            settings: New settings from the settings dialog
        """
        old_settings = self.controller._state.settings

        self.logger.info("Settings changed from UI: res=%dx%d, fps=%d, audio=%s",
                         settings.resolution[0], settings.resolution[1],
                         settings.frame_rate, settings.audio_enabled)

        # Check if we need to restart streaming
        needs_restart = (
            self.controller.state.phase == Phase.STREAMING and (
                old_settings.resolution != settings.resolution or
                old_settings.audio_enabled != settings.audio_enabled or
                old_settings.sample_rate != settings.sample_rate or
                old_settings.audio_channels != settings.audio_channels
            )
        )

        # Apply to controller and notify subscribers
        self.controller._state.settings = settings
        self.controller._notify()
        self._save_settings(settings)

        # Restart streaming if needed (resolution or audio changed)
        if needs_restart:
            self.logger.debug("Settings require stream restart, restarting...")
            asyncio.create_task(self._restart_streaming())

    async def _restart_streaming(self) -> None:
        """Restart streaming with current settings."""
        if not self._current_device_info:
            self.logger.warning("Cannot restart streaming: no device info")
            return

        device = self._current_device_info.get("device")
        if device is None:
            self.logger.warning("Cannot restart streaming: no device")
            return

        self.logger.debug("Stopping stream for restart...")
        await self.controller.stop_streaming()

        # Brief pause to let hardware settle
        await asyncio.sleep(0.2)

        # Re-detect audio if audio is now enabled but device_info lacks audio
        settings = self.controller.state.settings
        if settings.audio_enabled and not self._current_device_info.get("has_audio"):
            self.logger.debug("Audio enabled, re-detecting audio device...")
            # Only re-detect if device is an integer camera index
            if isinstance(device, int):
                audio_info = self._discover_camera_audio_sibling(device)
                if audio_info and audio_info.get("has_audio"):
                    self._current_device_info.update(audio_info)
                    self.logger.debug(
                        "Audio device found: index=%s, channels=%s",
                        audio_info.get("audio_device_index"),
                        audio_info.get("audio_channels"),
                    )

        self.logger.debug("Restarting stream with new settings...")
        await self._start_camera(device, self._current_device_info)

    def _save_settings(self, settings: Settings) -> None:
        """Save settings to preferences."""
        if not self._preferences:
            return

        try:
            updates = settings_to_persistable(settings)
            self._preferences.write_sync(updates)
            self.logger.debug("Saved camera settings to config")
        except Exception as e:
            self.logger.warning("Failed to save camera settings: %s", e)


# Backwards compatibility alias
USBCamerasRuntime = CamerasRuntime


def factory(ctx: RuntimeContext) -> CamerasRuntime:
    """Factory function for Logger integration."""
    return CamerasRuntime(ctx)
