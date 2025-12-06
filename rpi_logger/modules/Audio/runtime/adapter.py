"""Runtime adapter that wires the supervisor to :class:`AudioApp`.

Device discovery is centralized in the main logger. This runtime waits for
device assignments via assign_device commands.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from rpi_logger.core.commands import StatusMessage

from vmc import ModuleRuntime, RuntimeContext

from ..app import AudioApp
from ..config import AudioSettings
from ..domain import AudioDeviceInfo


class AudioRuntime(ModuleRuntime):
    """Adapter used by the supervisor.

    Device discovery is handled by the main logger. This runtime receives
    device assignments via assign_device commands.
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

    async def start(self) -> None:
        await self.app.start()

    async def shutdown(self) -> None:
        await self.app.shutdown()

    # ------------------------------------------------------------------
    # Device Assignment (from main logger)
    # ------------------------------------------------------------------

    async def assign_device(
        self,
        device_id: str,
        device_type: str,
        port: Optional[str],
        baudrate: int,
        is_wireless: bool = False,
        *,
        sounddevice_index: Optional[int] = None,
        audio_channels: Optional[int] = None,
        audio_sample_rate: Optional[float] = None,
    ) -> bool:
        """
        Assign an audio device to this module (called by main logger).

        Args:
            device_id: Unique device identifier (e.g., "audio_0")
            device_type: Device type string (e.g., "USB_Microphone")
            port: Not used for audio devices
            baudrate: Not used for audio devices
            is_wireless: Not used for audio devices
            sounddevice_index: The sounddevice index for this device
            audio_channels: Number of input channels
            audio_sample_rate: Sample rate for the device

        Returns:
            True if device was successfully assigned
        """
        if sounddevice_index is None:
            self.logger.error("Cannot assign audio device without sounddevice_index")
            return False

        self.logger.info(
            "Assigning audio device: id=%s, type=%s, index=%d, channels=%s, rate=%s",
            device_id, device_type, sounddevice_index, audio_channels, audio_sample_rate
        )

        try:
            # Create AudioDeviceInfo from the assignment
            device_info = AudioDeviceInfo(
                device_id=sounddevice_index,
                name=device_id,  # Use device_id as name, will be updated
                channels=audio_channels or 1,
                sample_rate=audio_sample_rate or self.settings.sample_rate,
            )

            # Add to app's device state and enable it
            self.app.state.set_device(sounddevice_index, device_info)
            await self.app.toggle_device(sounddevice_index, enabled=True)

            self.logger.info("Audio device %s assigned and enabled (index=%d)", device_id, sounddevice_index)
            return True

        except Exception as e:
            self.logger.error("Failed to assign audio device %s: %s", device_id, e, exc_info=True)
            return False

    async def unassign_device(self, device_id: str) -> None:
        """
        Unassign an audio device from this module.

        Args:
            device_id: The device to unassign (e.g., "audio_0")
        """
        self.logger.info("Unassigning audio device: %s", device_id)

        try:
            # Extract sounddevice index from device_id (format: "audio_N")
            if device_id.startswith("audio_"):
                try:
                    sounddevice_index = int(device_id.split("_")[1])
                except (IndexError, ValueError):
                    self.logger.warning("Could not parse device_id: %s", device_id)
                    return
            else:
                self.logger.warning("Unknown device_id format: %s", device_id)
                return

            # Disable and remove the device
            await self.app.toggle_device(sounddevice_index, enabled=False)
            self.app.state.remove_device(sounddevice_index)

            self.logger.info("Audio device %s unassigned", device_id)

        except Exception as e:
            self.logger.error("Error unassigning audio device %s: %s", device_id, e, exc_info=True)

    # ------------------------------------------------------------------
    # Command and action handling
    # ------------------------------------------------------------------

    async def handle_command(self, command: Dict[str, Any]) -> bool:
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
            )

        if action == "unassign_device":
            await self.unassign_device(command.get("device_id", ""))
            return True

        return await self.app.handle_command(command)

    async def handle_user_action(self, action: str, **kwargs: Any) -> bool:
        return await self.app.handle_user_action(action, **kwargs)

    async def healthcheck(self) -> bool:
        return await self.app.healthcheck()
