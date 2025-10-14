#!/usr/bin/env python3
"""
Async supervisor for audio system.
Maintains audio device availability with automatic retry on hardware failures.
"""

import asyncio
import logging
from typing import Optional

from .audio_system import AudioSystem, AudioInitializationError
from .constants import DEVICE_DISCOVERY_RETRY

logger = logging.getLogger("AudioSupervisor")


class AudioSupervisor:
    """Async wrapper that maintains audio device availability."""

    def __init__(self, args):
        self.args = args
        self.logger = logging.getLogger("AudioSupervisor")
        self.retry_interval = getattr(args, "discovery_retry", DEVICE_DISCOVERY_RETRY)
        self.shutdown_event = asyncio.Event()
        self.system: Optional[AudioSystem] = None

    async def run(self) -> None:
        """Run audio system with automatic retry on failure."""
        while not self.shutdown_event.is_set():
            system = AudioSystem(self.args)
            self.system = system

            try:
                await system.run()
            except AudioInitializationError:
                if self.shutdown_event.is_set():
                    break
                self.logger.info(
                    "Audio hardware not available; retrying in %.1fs",
                    self.retry_interval,
                )
                await asyncio.sleep(self.retry_interval)
                continue
            except KeyboardInterrupt:
                self.logger.info("Audio system interrupted")
                break
            except Exception as exc:  # pragma: no cover - defensive
                if self.shutdown_event.is_set():
                    break
                self.logger.exception("Audio system crashed: %s", exc)
                await asyncio.sleep(self.retry_interval)
                continue
            finally:
                try:
                    await system.cleanup()
                except Exception as exc:  # pragma: no cover - defensive
                    self.logger.error("Audio cleanup failed: %s", exc)
                self.system = None

            # Reaching here means run() completed normally; exit supervisor.
            break

        self.logger.debug("Audio supervisor exiting")

    async def shutdown(self) -> None:
        """Shutdown the supervisor and audio system."""
        if self.shutdown_event.is_set():
            return
        self.shutdown_event.set()

        system = self.system
        if system:
            system.shutdown_event.set()
