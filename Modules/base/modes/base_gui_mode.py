
import asyncio
import logging
import sys
from abc import ABC, abstractmethod
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import tkinter as tk

from .base_mode import BaseMode
from logger_core.commands import BaseCommandHandler, CommandMessage, StatusMessage


class BaseGUIMode(BaseMode, ABC):

    def __init__(self, system: Any, enable_commands: bool = False):
        super().__init__(system)
        self.enable_commands = enable_commands
        self.gui: Optional[Any] = None
        self.command_handler: Optional[BaseCommandHandler] = None
        self.command_task: Optional[asyncio.Task] = None
        self.preview_task: Optional[asyncio.Task] = None
        self.device_retry_task: Optional[asyncio.Task] = None

    @abstractmethod
    def create_gui(self) -> Any:
        pass

    @abstractmethod
    def create_command_handler(self, gui: Any) -> BaseCommandHandler:
        pass

    def get_preview_update_interval(self) -> float:
        return 0.1

    def update_preview(self) -> None:
        pass

    def sync_recording_state(self) -> None:
        self._sync_gui_recording_state()

    def _sync_gui_recording_state(self) -> None:
        window = self.get_gui_window()
        if not window:
            return

        try:
            is_recording = getattr(self.system, 'recording', False)

            module_name = self.get_module_display_name()

            if is_recording:
                session_label = getattr(self.system, 'session_label', None)
                if session_label:
                    title = f"{module_name} - ⬤ RECORDING - Session: {session_label}"
                else:
                    title = f"{module_name} - ⬤ RECORDING"
            else:
                title = module_name

            window.title(title)

        except Exception as e:
            self.logger.debug("Error updating window title: %s", e)

    def get_module_display_name(self) -> str:
        system_name = self.system.__class__.__name__

        if system_name.endswith("System"):
            system_name = system_name[:-6]

        # Insert spaces before capital letters (e.g., "AudioRecorder" → "Audio Recorder")
        import re
        display_name = re.sub(r'([A-Z])', r' \1', system_name).strip()

        return display_name

    def update_window_title(self, status: str = None) -> None:
        window = self.get_gui_window()
        if not window:
            return

        try:
            module_name = self.get_module_display_name()

            if status:
                title = f"{module_name} - {status}"
            else:
                title = module_name

            window.title(title)

        except Exception as e:
            self.logger.debug("Error updating window title: %s", e)

    async def cleanup(self) -> None:
        pass

    async def _device_retry_loop(self) -> None:
        retry_interval = self.get_device_retry_interval()

        while not self.system.initialized and self.system.running:
            try:
                self.logger.info("Attempting to detect devices...")

                await self.system._initialize_devices()

                self.system.initialized = True
                self.logger.info("Devices detected successfully!")

                if hasattr(self.system, 'enable_gui_commands') and self.system.enable_gui_commands:
                    from logger_core.commands import StatusMessage
                    StatusMessage.send("initialized", {"status": "connected"})

                break

            except asyncio.CancelledError:
                self.logger.debug("Device retry loop cancelled")
                raise
            except Exception as e:
                self.logger.debug("Device detection attempt failed: %s", e)

            # Wait before next retry with frequent cancellation checks
            for _ in range(int(retry_interval * 10)):
                if not self.system.running:
                    return
                await asyncio.sleep(0.1)

        if self.system.initialized:
            try:
                await self.on_devices_connected()
            except Exception as e:
                self.logger.error("Failed to setup GUI after device initialization: %s", e)

    def get_device_retry_interval(self) -> float:
        return 3.0

    async def on_devices_connected(self) -> None:
        pass

    def create_tasks(self) -> list[asyncio.Task]:
        tasks = []

        if not self.system.initialized:
            self.logger.info("Devices not detected - starting retry task")
            self.device_retry_task = asyncio.create_task(self._device_retry_loop())
            tasks.append(self.device_retry_task)

        return tasks

    async def on_auto_start_recording(self) -> None:
        pass

    def on_closing(self) -> None:
        if self.gui and hasattr(self.gui, 'handle_window_close'):
            try:
                self.gui.handle_window_close()
            except Exception as e:
                self.logger.error("Error in handle_window_close: %s", e, exc_info=True)
                self.system.running = False
                self.system.shutdown_event.set()
        else:
            self.system.running = False
            self.system.shutdown_event.set()

    def get_gui_window(self) -> Optional[Any]:
        if self.gui:
            if hasattr(self.gui, 'root'):
                return self.gui.root
            elif hasattr(self.gui, 'window'):
                return self.gui.window
        return None

    async def run(self) -> None:
        self.system.running = True

        self.gui = self.create_gui()

        if self.enable_commands:
            self.command_handler = self.create_command_handler(self.gui)
            self.logger.info("Starting GUI mode with parent command support")
        else:
            self.logger.info("Starting GUI mode (standalone)")

        if getattr(self.system, 'auto_start_recording', False):
            await self.on_auto_start_recording()

        self.preview_task = asyncio.create_task(self._preview_update_loop())

        if self.enable_commands:
            reader = await self._setup_stdin_reader()
            self.command_task = asyncio.create_task(self._command_listener(reader))

        module_tasks = self.create_tasks()

        try:
            tasks = [
                self._run_gui_async(),
                self.preview_task,
            ]

            if self.command_task:
                tasks.append(self.command_task)

            tasks.extend(module_tasks)

            results = await asyncio.gather(*tasks, return_exceptions=True)

            task_names = ['GUI', 'Preview Loop', 'Command Listener'] + [f'Task {i}' for i in range(len(module_tasks))]
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    task_name = task_names[i] if i < len(task_names) else f"Task {i}"
                    self.logger.exception(
                        "%s task failed with exception: %s",
                        task_name, result,
                        exc_info=result
                    )

        finally:
            if self.preview_task and not self.preview_task.done():
                self.preview_task.cancel()

            if self.command_task and not self.command_task.done():
                self.command_task.cancel()

            for task in module_tasks:
                if task and not task.done():
                    task.cancel()

            pending = []
            if self.preview_task:
                pending.append(self.preview_task)
            if self.command_task:
                pending.append(self.command_task)
            pending.extend(module_tasks)

            if pending:
                results = await asyncio.gather(*pending, return_exceptions=True)
                for i, result in enumerate(results):
                    if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                        self.logger.exception(
                            "Task cleanup failed with exception: %s",
                            result,
                            exc_info=result
                        )

            try:
                await self.cleanup()
            except Exception as e:
                self.logger.exception("Cleanup failed: %s", e, exc_info=True)

    async def _run_gui_async(self) -> None:
        import tkinter as tk

        loop = asyncio.get_event_loop()
        window = self.get_gui_window()

        if not window:
            self.logger.error("No GUI window available")
            return

        def update_gui():
            try:
                if window.winfo_exists():
                    window.update()
                    if self.system.running:
                        loop.call_later(0.01, update_gui)  # 100 Hz GUI updates
                else:
                    self.system.running = False
            except tk.TclError:
                self.system.running = False
            except Exception as e:
                self.logger.error("GUI update error: %s", e)
                self.system.running = False

        try:
            loop.call_soon(update_gui)

            await self.system.shutdown_event.wait()

        finally:
            if self.gui:
                try:
                    if hasattr(self.gui, 'destroy'):
                        self.gui.destroy()
                    elif window:
                        window.destroy()
                except Exception as e:
                    self.logger.debug("Error destroying GUI: %s", e)

    async def _preview_update_loop(self) -> None:
        interval = self.get_preview_update_interval()
        window = self.get_gui_window()

        while self.is_running():
            try:
                if window and window.winfo_exists():
                    window.after(0, self.update_preview)

                await asyncio.sleep(interval)
            except Exception as e:
                self.logger.debug("Preview update error: %s", e)
                break

    async def _setup_stdin_reader(self) -> asyncio.StreamReader:
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        return reader

    async def _command_listener(self, reader: asyncio.StreamReader) -> None:
        self.logger.info("Command listener started (parent communication enabled)")

        while self.is_running():
            try:
                try:
                    line = await asyncio.wait_for(reader.readline(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue

                if not line:
                    self.logger.info("Parent closed stdin, initiating shutdown")
                    self.system.running = False
                    self.system.shutdown_event.set()
                    break

                line_str = line.decode().strip()
                if line_str:
                    command_data = CommandMessage.parse(line_str)
                    if command_data:
                        continue_running = await self._handle_command_with_gui_sync(command_data)
                        if not continue_running:
                            self.logger.info("Quit command received, exiting command listener")
                            break
                    else:
                        StatusMessage.send("error", {"message": "Invalid JSON"})

            except Exception as e:
                StatusMessage.send("error", {"message": f"Command error: {e}"})
                self.logger.error("Command listener error: %s", e)
                break

        self.logger.info("Command listener stopped")

    async def _handle_command_with_gui_sync(self, command_data: dict) -> bool:
        if not self.command_handler:
            self.logger.error("No command handler available")
            return True

        cmd = command_data.get("command")

        continue_running = await self.command_handler.handle_command(command_data)

        if not continue_running:
            return False

        # Sync GUI state after command execution (thread-safe via window.after)
        window = self.get_gui_window()
        if window and window.winfo_exists():
            if cmd in ("start_recording", "stop_recording"):
                window.after(0, self.sync_recording_state)

        return True
