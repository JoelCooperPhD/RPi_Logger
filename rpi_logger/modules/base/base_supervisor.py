
import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Generic, Optional, Type, TypeVar

from rpi_logger.core.logging_utils import ensure_structured_logger

SystemT = TypeVar('SystemT')
ErrorT = TypeVar('ErrorT', bound=Exception)


class BaseSupervisor(ABC, Generic[SystemT, ErrorT]):

    def __init__(self, args: Any, default_retry_interval: float = 3.0):
        self.args = args
        self.logger = ensure_structured_logger(getattr(args, "logger", None), fallback_name=self.__class__.__name__)
        self.retry_interval = getattr(args, "discovery_retry", default_retry_interval)
        self.shutdown_event = asyncio.Event()
        self.system: Optional[SystemT] = None

    @abstractmethod
    def create_system(self) -> SystemT:
        pass

    @abstractmethod
    def get_initialization_error_type(self) -> Type[ErrorT]:
        pass

    def get_system_name(self) -> str:
        class_name = self.__class__.__name__
        return class_name.replace('Supervisor', '')

    async def run(self) -> None:
        system_name = self.get_system_name()
        initialization_error = self.get_initialization_error_type()

        while not self.shutdown_event.is_set():
            system = self.create_system()
            self.system = system

            try:
                await system.run()

            except initialization_error:
                if self.shutdown_event.is_set():
                    break
                self.logger.info(
                    "%s hardware not available; retrying in %.1fs",
                    system_name,
                    self.retry_interval,
                )
                await asyncio.sleep(self.retry_interval)
                continue

            except KeyboardInterrupt:
                self.logger.info("%s system interrupted", system_name)
                break

            except Exception as exc:  # pragma: no cover - defensive
                if self.shutdown_event.is_set():
                    break
                self.logger.exception("%s system crashed: %s", system_name, exc)
                await asyncio.sleep(self.retry_interval)
                continue

            finally:
                try:
                    await system.cleanup()
                except Exception as exc:  # pragma: no cover - defensive
                    self.logger.error("%s cleanup failed: %s", system_name, exc)
                self.system = None

            break

        self.logger.debug("%s supervisor exiting", system_name)

    async def shutdown(self) -> None:
        if self.shutdown_event.is_set():
            return

        self.shutdown_event.set()

        system = self.system
        if system and hasattr(system, 'shutdown_event'):
            system.shutdown_event.set()
