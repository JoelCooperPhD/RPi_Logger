#!/usr/bin/env python3
"""
Async supervisor for camera system.
Maintains camera availability with automatic retry on hardware failures.
"""

import asyncio
import logging
from typing import Optional

from .camera_system import CameraSystem, CameraInitializationError

logger = logging.getLogger("CameraSupervisor")


class CameraSupervisor:
    """Async wrapper that maintains camera availability."""

    def __init__(self, args):
        self.args = args
        self.logger = logging.getLogger("CameraSupervisor")
        self.retry_interval = getattr(args, "discovery_retry", 3.0)
        self.shutdown_event = asyncio.Event()
        self.system: Optional[CameraSystem] = None

    async def run(self) -> None:
        loop = asyncio.get_running_loop()

        while not self.shutdown_event.is_set():
            system = CameraSystem(self.args)
            self.system = system

            try:
                await loop.run_in_executor(None, system.run)
            except CameraInitializationError:
                if self.shutdown_event.is_set():
                    break
                self.logger.info(
                    "Camera hardware not available; retrying in %.1fs",
                    self.retry_interval,
                )
                await asyncio.sleep(self.retry_interval)
                continue
            except KeyboardInterrupt:
                self.logger.info("Camera system interrupted")
                break
            except Exception as exc:  # pragma: no cover - defensive
                if self.shutdown_event.is_set():
                    break
                self.logger.exception("Camera system crashed: %s", exc)
                await asyncio.sleep(self.retry_interval)
                continue
            finally:
                try:
                    system.cleanup()
                except Exception as exc:  # pragma: no cover - defensive
                    self.logger.error("Camera cleanup failed: %s", exc)
                self.system = None

            # Reaching here means run() completed normally; exit supervisor.
            break

        self.logger.debug("Camera supervisor exiting")

    async def shutdown(self) -> None:
        if self.shutdown_event.is_set():
            return
        self.shutdown_event.set()

        system = self.system
        if system:
            system.shutdown_event.set()
            if system.command_thread and system.command_thread.is_alive():
                system.command_thread.join(timeout=1.0)
