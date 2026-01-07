"""ModuleRuntime + main.py template for Elm/Redux Logger modules."""

# === runtime.py ===

from vmc import ModuleRuntime, RuntimeContext
from core.state import AppState, initial_state
from core.store import Store
from infra.effect_executor import EffectExecutor

class MyModuleRuntime(ModuleRuntime):
    def __init__(self, context: RuntimeContext):
        self._context = context
        self._store: Store | None = None
        self._executor: EffectExecutor | None = None

    async def start(self) -> None:
        self._store = Store(initial_state())
        self._executor = EffectExecutor(self._store.dispatch)
        self._store.set_effect_handler(self._executor.execute)

        if self._context.view:
            self._store.subscribe(self._context.view.render)

    async def handle_command(self, command: dict) -> bool:
        from infra.command_handler import command_to_action
        action = command_to_action(command)
        if action:
            await self._store.dispatch(action)
            return True
        return False

    async def shutdown(self) -> None:
        from core.actions import Shutdown
        if self._store:
            await self._store.dispatch(Shutdown())


# === main.py ===

import asyncio
import sys
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent
MODULE_ID = "mymodule"
DISPLAY_NAME = "MyModule"

def _find_project_root(start: Path) -> Path:
    for parent in start.parents:
        if parent.name == "rpi_logger":
            return parent.parent
    return start.parents[-1]

PROJECT_ROOT = _find_project_root(MODULE_DIR)
for path in [PROJECT_ROOT, MODULE_DIR.parent / "stub (codex)"]:
    if path.exists() and str(path) not in sys.path:
        sys.path.insert(0, str(path))

from vmc import StubCodexSupervisor, RuntimeRetryPolicy
from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger(f"Main{DISPLAY_NAME}")

def build_runtime(context):
    from runtime import MyModuleRuntime
    return MyModuleRuntime(context)

async def main():
    # Parse args, load config here
    args = parse_args()

    supervisor = StubCodexSupervisor(
        args, MODULE_DIR, logger,
        runtime_factory=build_runtime,
        runtime_retry_policy=RuntimeRetryPolicy(interval=3.0, max_attempts=3),
        display_name=DISPLAY_NAME,
        module_id=MODULE_ID,
    )
    await supervisor.run()

if __name__ == "__main__":
    asyncio.run(main())
