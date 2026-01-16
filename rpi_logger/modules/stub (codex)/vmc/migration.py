"""Scaffolding helpers for migrating legacy Tkinter modules onto StubCodex."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from rpi_logger.core.logging_utils import get_module_logger

from .runtime import ModuleRuntime
from .view import StubCodexView


class LegacySystemRuntimeAdapter(ModuleRuntime):
    """Wrap a legacy BaseSystem so it can run inside StubCodex as a ModuleRuntime."""

    def __init__(self, system, *, logger: Optional[logging.Logger] = None) -> None:
        self.system = system
        self.logger = logger or get_module_logger("LegacySystemRuntime")

    async def start(self) -> None:
        await self.system.run()

    async def shutdown(self) -> None:
        await self.system.cleanup()

    async def handle_command(self, command: dict[str, Any]) -> bool:  # type: ignore[override]
        handler = getattr(self.system, "handle_command", None)
        if callable(handler):
            return bool(await handler(command))
        return False

    async def handle_user_action(self, action: str, **kwargs: Any) -> bool:  # type: ignore[override]
        handler = getattr(self.system, "handle_user_action", None)
        if callable(handler):
            return bool(await handler(action, **kwargs))
        return False

    async def healthcheck(self) -> bool:
        checker = getattr(self.system, "healthcheck", None)
        if callable(checker):
            return bool(await checker())
        return True


class LegacyTkViewBridge:
    """Helper that mounts an existing Tk builder inside the StubCodex view."""

    def __init__(self, stub_view: Optional[StubCodexView], *, logger: Optional[logging.Logger] = None) -> None:
        self.stub_view = stub_view
        self.logger = logger or get_module_logger("LegacyTkViewBridge")
        self._cleanup_callbacks: list[Callable[[], None]] = []

    def mount(self, builder: Callable[[Any], None]) -> None:
        """Invoke a legacy builder with the stub's content frame."""

        if not self.stub_view:
            raise RuntimeError("Stub view unavailable; cannot mount legacy content")

        def _wrapped(parent) -> None:
            result = builder(parent)
            cleanup = getattr(result, "destroy", None)
            if callable(cleanup):
                self._cleanup_callbacks.append(cleanup)

        self.stub_view.build_stub_content(_wrapped)

    def register_cleanup(self, func: Callable[[], None]) -> None:
        self._cleanup_callbacks.append(func)

    def cleanup(self) -> None:
        for callback in reversed(self._cleanup_callbacks):
            try:
                callback()
            except Exception:
                pass  # Cleanup callback failed, ignore
        self._cleanup_callbacks.clear()


__all__ = [
    "LegacySystemRuntimeAdapter",
    "LegacyTkViewBridge",
]
