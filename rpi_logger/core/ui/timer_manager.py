
import asyncio
import datetime
from rpi_logger.core.logging_utils import get_module_logger
from tkinter import ttk
from typing import Optional

from ..system_monitor import SystemMonitor


class TimerManager:

    def __init__(self):
        self.logger = get_module_logger("TimerManager")

        self.current_time_label: Optional[ttk.Label] = None
        self.session_timer_label: Optional[ttk.Label] = None
        self.trial_timer_label: Optional[ttk.Label] = None
        self.cpu_label: Optional[ttk.Label] = None
        self.ram_label: Optional[ttk.Label] = None
        self.disk_label: Optional[ttk.Label] = None

        self.session_start_time: Optional[datetime.datetime] = None
        self.trial_start_time: Optional[datetime.datetime] = None

        self.clock_timer_task: Optional[asyncio.Task] = None
        self.session_timer_task: Optional[asyncio.Task] = None
        self.trial_timer_task: Optional[asyncio.Task] = None
        self.system_monitor_task: Optional[asyncio.Task] = None

        self.running = False
        self.system_monitor = SystemMonitor()

    def set_labels(
        self,
        current_time_label: ttk.Label,
        session_timer_label: ttk.Label,
        trial_timer_label: ttk.Label,
        cpu_label: Optional[ttk.Label] = None,
        ram_label: Optional[ttk.Label] = None,
        disk_label: Optional[ttk.Label] = None
    ) -> None:
        self.current_time_label = current_time_label
        self.session_timer_label = session_timer_label
        self.trial_timer_label = trial_timer_label
        self.cpu_label = cpu_label
        self.ram_label = ram_label
        self.disk_label = disk_label

    async def start_clock(self) -> None:
        if self.clock_timer_task:
            self.clock_timer_task.cancel()
        self.running = True
        self.clock_timer_task = asyncio.create_task(self._update_clock_timer())
        if self.system_monitor_task:
            self.system_monitor_task.cancel()
        self.system_monitor_task = asyncio.create_task(self._update_system_monitor())

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
        if self.system_monitor_task:
            self.system_monitor_task.cancel()
            self.system_monitor_task = None

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

    async def _update_system_monitor(self) -> None:
        try:
            while self.running:
                try:
                    cpu_percent = await asyncio.to_thread(self.system_monitor.get_cpu_percent)
                    ram_percent = await asyncio.to_thread(self.system_monitor.get_memory_percent)
                    total_gb, used_gb, free_gb = await asyncio.to_thread(self.system_monitor.get_disk_space)

                    if self.cpu_label:
                        self.cpu_label.config(text=f"{cpu_percent:.1f}%")

                    if self.ram_label:
                        self.ram_label.config(text=f"{ram_percent:.1f}%")

                    if self.disk_label:
                        self.disk_label.config(text=f"{free_gb:.1f} GB")
                except Exception as e:
                    self.logger.warning("System monitor update failed: %s", e)

                await asyncio.sleep(2.0)
        except asyncio.CancelledError:
            pass
