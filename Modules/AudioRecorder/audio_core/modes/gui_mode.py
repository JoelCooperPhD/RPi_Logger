
import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Dict, Optional

from Modules.base import AsyncTaskManager
from Modules.base.modes import BaseGUIMode
from ..audio_utils import DeviceDiscovery
from ..constants import USB_POLL_INTERVAL
from ..commands import CommandHandler
from ..interfaces.gui import TkinterGUI
from ..display import AudioCaptureManager

if TYPE_CHECKING:
    from ..audio_system import AudioSystem


class GUIMode(BaseGUIMode):

    def __init__(self, audio_system: 'AudioSystem', enable_commands: bool = False):
        super().__init__(audio_system, enable_commands)
        self.capture_manager: Optional[AudioCaptureManager] = None
        self.current_usb_devices: Dict[int, str] = {}
        self._display_loop_stopped = False
        self._bridge_tasks = AsyncTaskManager("AudioGUIModeTasks", self.logger)
        self._ui_service_task: Optional[asyncio.Task] = None

    def create_gui(self) -> TkinterGUI:
        gui = TkinterGUI(self.system, self.system.args)

        # Set GUI reference in system so AudioHandler can update meters during recording
        self.system.gui = gui

        if self.system.available_devices:
            self.capture_manager = AudioCaptureManager(gui, self.system.available_devices)

            gui.populate_device_toggles()

            gui.create_meter_canvases(
                on_resize_callback=self._on_canvas_resize,
                on_toggle_device_callback=self._toggle_device
            )

        return gui

    def create_command_handler(self, gui: TkinterGUI) -> CommandHandler:
        return CommandHandler(self.system, gui=gui, mode=self)

    async def on_async_bridge_started(self) -> None:
        if self.capture_manager and self.system.selected_devices:
            for device_id in self.system.selected_devices:
                await self.capture_manager.start_capture_for_device(device_id)

        if self.capture_manager:
            await self._start_ui_service_loop()

    async def on_auto_start_recording(self) -> None:
        if await self.system.start_recording():
            if self.gui:
                self.gui.recording_start_time = datetime.now()
                self.gui.root.title("Audio System - ⬤ RECORDING (auto-started)")
            self.logger.info("Recording auto-started")

    async def on_devices_connected(self) -> None:
        if self.gui and self.gui.root.winfo_exists():
            self.capture_manager = AudioCaptureManager(self.gui, self.system.available_devices)
            self.gui.populate_device_toggles()
            self.gui.create_meter_canvases(
                on_resize_callback=self._on_canvas_resize,
                on_toggle_device_callback=self._toggle_device
            )
            self.gui.root.title(f"Audio System - {len(self.system.available_devices)} Devices")

            for device_id in self.system.selected_devices:
                await self.capture_manager.start_capture_for_device(device_id)

            await self._start_ui_service_loop()

    def update_preview(self) -> None:
        # This method is not used but required by base class
        pass

    def enable_preview_loop(self) -> bool:
        return False

    def sync_recording_state(self) -> None:
        if self.gui:
            self.gui.sync_recording_state()

    def sync_cleanup(self) -> None:
        """Synchronous cleanup - forcefully kill audio processes."""
        self.logger.info("Audio sync cleanup - stopping display loop and killing processes")
        self._display_loop_stopped = True

        if self.capture_manager:
            import signal
            for device_id, process in list(self.capture_manager.audio_processes.items()):
                try:
                    process.kill()
                    self.logger.info("Killed arecord for device %d (pid %s)", device_id, process.pid)
                except Exception as e:
                    self.logger.debug("Error killing process for device %d: %s", device_id, e)

    def on_closing(self) -> None:
        self.logger.info("Audio GUI closing - stopping display loop immediately")
        self._display_loop_stopped = True

        use_sync_shutdown = (
            self.async_bridge
            and self.async_bridge.loop is not None
            and (not self.capture_manager or not self.capture_manager.audio_processes)
        )

        if use_sync_shutdown:
            self.logger.info("No active audio capture processes; using synchronous shutdown path")
            bridge = self.async_bridge
            self.async_bridge = None
            try:
                super().on_closing()
            finally:
                self.async_bridge = bridge
            return

        super().on_closing()

    async def cleanup(self) -> None:
        self.logger.info("Audio mode cleanup started")
        self._display_loop_stopped = True

        await self._shutdown_bridge_tasks()

        if self.capture_manager:
            await self.capture_manager.stop_all_captures()

        if self.system.recording:
            await self.system.stop_recording()

        if self.gui:
            self.gui.destroy_window()

        self.logger.info("Audio mode cleanup completed")

    def _on_canvas_resize(self, event, device_id: int):
        if self.gui and device_id in self.gui.level_meters:
            self.gui.level_meters[device_id].dirty = True
            self.gui.draw_level_meter(device_id)

    def _toggle_device(self, device_id: int, active: bool):
        if active:
            if self.system.select_device(device_id):
                self.logger.info("Selected device %d", device_id)
                if self.async_bridge:
                    self.async_bridge.call_in_gui(
                        self.gui.create_meter_canvases,
                        on_resize_callback=self._on_canvas_resize,
                        on_toggle_device_callback=self._toggle_device
                    )
                if self.capture_manager:
                    self._schedule_on_bridge(
                        lambda did=device_id: self.capture_manager.start_capture_for_device(did),
                        name=f"capture_start_{device_id}"
                    )
        else:
            if self.system.deselect_device(device_id):
                self.logger.info("Deselected device %d", device_id)
                if self.capture_manager:
                    self._schedule_on_bridge(
                        lambda did=device_id: self.capture_manager.stop_capture_for_device(did),
                        name=f"capture_stop_{device_id}"
                    )
                if self.async_bridge:
                    self.async_bridge.call_in_gui(
                        self.gui.create_meter_canvases,
                        on_resize_callback=self._on_canvas_resize,
                        on_toggle_device_callback=self._toggle_device
                    )

    def _schedule_on_bridge(self, coro_factory, *, name: str) -> None:
        if not self.async_bridge or self.async_bridge.loop is None:
            self.logger.debug("Bridge unavailable for task %s", name)
            return

        def _submit() -> None:
            try:
                self._bridge_tasks.create(coro_factory(), name=name)
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.error("Failed to schedule %s: %s", name, exc, exc_info=True)

        self.async_bridge.loop.call_soon_threadsafe(_submit)

    async def _start_ui_service_loop(self) -> None:
        if self._ui_service_task and not self._ui_service_task.done():
            return

        self._ui_service_task = self._bridge_tasks.create(
            self._ui_service_loop(),
            name="audio_ui_service"
        )

    async def _ui_service_loop(self) -> None:
        loop = asyncio.get_running_loop()
        display_interval = 0.05
        preview_interval = max(0.05, self.get_preview_update_interval())
        usb_interval = USB_POLL_INTERVAL

        next_display = loop.time()
        next_preview = loop.time()
        next_usb = loop.time()

        self.logger.info("Audio UI service loop started")

        try:
            while self.is_running() and self.gui and not self._display_loop_stopped:
                now = loop.time()

                if now >= next_display:
                    await self._refresh_level_meters()
                    next_display = now + display_interval

                if now >= next_preview:
                    await self._trigger_preview_update()
                    next_preview = now + preview_interval

                if now >= next_usb:
                    await self._poll_usb_devices()
                    next_usb = now + usb_interval

                sleep_until = min(next_display, next_preview, next_usb)
                sleep_duration = max(0.01, sleep_until - loop.time())
                await asyncio.sleep(sleep_duration)

        except asyncio.CancelledError:
            self.logger.debug("Audio UI service loop cancelled")
            raise
        except Exception as e:
            self.logger.error("Audio UI service loop error: %s", e, exc_info=True)
        finally:
            self.logger.info("Audio UI service loop stopped")

    async def _shutdown_bridge_tasks(self) -> None:
        if not self.async_bridge or self.async_bridge.loop is None:
            self._ui_service_task = None
            return

        future = self.async_bridge.run_coroutine(self._bridge_tasks.shutdown())

        try:
            await asyncio.wrap_future(future)
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.error("Bridge task shutdown error: %s", exc, exc_info=True)
        finally:
            self._ui_service_task = None

        if self.capture_manager:
            capture_future = self.async_bridge.run_coroutine(self.capture_manager.shutdown_tasks())
            try:
                await asyncio.wrap_future(capture_future)
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.error("Capture manager shutdown error: %s", exc, exc_info=True)

    async def _refresh_level_meters(self) -> None:
        if not self.gui or self._display_loop_stopped or not self.async_bridge:
            return

        def _draw_all_level_meters() -> None:
            if not self.gui or self._display_loop_stopped:
                return
            if not hasattr(self.gui, 'root') or not self.gui.root.winfo_exists():
                return
            for device_id in list(self.gui.level_canvases.keys()):
                self.gui.draw_level_meter(device_id)

        self.async_bridge.call_in_gui(_draw_all_level_meters)

    async def _trigger_preview_update(self) -> None:
        if not self.gui or self._display_loop_stopped or not self.async_bridge:
            return

        self.async_bridge.call_in_gui(self.update_preview)

    async def _poll_usb_devices(self) -> None:
        try:
            usb_devices = await DeviceDiscovery.get_usb_audio_devices()
        except Exception as exc:
            self.logger.debug("USB poll failed: %s", exc)
            return

        if usb_devices == self.current_usb_devices:
            return

        added = set(usb_devices) - set(self.current_usb_devices)
        removed = set(self.current_usb_devices) - set(usb_devices)

        try:
            self.system.available_devices = await DeviceDiscovery.get_audio_input_devices()
        except Exception as exc:
            self.logger.error("Failed to refresh audio devices: %s", exc)
            return

        new_device_ids = set(self.system.available_devices.keys()) - self.system._known_devices
        self.system._known_devices = set(self.system.available_devices.keys())

        if self.system.auto_select_new and new_device_ids:
            for device_id in new_device_ids:
                if self.system.select_device(device_id):
                    self.logger.info("Auto-selected new device %d", device_id)

        missing_selected = {
            device_id
            for device_id in list(self.system.selected_devices)
            if device_id not in self.system.available_devices
        }

        if missing_selected:
            for device_id in missing_selected:
                self.system.deselect_device(device_id)
                if self.capture_manager:
                    await self.capture_manager.stop_capture_for_device(device_id)

            if self.system.recording:
                await self.system.stop_recording()
                self.logger.warning("Recording stopped (device removed)")

            if self.gui and self.async_bridge:
                self.async_bridge.call_in_gui(
                    self.gui.create_meter_canvases,
                    on_resize_callback=self._on_canvas_resize,
                    on_toggle_device_callback=self._toggle_device
                )

        if self.capture_manager and added:
            for device_id in sorted(new_device_ids):
                if device_id in self.system.selected_devices:
                    await self.capture_manager.start_capture_for_device(device_id)

        if self.gui and self.async_bridge:
            self.async_bridge.call_in_gui(self.gui.populate_device_toggles)

        self.current_usb_devices = usb_devices
