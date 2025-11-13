"""Lightweight runtime abstractions for modules built on the stub stack."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional, TYPE_CHECKING

from .constants import DISPLAY_NAME, MODULE_ID

if TYPE_CHECKING:  # pragma: no cover - type checking only
    from .controller import StubCodexController
    from .model import StubCodexModel
    from .supervisor import StubCodexSupervisor
    from .view import StubCodexView


class ModuleRuntime:
    """Minimal async lifecycle contract for domain-specific runtimes.

    Subclasses are expected to implement :meth:`start`. The other hooks are
    optional and default to no-ops so simple runtimes can stay lean.
    """

    async def start(self) -> None:
        raise NotImplementedError("ModuleRuntime.start() must be implemented")

    async def shutdown(self) -> None:  # pragma: no cover - default no-op
        return None

    async def cleanup(self) -> None:  # pragma: no cover - default no-op
        return None

    async def handle_command(self, command: Dict[str, Any]) -> bool:
        """Return True if the command was handled."""
        return False

    async def handle_user_action(self, action: str, **kwargs: Any) -> bool:
        """Return True if the user action was consumed."""
        return False

    async def healthcheck(self) -> bool:
        """Override to provide a heartbeat for retry policies."""
        return True


@dataclass(slots=True)
class RuntimeContext:
    """Supplies construction-time context to runtime factories."""

    args: Any
    module_dir: Path
    logger: logging.Logger
    model: "StubCodexModel"
    controller: "StubCodexController"
    supervisor: "StubCodexSupervisor"
    view: Optional["StubCodexView"] = None
    display_name: str = DISPLAY_NAME
    module_id: str = MODULE_ID


RuntimeFactory = Callable[[RuntimeContext], ModuleRuntime | Awaitable[ModuleRuntime]]
"""Callable that creates a :class:`ModuleRuntime` for the stub supervisor."""
