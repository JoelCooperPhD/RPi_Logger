
import asyncio
import csv
import datetime
from rpi_logger.core.logging_utils import get_module_logger
from pathlib import Path

import aiofiles

logger = get_module_logger("EventLogger")


class EventLogger:

    def __init__(self, session_dir: Path, session_timestamp: str):
        self.session_dir = session_dir
        self.event_log_path = session_dir / f"{session_timestamp}_CONTROL.csv"
        self.initialized = False
        self._write_lock = asyncio.Lock()

    async def initialize(self) -> None:
        await asyncio.to_thread(self.session_dir.mkdir, parents=True, exist_ok=True)

        async with aiofiles.open(self.event_log_path, 'w', newline='') as f:
            await f.write("timestamp,event_type,details\n")

        self.initialized = True
        logger.info("Event logger initialized: %s", self.event_log_path)

    async def log_event(self, event_type: str, details: str = "") -> None:
        if not self.initialized:
            logger.warning("Event logger not initialized, skipping event: %s", event_type)
            return

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        async with self._write_lock:
            async with aiofiles.open(self.event_log_path, 'a', newline='') as f:
                import io
                buffer = io.StringIO()
                writer = csv.writer(buffer)
                writer.writerow([timestamp, event_type, details])
                await f.write(buffer.getvalue())

        logger.debug("Logged event: %s - %s", event_type, details)

    async def log_session_start(self, session_dir: str) -> None:
        await self.log_event("session_start", f"path={session_dir}")

    async def log_session_stop(self) -> None:
        await self.log_event("session_stop", "")

    async def log_trial_start(self, trial_number: int, trial_label: str = "") -> None:
        details = f"trial={trial_number}"
        if trial_label:
            details += f", label={trial_label}"
        await self.log_event("trial_start", details)

    async def log_trial_stop(self, trial_number: int) -> None:
        await self.log_event("trial_stop", f"trial={trial_number}")

    async def log_module_started(self, module_name: str) -> None:
        await self.log_event("module_started", f"module={module_name}")

    async def log_module_stopped(self, module_name: str) -> None:
        await self.log_event("module_stopped", f"module={module_name}")

    async def log_module_recording_started(self, module_name: str) -> None:
        await self.log_event("module_recording_started", f"module={module_name}")

    async def log_module_recording_stopped(self, module_name: str) -> None:
        await self.log_event("module_recording_stopped", f"module={module_name}")

    async def log_custom_event(self, event_type: str, details: str = "") -> None:
        await self.log_event(event_type, details)

    async def log_button_press(self, button_name: str, action: str = "") -> None:
        details = f"button={button_name}"
        if action:
            details += f", action={action}"
        await self.log_event("button_press", details)
