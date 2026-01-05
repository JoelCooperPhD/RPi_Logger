"""Runtime adapter for AudioApp."""

from __future__ import annotations

from typing import Any

from vmc import ModuleRuntime, RuntimeContext

from rpi_logger.core.commands import StatusMessage

from ..app import AudioApp
from ..config import AudioSettings
from ..domain import AudioDeviceInfo


class AudioRuntime(ModuleRuntime):
    """Runtime adapter for supervisor."""
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
        StatusMessage.send("ready")

    async def shutdown(self) -> None:
        await self.app.shutdown()

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
        if sounddevice_index is None:
            self.logger.error("Cannot assign audio device without sounddevice_index")
            StatusMessage.send("device_error", {
                "device_id": device_id,
                "error": "Missing sounddevice_index",
            }, command_id=command_id)
            return False

        self.logger.info("Assigning device: %s (index=%d, ch=%s, rate=%s)", device_id, sounddevice_index, audio_channels, audio_sample_rate)
        if self.app.state.device is not None:
            self.logger.info("Replacing existing device with new assignment")
            await self._unassign_current_device()
        try:
            device_name = display_name or device_id
            device_info = AudioDeviceInfo(
                device_id=sounddevice_index,
                name=device_name,
                channels=audio_channels or 1,
                sample_rate=audio_sample_rate or self.settings.sample_rate,
            )
            success = await self.app.enable_device(device_info)
            if not success:
                self.logger.error("Failed to enable audio device %s: stream failed to start", device_id)
                StatusMessage.send("device_error", {
                    "device_id": device_id,
                    "error": "Failed to start audio stream",
                }, command_id=command_id)
                return False

            self._current_device_id = device_id
            if hasattr(self.context, 'view') and self.context.view:
                short_name = device_name if len(device_name) <= 20 else device_name[:17] + "..."
                title = f"Audio(USB):{short_name}"
                try:
                    self.context.view.set_window_title(title)
                except Exception:
                    pass
            self.logger.info("Device %s assigned and enabled (index=%d)", device_id, sounddevice_index)
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
        self.logger.info("Unassigning device: %s", device_id)
        await self._unassign_current_device()

    async def _unassign_current_device(self) -> None:
        if self.app.state.device is None:
            return

        try:
            await self.app.disable_device()
            self._current_device_id = None
            self.logger.info("Device unassigned")
        except Exception as e:
            self.logger.error("Error unassigning device: %s", e, exc_info=True)

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
