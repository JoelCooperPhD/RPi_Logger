"""Runtime adapter that wires the supervisor to :class:`AudioApp`.

Device discovery is centralized in the main logger. This runtime waits for
a single device assignment via assign_device commands.
"""

from __future__ import annotations

from typing import Any

from vmc import ModuleRuntime, RuntimeContext

from rpi_logger.core.commands import StatusMessage

from ..app import AudioApp
from ..config import AudioSettings
from ..domain import AudioDeviceInfo


class AudioRuntime(ModuleRuntime):
    """Adapter used by the supervisor.

    Device discovery is handled by the main logger. This runtime receives
    a single device assignment via assign_device commands.
    """

    def __init__(self, context: RuntimeContext) -> None:
        self.context = context
        self.logger = context.logger.getChild("Runtime")
        prefs = getattr(context.model, "preferences_scope", None)
        if callable(prefs):
            audio_prefs = prefs("audio")
            self.settings = AudioSettings.from_preferences(audio_prefs, context.args)
        else:
            self.settings = AudioSettings.from_args(context.args)
        self.app = AudioApp(
            context,
            self.settings,
            status_callback=StatusMessage.send,
        )
        self._current_device_id: str | None = None

    async def start(self) -> None:
        await self.app.start()
        # Notify logger that module is ready for commands
        StatusMessage.send("ready")

    async def shutdown(self) -> None:
        await self.app.shutdown()

    # ------------------------------------------------------------------
    # Device Assignment (from main logger)
    # ------------------------------------------------------------------

    async def assign_device(
        self,
        device_id: str,
        device_type: str,
        port: str | None,
        baudrate: int,
        is_wireless: bool = False,
        *,
        sounddevice_index: int | None = None,
        audio_channels: int | None = None,
        audio_sample_rate: float | None = None,
        display_name: str | None = None,
        command_id: str | None = None,
    ) -> bool:
        """
        Assign an audio device to this module (called by main logger).

        Replaces any existing device - only one device at a time is supported.

        Args:
            device_id: Unique device identifier (e.g., "audio_0")
            device_type: Device type string (e.g., "USB_Microphone")
            port: Not used for audio devices
            baudrate: Not used for audio devices
            is_wireless: Not used for audio devices
            sounddevice_index: The sounddevice index for this device
            audio_channels: Number of input channels
            audio_sample_rate: Sample rate for the device
            display_name: Human-readable device name (e.g., "HD Pro Webcam C920: USB Audio")
            command_id: Correlation ID for acknowledgment tracking

        Returns:
            True if device was successfully assigned
        """
        if sounddevice_index is None:
            self.logger.error("Cannot assign audio device without sounddevice_index")
            StatusMessage.send("device_error", {
                "device_id": device_id,
                "error": "Missing sounddevice_index",
            }, command_id=command_id)
            return False

        self.logger.info(
            "Assigning audio device: id=%s, type=%s, index=%d, channels=%s, rate=%s, cmd_id=%s",
            device_id, device_type, sounddevice_index, audio_channels, audio_sample_rate, command_id
        )

        # If device already assigned, unassign first
        if self.app.state.device is not None:
            self.logger.info("Replacing existing device with new assignment")
            await self._unassign_current_device()

        try:
            # Create AudioDeviceInfo from the assignment
            device_name = display_name or device_id
            device_info = AudioDeviceInfo(
                device_id=sounddevice_index,
                name=device_name,
                channels=audio_channels or 1,
                sample_rate=audio_sample_rate or self.settings.sample_rate,
            )

            # Enable the device (start audio stream)
            success = await self.app.enable_device(device_info)
            if not success:
                self.logger.error("Failed to enable audio device %s: stream failed to start", device_id)
                StatusMessage.send("device_error", {
                    "device_id": device_id,
                    "error": "Failed to start audio stream",
                }, command_id=command_id)
                return False

            self._current_device_id = device_id

            # Update window title: Audio(USB):device_name
            if hasattr(self.context, 'view') and self.context.view:
                short_name = device_name
                # Truncate long device names
                if len(short_name) > 20:
                    short_name = short_name[:17] + "..."
                title = f"Audio(USB):{short_name}"
                try:
                    self.context.view.set_window_title(title)
                except Exception:
                    pass

            self.logger.info("Audio device %s assigned and enabled (index=%d)", device_id, sounddevice_index)

            # Send acknowledgement to logger that device is ready
            StatusMessage.send("device_ready", {"device_id": device_id}, command_id=command_id)

            return True

        except Exception as e:
            self.logger.error("Failed to assign audio device %s: %s", device_id, e, exc_info=True)
            await self.app.disable_device()
            StatusMessage.send("device_error", {
                "device_id": device_id,
                "error": str(e),
            }, command_id=command_id)
            return False

    async def unassign_device(self, device_id: str) -> None:
        """
        Unassign the audio device from this module.

        Args:
            device_id: The device to unassign (e.g., "audio_0")
        """
        self.logger.info("Unassigning audio device: %s", device_id)
        await self._unassign_current_device()

    async def _unassign_current_device(self) -> None:
        """Internal helper to unassign current device."""
        if self.app.state.device is None:
            return

        try:
            await self.app.disable_device()
            self._current_device_id = None
            self.logger.info("Audio device unassigned")
        except Exception as e:
            self.logger.error("Error unassigning audio device: %s", e, exc_info=True)

    # ------------------------------------------------------------------
    # Command and action handling
    # ------------------------------------------------------------------

    async def handle_command(self, command: dict[str, Any]) -> bool:
        action = (command.get("command") or "").lower()

        if action == "assign_device":
            return await self.assign_device(
                device_id=command.get("device_id", ""),
                device_type=command.get("device_type", ""),
                port=command.get("port"),
                baudrate=command.get("baudrate", 0),
                is_wireless=command.get("is_wireless", False),
                sounddevice_index=command.get("sounddevice_index"),
                audio_channels=command.get("audio_channels"),
                audio_sample_rate=command.get("audio_sample_rate"),
                display_name=command.get("display_name"),
                command_id=command.get("command_id"),
            )

        if action == "unassign_device":
            await self.unassign_device(command.get("device_id", ""))
            return True

        return await self.app.handle_command(command)

    async def handle_user_action(self, action: str, **kwargs: Any) -> bool:
        return await self.app.handle_user_action(action, **kwargs)

    async def healthcheck(self) -> bool:
        return await self.app.healthcheck()
