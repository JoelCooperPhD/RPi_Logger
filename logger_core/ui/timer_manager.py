
import asyncio
import datetime
import logging
import tkinter as tk
from typing import Optional


class TimerManager:

    def __init__(self):
        self.logger = logging.getLogger("TimerManager")

        self.current_time_label: Optional[tk.Label] = None
        self.session_timer_label: Optional[tk.Label] = None
        self.trial_timer_label: Optional[tk.Label] = None

        self.session_start_time: Optional[datetime.datetime] = None
        self.trial_start_time: Optional[datetime.datetime] = None

        self.clock_timer_task: Optional[asyncio.Task] = None
        self.session_timer_task: Optional[asyncio.Task] = None
        self.trial_timer_task: Optional[asyncio.Task] = None

        self.running = False

    def set_labels(
        self,
        current_time_label: tk.Label,
        session_timer_label: tk.Label,
        trial_timer_label: tk.Label
    ) -> None:
        self.current_time_label = current_time_label
        self.session_timer_label = session_timer_label
        self.trial_timer_label = trial_timer_label

    async def start_clock(self) -> None:
        if self.clock_timer_task:
            self.clock_timer_task.cancel()
        self.running = True
        self.clock_timer_task = asyncio.create_task(self._update_clock_timer())

    async def start_session_timer(self) -> None:
        self.session_start_time = datetime.datetime.now()
        if self.session_timer_task:
            self.session_timer_task.cancel()
        self.session_timer_task = asyncio.create_task(self._update_session_timer())

    async def stop_session_timer(self) -> None:
        self.session_start_time = None
        if self.session_timer_task:
            self.session_timer_task.cancel()
            self.session_timer_task = None
        if self.session_timer_label:
            self.session_timer_label.config(text="--:--:--")

    async def start_trial_timer(self) -> None:
        self.trial_start_time = datetime.datetime.now()
        if self.trial_timer_task:
            self.trial_timer_task.cancel()
        self.trial_timer_task = asyncio.create_task(self._update_trial_timer())

    async def stop_trial_timer(self) -> None:
        self.trial_start_time = None
        if self.trial_timer_task:
            self.trial_timer_task.cancel()
            self.trial_timer_task = None
        if self.trial_timer_label:
            self.trial_timer_label.config(text="--:--:--")

    async def stop_all(self) -> None:
        self.running = False
        if self.clock_timer_task:
            self.clock_timer_task.cancel()
            self.clock_timer_task = None
        if self.session_timer_task:
            self.session_timer_task.cancel()
            self.session_timer_task = None
        if self.trial_timer_task:
            self.trial_timer_task.cancel()
            self.trial_timer_task = None

    async def _update_clock_timer(self) -> None:
        try:
            while self.running:
                current_time = datetime.datetime.now()
                time_str = current_time.strftime("%H:%M:%S")
                if self.current_time_label:
                    self.current_time_label.config(text=time_str)
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass

    async def _update_session_timer(self) -> None:
        try:
            while self.session_start_time and self.running:
                elapsed = datetime.datetime.now() - self.session_start_time
                hours = int(elapsed.total_seconds() // 3600)
                minutes = int((elapsed.total_seconds() % 3600) // 60)
                seconds = int(elapsed.total_seconds() % 60)

                if self.session_timer_label:
                    self.session_timer_label.config(text=f"{hours:02d}:{minutes:02d}:{seconds:02d}")

                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass

    async def _update_trial_timer(self) -> None:
        try:
            while self.trial_start_time and self.running:
                elapsed = datetime.datetime.now() - self.trial_start_time
                hours = int(elapsed.total_seconds() // 3600)
                minutes = int((elapsed.total_seconds() % 3600) // 60)
                seconds = int(elapsed.total_seconds() % 60)

                if self.trial_timer_label:
                    self.trial_timer_label.config(text=f"{hours:02d}:{minutes:02d}:{seconds:02d}")

                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass
