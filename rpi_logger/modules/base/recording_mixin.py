import asyncio
from typing import Optional

from rpi_logger.core.logging_utils import get_module_logger


class RecordingStateMixin:

    def __init__(self):
        self._recording = False
        self._recording_count = 0
        self._recording_lock = asyncio.Lock()
        self.logger = get_module_logger(self.__class__.__name__)

    @property
    def recording(self) -> bool:
        return self._recording

    @recording.setter
    def recording(self, value: bool) -> None:
        self._recording = value

    @property
    def recording_count(self) -> int:
        return self._recording_count

    def _increment_recording_count(self) -> int:
        self._recording_count += 1
        return self._recording_count

    def validate_recording_start(self, require_initialized: bool = True) -> tuple[bool, Optional[str]]:
        if self._recording:
            return False, "Already recording"

        if require_initialized and hasattr(self, 'initialized') and not self.initialized:
            return False, "System not initialized"

        return True, None

    def validate_recording_stop(self) -> tuple[bool, Optional[str]]:
        if not self._recording:
            return False, "Not currently recording"

        return True, None

    async def with_recording_lock(self, coro):
        async with self._recording_lock:
            return await coro
