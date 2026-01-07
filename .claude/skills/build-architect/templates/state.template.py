"""Elm/Redux core files template."""

# === core/state.py ===

from dataclasses import dataclass
from enum import Enum, auto

class ModuleStatus(Enum):
    IDLE = auto()
    ACTIVE = auto()
    ERROR = auto()

@dataclass(frozen=True)
class AppState:
    status: ModuleStatus = ModuleStatus.IDLE
    error_message: str | None = None
    # Add module-specific state fields

def initial_state() -> AppState:
    return AppState()


# === core/actions.py ===

from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Initialize:
    pass

@dataclass(frozen=True)
class Shutdown:
    pass

@dataclass(frozen=True)
class ErrorOccurred:
    message: str

# Add module-specific actions

Action = Initialize | Shutdown | ErrorOccurred  # Union of all actions


# === core/effects.py ===

from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class LogMessage:
    level: str
    message: str

# Add module-specific effects (I/O descriptions)

Effect = LogMessage  # Union of all effects


# === core/update.py ===

from dataclasses import replace
from .state import AppState, ModuleStatus
from .actions import Action, Initialize, Shutdown, ErrorOccurred
from .effects import Effect, LogMessage

def update(state: AppState, action: Action) -> tuple[AppState, list[Effect]]:
    match action:
        case Initialize():
            return replace(state, status=ModuleStatus.ACTIVE), []

        case Shutdown():
            return replace(state, status=ModuleStatus.IDLE), []

        case ErrorOccurred(message):
            return replace(state, status=ModuleStatus.ERROR, error_message=message), [
                LogMessage("error", message)
            ]

        case _:
            return state, []


# === core/store.py ===

from typing import Callable, Awaitable
from .state import AppState
from .actions import Action
from .effects import Effect
from .update import update

class Store:
    def __init__(self, initial: AppState):
        self._state = initial
        self._subscribers: list[Callable[[AppState], None]] = []
        self._effect_handler: Callable[[Effect], Awaitable[None]] | None = None

    @property
    def state(self) -> AppState:
        return self._state

    def subscribe(self, callback: Callable[[AppState], None]) -> Callable[[], None]:
        self._subscribers.append(callback)
        return lambda: self._subscribers.remove(callback)

    def set_effect_handler(self, handler: Callable[[Effect], Awaitable[None]]) -> None:
        self._effect_handler = handler

    async def dispatch(self, action: Action) -> None:
        self._state, effects = update(self._state, action)
        for sub in self._subscribers:
            sub(self._state)
        if self._effect_handler:
            for effect in effects:
                await self._effect_handler(effect)
