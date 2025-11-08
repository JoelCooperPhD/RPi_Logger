"""Audio (Stub) runtime wired into the stub (codex) stack."""

from __future__ import annotations

from typing import Any, Dict

from logger_core.commands import StatusMessage

from vmc import ModuleRuntime, RuntimeContext

from .audio_mvc import AudioController, AudioStubConfig


class AudioStubRuntime(ModuleRuntime):
    """Thin shell delegating all logic to the AudioController."""

    def __init__(self, context: RuntimeContext) -> None:
        self.context = context
        self.config = AudioStubConfig.from_args(context.args)
        self.controller = AudioController(
            context,
            self.config,
            status_callback=StatusMessage.send,
        )

    async def start(self) -> None:
        await self.controller.start()

    async def shutdown(self) -> None:
        await self.controller.shutdown()

    async def handle_command(self, command: Dict[str, Any]) -> bool:
        return await self.controller.handle_command(command)

    async def handle_user_action(self, action: str, **kwargs: Any) -> bool:
        return await self.controller.handle_user_action(action, **kwargs)

    async def healthcheck(self) -> bool:
        return await self.controller.healthcheck()
