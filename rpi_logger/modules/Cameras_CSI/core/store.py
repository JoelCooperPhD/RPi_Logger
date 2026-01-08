from typing import Callable, Awaitable, Protocol
import asyncio

from .state import AppState, initial_state
from .actions import Action
from .effects import Effect
from .update import update


class EffectHandler(Protocol):
    async def __call__(
        self,
        effect: Effect,
        dispatch: Callable[[Action], Awaitable[None]]
    ) -> None: ...


class Store:
    def __init__(self, initial: AppState | None = None):
        self._state = initial if initial is not None else initial_state()
        self._subscribers: list[Callable[[AppState], None]] = []
        self._effect_handler: EffectHandler | None = None
        self._dispatch_queue: asyncio.Queue[Action] = asyncio.Queue()
        self._processing = False

    @property
    def state(self) -> AppState:
        return self._state

    def subscribe(self, callback: Callable[[AppState], None]) -> Callable[[], None]:
        self._subscribers.append(callback)
        callback(self._state)
        return lambda: self._subscribers.remove(callback)

    def set_effect_handler(self, handler: EffectHandler) -> None:
        self._effect_handler = handler

    def _notify_subscribers(self) -> None:
        for subscriber in self._subscribers:
            subscriber(self._state)

    async def dispatch(self, action: Action) -> None:
        self._state, effects = update(self._state, action)
        self._notify_subscribers()

        if self._effect_handler:
            for effect in effects:
                await self._effect_handler(effect, self.dispatch)

    def dispatch_sync(self, action: Action) -> None:
        self._state, effects = update(self._state, action)
        self._notify_subscribers()


def create_store(initial: AppState | None = None) -> Store:
    return Store(initial)
