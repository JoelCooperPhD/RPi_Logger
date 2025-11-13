"""Runtime adapter that wires the stub supervisor to :class:`AudioApp`."""

from __future__ import annotations

from typing import Any, Dict

from logger_core.commands import StatusMessage

from vmc import ModuleRuntime, RuntimeContext

from .app import AudioApp
from .config import AudioStubSettings


class AudioStubRuntime(ModuleRuntime):
    """Adapter used by the stub supervisor."""

    def __init__(self, context: RuntimeContext) -> None:
        self.context = context
        self.settings = AudioStubSettings.from_args(context.args)
        self.app = AudioApp(context, self.settings, status_callback=StatusMessage.send)

    async def start(self) -> None:
        await self.app.start()

    async def shutdown(self) -> None:
        await self.app.shutdown()

    async def handle_command(self, command: Dict[str, Any]) -> bool:
        return await self.app.handle_command(command)

    async def handle_user_action(self, action: str, **kwargs: Any) -> bool:
        return await self.app.handle_user_action(action, **kwargs)

    async def healthcheck(self) -> bool:
        return await self.app.healthcheck()
