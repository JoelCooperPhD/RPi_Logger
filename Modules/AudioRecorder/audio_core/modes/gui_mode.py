
import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Dict, Optional

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

    def create_gui(self) -> TkinterGUI:
        gui = TkinterGUI(self.system, self.system.args)

        gui.set_close_handler(self.on_closing)

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
                asyncio.create_task(self.capture_manager.start_capture_for_device(device_id))

            asyncio.create_task(self._update_loop())
            asyncio.create_task(self._display_update_loop())

    def create_tasks(self) -> list[asyncio.Task]:
        tasks = super().create_tasks()

        if self.system.initialized:
            for device_id in self.system.selected_devices:
                asyncio.create_task(self.capture_manager.start_capture_for_device(device_id))

            tasks.append(asyncio.create_task(self._update_loop()))
            tasks.append(asyncio.create_task(self._display_update_loop()))

        return tasks

    def update_preview(self) -> None:
        # This method is not used but required by base class
        pass

    def sync_recording_state(self) -> None:
        if self.gui:
            self.gui.sync_recording_state()

    async def cleanup(self) -> None:
        self.logger.info("Audio mode cleanup started")


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
                self.gui.create_meter_canvases(
                    on_resize_callback=self._on_canvas_resize,
                    on_toggle_device_callback=self._toggle_device
                )
                asyncio.create_task(self.capture_manager.start_capture_for_device(device_id))
        else:
            if self.system.deselect_device(device_id):
                self.logger.info("Deselected device %d", device_id)
                asyncio.create_task(self.capture_manager.stop_capture_for_device(device_id))
                self.gui.create_meter_canvases(
                    on_resize_callback=self._on_canvas_resize,
                    on_toggle_device_callback=self._toggle_device
                )

    async def _display_update_loop(self):
        while self.is_running() and self.gui:
            try:
                if self.gui:
                    for device_id in list(self.gui.level_canvases.keys()):
                        self.gui.draw_level_meter(device_id)

                await asyncio.sleep(0.05)

            except Exception as e:
                self.logger.error("Display update loop error: %s", e)
                await asyncio.sleep(0.05)

    async def _update_loop(self):
        usb_poll_counter = 0
        usb_poll_interval_cycles = int(USB_POLL_INTERVAL / 0.5)  # Convert to 500ms cycles

        while self.is_running() and self.gui:
            try:
                usb_poll_counter += 1
                if usb_poll_counter >= usb_poll_interval_cycles:
                    usb_poll_counter = 0

                    usb_devices = await DeviceDiscovery.get_usb_audio_devices()

                    if usb_devices != self.current_usb_devices:
                        added = set(usb_devices) - set(self.current_usb_devices)
                        removed = set(self.current_usb_devices) - set(usb_devices)

                        if added or removed:
                            self.system.available_devices = await DeviceDiscovery.get_audio_input_devices()

                            new_device_ids = set(self.system.available_devices.keys()) - self.system._known_devices
                            self.system._known_devices = set(self.system.available_devices.keys())

                            if self.system.auto_select_new and new_device_ids:
                                for device_id in new_device_ids:
                                    self.system.select_device(device_id)
                                    self.logger.info("Auto-selected new device %d", device_id)

                            missing_selected = {
                                device_id
                                for device_id in list(self.system.selected_devices)
                                if device_id not in self.system.available_devices
                            }
                            if missing_selected:
                                for device_id in missing_selected:
                                    self.system.deselect_device(device_id)
                                    await self.capture_manager.stop_capture_for_device(device_id)

                                if self.system.recording:
                                    await self.system.stop_recording()
                                    self.logger.warning("Recording stopped (device removed)")

                                if self.gui:
                                    self.gui.create_meter_canvases(
                                        on_resize_callback=self._on_canvas_resize,
                                        on_toggle_device_callback=self._toggle_device
                                    )

                            if self.gui:
                                self.gui.populate_device_toggles()

                            self.current_usb_devices = usb_devices

                await asyncio.sleep(0.5)

            except Exception as e:
                self.logger.error("Update loop error: %s", e)
                await asyncio.sleep(0.5)
