
import asyncio
import io
import logging
import os
import sys
from abc import ABC, abstractmethod
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import tkinter as tk

from .base_mode import BaseMode
from logger_core.commands import BaseCommandHandler, CommandMessage, StatusMessage
from logger_core.async_bridge import AsyncBridge


class BaseGUIMode(BaseMode, ABC):

    def __init__(self, system: Any, enable_commands: bool = False):
        super().__init__(system)
        self.enable_commands = enable_commands
        self.gui: Optional[Any] = None
        self.async_bridge: Optional[AsyncBridge] = None
        self.command_handler: Optional[BaseCommandHandler] = None
        self.command_task: Optional[asyncio.Task] = None
        self.preview_task: Optional[asyncio.Task] = None
        self.device_retry_task: Optional[asyncio.Task] = None
        self._closing = False
        self._close_future = None
        self._stdin_transport = None
        self._stdin_pipe = None
        self._stdin_reader: Optional[asyncio.StreamReader] = None

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
            # Check multiple recording state attributes for compatibility
            is_recording = getattr(self.system, 'recording', False)
            if not is_recording and hasattr(self.system, 'recording_manager'):
                is_recording = getattr(self.system.recording_manager, 'is_recording', False)

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

            # Call hook for module-specific UI updates
            self._on_recording_state_changed(is_recording)

        except Exception as e:
            self.logger.debug("Error updating window title: %s", e)

    def _on_recording_state_changed(self, is_recording: bool) -> None:
        """
        Hook method for module-specific UI updates when recording state changes.

        Override this method in subclasses to add custom UI behavior during
        recording state transitions (e.g., disabling menu items, changing colors).

        Args:
            is_recording: True if currently recording, False otherwise
        """
        pass

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
        retry_attempt = 0

        while not self.system.initialized and self.system.running:
            retry_attempt += 1
            try:
                if retry_attempt == 1:
                    self.logger.info("Scanning for devices...")
                else:
                    self.logger.info("Retrying device detection (attempt %d)...", retry_attempt)
                self.system.lifecycle_timer.mark_phase(f"device_scan_{retry_attempt}")

                await self.system._initialize_devices()

                self.system.initialized = True

                if retry_attempt == 1:
                    self.logger.info("Device(s) detected on first scan!")
                else:
                    self.logger.info("Device(s) detected after %d attempts!", retry_attempt)

                if hasattr(self.system, 'enable_gui_commands') and self.system.enable_gui_commands:
                    from logger_core.commands import StatusMessage
                    init_duration = self.system.lifecycle_timer.get_duration("process_start", "initialized")
                    StatusMessage.send_with_timing("initialized", init_duration, {
                        "status": "connected",
                        "scan_attempts": retry_attempt
                    })

                break

            except asyncio.CancelledError:
                self.logger.debug("Device scan cancelled")
                raise
            except KeyboardInterrupt:
                self.logger.debug("Device detection cancelled by user")
                return
            except Exception as e:
                if retry_attempt == 1:
                    self.logger.info("No devices found on initial scan: %s", e)
                else:
                    self.logger.debug("Device detection attempt %d failed: %s", retry_attempt, e)

            if retry_attempt > 1:
                self.logger.info("Waiting %ds before next scan...", retry_interval)

            for _ in range(int(retry_interval * 10)):
                if not self.system.running:
                    return
                await asyncio.sleep(0.1)

        if self.system.initialized:
            try:
                self.system.lifecycle_timer.mark_phase("gui_ready")
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

    def _close_command_stream(self) -> None:
        if self._stdin_transport is not None:
            try:
                self._stdin_transport.close()
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.debug("Failed to close stdin transport: %s", exc)
            self._stdin_transport = None

        if self._stdin_pipe is not None:
            try:
                self._stdin_pipe.close()
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.debug("Failed to close stdin pipe: %s", exc)
            self._stdin_pipe = None

        self._stdin_reader = None

    def on_closing(self) -> None:
        if self._closing:
            self.logger.debug("Close request ignored; shutdown already in progress")
            return

        self._closing = True
        self.logger.info("Window close requested")
        self.system.lifecycle_timer.mark_phase("shutdown_start")

        self.system.running = False
        self.system.shutdown_event.set()
        self._close_command_stream()

        if self.system.enable_gui_commands:
            StatusMessage.send("shutdown_started", {"reason": "user_closed_window"})

        window = self.get_gui_window()
        if window:
            try:
                window.title(f"{self.get_module_display_name()} - Closing…")
                window.update_idletasks()
            except Exception:
                pass

        if not self.async_bridge or self.async_bridge.loop is None:
            self.logger.warning("Async bridge unavailable; performing best-effort synchronous shutdown")

            if hasattr(self, 'sync_cleanup'):
                try:
                    self.logger.info("Running synchronous cleanup without bridge")
                    self.sync_cleanup()
                    self.system.lifecycle_timer.mark_phase("sync_cleanup_complete")
                except Exception as exc:
                    self.logger.error("Error during sync cleanup: %s", exc, exc_info=True)

            if self.gui and hasattr(self.gui, 'handle_window_close'):
                try:
                    self.gui.handle_window_close()
                    self.system.lifecycle_timer.mark_phase("geometry_saved")
                except Exception as exc:
                    self.logger.error("Error saving geometry: %s", exc, exc_info=True)

            if window:
                try:
                    window.destroy()
                    self.system.lifecycle_timer.mark_phase("window_destroyed")
                except Exception as exc:
                    self.logger.debug("Error destroying window: %s", exc)

            if self.system.enable_gui_commands:
                shutdown_duration = self.system.lifecycle_timer.get_duration("shutdown_start", "window_destroyed")
                StatusMessage.send("quitting", {
                    "reason": "user_closed_window",
                    "shutdown_duration_ms": round(shutdown_duration, 1)
                })
            return

        self._close_future = self.async_bridge.run_coroutine(self._shutdown_sequence())

    async def _shutdown_sequence(self) -> None:
        try:
            if self.system:
                try:
                    self.logger.debug("Starting shutdown guard")
                    await self.system.start_shutdown_guard(self.system.shutdown_guard_timeout)
                    self.logger.warning("BaseGUIMode.on_closing: shutdown guard scheduled")
                except Exception as exc:  # pragma: no cover - defensive
                    self.logger.error("Failed to start shutdown guard: %s", exc)

            loop = asyncio.get_running_loop()

            if hasattr(self, 'sync_cleanup'):
                try:
                    self.logger.info("Running synchronous cleanup in executor")
                    await loop.run_in_executor(None, self.sync_cleanup)
                    self.system.lifecycle_timer.mark_phase("sync_cleanup_complete")
                except Exception as exc:
                    self.logger.error("Error during sync cleanup: %s", exc, exc_info=True)

            if self.gui and hasattr(self.gui, 'handle_window_close'):
                try:
                    self.logger.info("Saving geometry")
                    await self.async_bridge.call_in_gui_async(self.gui.handle_window_close)
                    self.system.lifecycle_timer.mark_phase("geometry_saved")
                except Exception as exc:
                    self.logger.error("Error saving geometry: %s", exc, exc_info=True)

            window = self.get_gui_window()
            if window:
                try:
                    self.logger.info("Destroying window")
                    await self.async_bridge.call_in_gui_async(window.destroy)
                    self.system.lifecycle_timer.mark_phase("window_destroyed")
                except Exception as exc:
                    self.logger.debug("Error destroying window: %s", exc)
            else:
                self.system.lifecycle_timer.mark_phase("window_destroyed")

            if self.system.enable_gui_commands:
                shutdown_duration = self.system.lifecycle_timer.get_duration("shutdown_start", "window_destroyed")
                StatusMessage.send("quitting", {
                    "reason": "user_closed_window",
                    "shutdown_duration_ms": round(shutdown_duration, 1)
                })
        finally:
            if self.system:
                try:
                    await self.system.cancel_shutdown_guard()
                except Exception as exc:  # pragma: no cover - defensive
                    self.logger.debug("Failed to cancel shutdown guard: %s", exc)

    def sync_cleanup(self) -> None:
        """Synchronous cleanup - override in subclasses if needed."""
        pass

    def get_gui_window(self) -> Optional[Any]:
        if self.gui:
            if hasattr(self.gui, 'root'):
                return self.gui.root
            elif hasattr(self.gui, 'window'):
                return self.gui.window
        return None

    async def run(self) -> None:
        """
        Run GUI mode using guest mode pattern.

        Architecture:
        - Tkinter mainloop runs in MAIN thread (blocking)
        - AsyncIO event loop runs in BACKGROUND daemon thread
        - AsyncBridge provides thread-safe communication
        """
        self.system.running = True

        self.gui = self.create_gui()
        window = self.get_gui_window()

        if not window:
            self.logger.error("Failed to create GUI window")
            return

        self.async_bridge = AsyncBridge(window)
        self.async_bridge.start()

        self.gui.async_bridge = self.async_bridge

        if hasattr(self, 'on_async_bridge_started'):
            self.logger.info("Calling on_async_bridge_started hook...")
            self.async_bridge.run_coroutine(self.on_async_bridge_started())

        window.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.logger.info("Window close handler registered")

        if self.enable_commands:
            self.logger.info("Starting GUI mode with parent command support")
            self.command_handler = self.create_command_handler(self.gui)
            self.command_task = self.async_bridge.run_coroutine(
                self._start_command_listener()
            )
        else:
            self.logger.info("Starting GUI mode (standalone)")

        if getattr(self.system, 'auto_start_recording', False):
            await self.on_auto_start_recording()

        self.async_bridge.run_coroutine(self._preview_update_loop())

        if not self.system.initialized:
            def start_device_detection():
                self.logger.info("Starting device detection...")
                self.device_retry_task = self.async_bridge.run_coroutine(self._device_retry_loop())

            window.after(100, start_device_detection)

        try:
            self._run_gui_sync()

        finally:
            self.logger.info("GUI closed, stopping async tasks")

            if self._close_future:
                try:
                    await asyncio.wrap_future(self._close_future)
                except Exception as exc:
                    self.logger.error("Shutdown sequence raised: %s", exc, exc_info=True)

            if self.async_bridge:
                self.async_bridge.stop()

            await asyncio.sleep(0.1)

            self.logger.info("Shutdown complete")

    def _run_gui_sync(self) -> None:
        """
        Run Tkinter mainloop in main thread (guest mode pattern).
        This is NOT async - it blocks until the window is closed.
        """
        window = self.get_gui_window()

        if not window:
            self.logger.error("No GUI window available")
            return

        self.logger.info("Starting Tkinter mainloop in main thread")

        try:
            window.mainloop()
            self.logger.info("GUI mainloop completed")

        except Exception as e:
            self.logger.error("GUI mainloop error: %s", e, exc_info=True)
            self.system.running = False

    async def _preview_update_loop(self) -> None:
        interval = self.get_preview_update_interval()
        window = self.get_gui_window()

        while self.is_running():
            try:
                if window and window.winfo_exists():
                    window.after(0, self.update_preview)

                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                self.logger.debug("Preview update loop cancelled")
                raise
            except Exception as e:
                self.logger.debug("Preview update error: %s", e)
                break

    async def _setup_stdin_reader(self) -> Optional[asyncio.StreamReader]:
        if self._stdin_transport and not self._stdin_transport.is_closing() and self._stdin_reader is not None:
            return self._stdin_reader

        if sys.stdin.closed:
            self.logger.debug("stdin closed; skipping command listener setup")
            return None

        stream = getattr(sys.stdin, "buffer", sys.stdin)

        try:
            fileno = stream.fileno()
        except (AttributeError, io.UnsupportedOperation, ValueError) as exc:
            self.logger.warning("Command listener disabled (stdin has no file descriptor): %s", exc)
            return None

        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)

        pipe = None
        try:
            dup_fd = os.dup(fileno)
            pipe = os.fdopen(dup_fd, "rb", buffering=0)
            transport, _ = await loop.connect_read_pipe(lambda: protocol, pipe)
        except (PermissionError, NotImplementedError) as exc:
            if pipe is not None:
                pipe.close()
            self.logger.warning("Command listener disabled: %s", exc)
            return None
        except Exception as exc:
            if pipe is not None:
                pipe.close()
            self.logger.error("Failed to set up command listener: %s", exc, exc_info=True)
            return None

        self._stdin_transport = transport
        self._stdin_pipe = pipe
        self._stdin_reader = reader
        return reader

    async def _start_command_listener(self) -> None:
        """Set up stdin reader and start command listener (runs in background thread)."""
        stdin_reader = await self._setup_stdin_reader()
        if stdin_reader is None:
            self.logger.warning("Parent command interface unavailable; running in standalone GUI mode")
            return

        await self._command_listener(stdin_reader)

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

            except asyncio.CancelledError:
                self.logger.debug("Command listener cancelled")
                raise
            except Exception as e:
                StatusMessage.send("error", {"message": f"Command error: {e}"})
                self.logger.error("Command listener error: %s", e)
                break

        self.logger.info("Command listener stopped")
        self._close_command_stream()

    async def _handle_command_with_gui_sync(self, command_data: dict) -> bool:
        if not self.command_handler:
            self.logger.error("No command handler available")
            return True

        cmd = command_data.get("command")

        continue_running = await self.command_handler.handle_command(command_data)

        if not continue_running:
            return False

        if cmd in ("start_recording", "stop_recording") and self.async_bridge:
            self.async_bridge.call_in_gui(self.sync_recording_state)

        return True
