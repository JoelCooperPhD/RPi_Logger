
import asyncio
import logging
import subprocess
import tkinter as tk
from datetime import datetime
from tkinter import ttk, scrolledtext
from typing import TYPE_CHECKING, Dict, Optional

from Modules.base import TkinterGUIBase, TkinterMenuBase
from .widgets import AudioLevelMeter

if TYPE_CHECKING:
    from ...audio_system import AudioSystem

logger = logging.getLogger("TkinterGUI")


class TkinterGUI(TkinterGUIBase, TkinterMenuBase):

    def __init__(self, audio_system: 'AudioSystem', args):
        self.system = audio_system
        self.args = args

        # Initialize module-specific attributes before GUI framework
        self.meter_container: Optional[ttk.Frame] = None
        self.level_canvases: Dict[int, tk.Canvas] = {}  # One canvas per device
        self.log_text: Optional[scrolledtext.ScrolledText] = None
        self.log_handler = None
        self.device_active_vars: Dict[int, tk.BooleanVar] = {}
        self.level_meters: Dict[int, AudioLevelMeter] = {}
        self.recording_start_time: Optional[datetime] = None

        # Use template method for GUI initialization
        self.initialize_gui_framework(
            title="Audio System",
            default_width=600,
            default_height=400
        )

    def set_close_handler(self, handler):
        """Allow external code to override the window close handler"""
        self.root.protocol("WM_DELETE_WINDOW", handler)

    def populate_module_menus(self):
        pass

    def on_start_recording(self):
        self._start_recording()

    def on_stop_recording(self):
        asyncio.create_task(self._stop_recording_async())

    def _create_widgets(self):
        content_frame = self.create_standard_layout(logger_height=2, content_title="Audio Input Levels")
        content_frame.columnconfigure(0, weight=1)
        content_frame.rowconfigure(0, weight=1)

        self.meter_container = ttk.Frame(content_frame)
        self.meter_container.grid(row=0, column=0, sticky='nsew')
        self.meter_container.columnconfigure(0, weight=1)
        self.meter_container.rowconfigure(0, weight=1)

        self.meter_frame = content_frame

        if not self.system.initialized:
            self._show_waiting_message()

    def create_meter_canvases(self, on_resize_callback=None, on_toggle_device_callback=None):
        if not self.meter_container:
            return

        self._on_resize_callback = on_resize_callback
        self._on_toggle_device_callback = on_toggle_device_callback

        for widget in self.meter_container.winfo_children():
            widget.destroy()
        self.level_canvases.clear()

        selected_device_ids = sorted(self.system.selected_devices)

        if not selected_device_ids:
            label = ttk.Label(
                self.meter_container,
                text="No devices selected\nSelect devices from the Devices menu",
                font=('TkDefaultFont', 10),
                foreground='gray',
                justify='center'
            )
            label.grid(row=0, column=0, sticky='nsew')
            self.meter_container.columnconfigure(0, weight=1)
            self.meter_container.rowconfigure(0, weight=1)
            return

        self.meter_container.columnconfigure(0, weight=1)  # Single column (expandable width)

        for i, device_id in enumerate(selected_device_ids):
            self.meter_container.rowconfigure(i, weight=0)  # Fixed height for horizontal meter

            device_frame = ttk.Frame(self.meter_container)
            device_frame.grid(row=i, column=0, sticky='ew', pady=(0, 3))
            device_frame.columnconfigure(1, weight=1)  # Canvas column expands

            device_info = self.system.available_devices.get(device_id, {})
            device_name = device_info.get('name', f'Device {device_id}')
            label = ttk.Label(
                device_frame,
                text=f"Dev{device_id}:",
                font=('TkDefaultFont', 8, 'bold'),
                width=6
            )
            label.grid(row=0, column=0, sticky='w', padx=(0, 5))

            canvas = tk.Canvas(
                device_frame,
                width=200,  # Minimum width
                height=20,  # Short height for horizontal meter
                bg='#1a1a1a',
                highlightthickness=1,
                highlightbackground='gray'
            )
            canvas.grid(row=0, column=1, sticky='ew')

            if on_resize_callback:
                canvas.bind('<Configure>', lambda e, did=device_id: on_resize_callback(e, did))

            self.level_canvases[device_id] = canvas

            if device_id not in self.level_meters:
                self.level_meters[device_id] = AudioLevelMeter(peak_hold_time=2.0)

        logger.info("Created %d meter canvas(es)", len(selected_device_ids))

    def _start_recording(self):
        if self.system.recording:
            return

        if not self.system.selected_devices:
            logger.warning("No devices selected!")
            return

        if self.system.start_recording():
            self.recording_start_time = datetime.now()
            self.root.title(f"Audio System - ⬤ RECORDING")

            for device_id in self.device_active_vars.keys():
                device_info = self.system.available_devices[device_id]
                device_label = f"Device {device_id}: {device_info['name']} ({device_info['channels']}ch, {device_info['sample_rate']:.0f}Hz)"
                try:
                    self.sources_menu.entryconfig(device_label, state='disabled')
                except tk.TclError:
                    pass  # Menu item might not exist

            logger.info("Recording started")
        else:
            logger.error("Failed to start recording")

    def _stop_recording(self):
        if not self.system.recording:
            return

        asyncio.create_task(self._stop_recording_async())

    async def _stop_recording_async(self):
        await self.system.stop_recording()
        self.recording_start_time = None
        self.root.title("Audio System")

        # Re-enable device toggles after recording
        for device_id in self.device_active_vars.keys():
            device_info = self.system.available_devices[device_id]
            device_label = f"Device {device_id}: {device_info['name']} ({device_info['channels']}ch, {device_info['sample_rate']:.0f}Hz)"
            try:
                self.sources_menu.entryconfig(device_label, state='normal')
            except tk.TclError:
                pass  # Menu item might not exist

        logger.info("Recording stopped")

    def draw_level_meter(self, device_id: int):
        if device_id not in self.level_canvases:
            return

        canvas = self.level_canvases[device_id]

        if hasattr(self, 'module_content_visible_var') and not self.module_content_visible_var.get():
            canvas.delete('all')
            width = canvas.winfo_width()
            height = canvas.winfo_height()
            if width > 10 and height > 10:
                canvas.create_text(
                    width // 2, height // 2,
                    text="Hidden",
                    fill='gray', font=('TkDefaultFont', 7)
                )
            return

        if device_id not in self.level_meters:
            return

        meter = self.level_meters[device_id]

        if not meter.dirty:
            return

        canvas.delete('all')

        width = canvas.winfo_width()
        height = canvas.winfo_height()

        if width < 10 or height < 10:
            return

        rms_db, peak_db = meter.get_db_levels()

        db_min = -60
        db_max = 0
        green_threshold = -12
        yellow_threshold = -6

        padding_x = 5
        padding_y = 3
        meter_height = height - (2 * padding_y)
        meter_y = padding_y

        total_db_range = db_max - db_min
        green_width = ((green_threshold - db_min) / total_db_range) * (width - 2 * padding_x)
        yellow_width = ((yellow_threshold - green_threshold) / total_db_range) * (width - 2 * padding_x)
        red_width = ((db_max - yellow_threshold) / total_db_range) * (width - 2 * padding_x)

        x_offset = padding_x  # Start at left
        canvas.create_rectangle(
            x_offset, meter_y,
            x_offset + green_width, meter_y + meter_height,
            fill='#1a3a1a', outline='#2a4a2a'
        )
        x_offset += green_width
        canvas.create_rectangle(
            x_offset, meter_y,
            x_offset + yellow_width, meter_y + meter_height,
            fill='#3a3a1a', outline='#4a4a2a'
        )
        x_offset += yellow_width
        canvas.create_rectangle(
            x_offset, meter_y,
            x_offset + red_width, meter_y + meter_height,
            fill='#3a1a1a', outline='#4a2a2a'
        )

        rms_position = max(db_min, min(rms_db, db_max))
        rms_fraction = (rms_position - db_min) / total_db_range
        rms_width = rms_fraction * (width - 2 * padding_x)

        if rms_width > 0:
            x_offset = padding_x  # Start at left
            remaining = rms_width

            green_fill = min(remaining, green_width)
            if green_fill > 0:
                canvas.create_rectangle(
                    x_offset, meter_y,
                    x_offset + green_fill, meter_y + meter_height,
                    fill='#00ff00', outline=''
                )
                remaining -= green_fill
                x_offset += green_fill

            if remaining > 0:
                yellow_fill = min(remaining, yellow_width)
                if yellow_fill > 0:
                    canvas.create_rectangle(
                        x_offset, meter_y,
                        x_offset + yellow_fill, meter_y + meter_height,
                        fill='#ffff00', outline=''
                    )
                    remaining -= yellow_fill
                    x_offset += yellow_fill

            if remaining > 0:
                red_fill = min(remaining, red_width)
                if red_fill > 0:
                    canvas.create_rectangle(
                        x_offset, meter_y,
                        x_offset + red_fill, meter_y + meter_height,
                        fill='#ff0000', outline=''
                    )

        if peak_db > db_min:
            peak_position = max(db_min, min(peak_db, db_max))
            peak_fraction = (peak_position - db_min) / total_db_range
            peak_x = padding_x + (peak_fraction * (width - 2 * padding_x))

            canvas.create_line(
                peak_x, meter_y,
                peak_x, meter_y + meter_height,
                fill='#ffffff', width=2
            )

        # Clear dirty flag after drawing
        meter.clear_dirty()

    def populate_device_toggles(self):
        menu_size = self.sources_menu.index('end')
        if menu_size is not None:
            for _ in range(menu_size, -1, -1):
                try:
                    self.sources_menu.delete(menu_size)
                except:
                    pass
                menu_size -= 1

        self.device_active_vars.clear()

        for device_id in sorted(self.system.available_devices.keys()):
            device_info = self.system.available_devices[device_id]
            is_selected = device_id in self.system.selected_devices

            active_var = tk.BooleanVar(value=is_selected)
            self.device_active_vars[device_id] = active_var

            device_label = f"Device {device_id}: {device_info['name']} ({device_info['channels']}ch, {device_info['sample_rate']:.0f}Hz)"
            self.add_source_toggle(
                label=device_label,
                variable=active_var,
                command=lambda did=device_id, var=active_var: self._toggle_device(did, var.get())
            )

    def _toggle_device(self, device_id: int, active: bool):
        if self._on_toggle_device_callback:
            self._on_toggle_device_callback(device_id, active)

    def sync_recording_state(self):
        if self.system.recording:
            self.root.title("Audio System - ⬤ RECORDING")

            for device_id in self.device_active_vars.keys():
                device_info = self.system.available_devices.get(device_id, {})
                device_label = f"Device {device_id}: {device_info.get('name', 'Unknown')} ({device_info.get('channels', 0)}ch, {device_info.get('sample_rate', 0):.0f}Hz)"
                try:
                    self.sources_menu.entryconfig(device_label, state='disabled')
                except Exception:
                    pass
        else:
            self.root.title("Audio System")

            # Re-enable device toggles after recording
            for device_id in self.device_active_vars.keys():
                device_info = self.system.available_devices.get(device_id, {})
                device_label = f"Device {device_id}: {device_info.get('name', 'Unknown')} ({device_info.get('channels', 0)}ch, {device_info.get('sample_rate', 0):.0f}Hz)"
                try:
                    self.sources_menu.entryconfig(device_label, state='normal')
                except Exception:
                    pass

    def _show_waiting_message(self):
        for widget in self.meter_container.winfo_children():
            widget.destroy()

        label = ttk.Label(
            self.meter_container,
            text="Waiting for audio devices...\n\nChecking every 3 seconds",
            font=('TkDefaultFont', 12),
            foreground='gray',
            justify='center'
        )
        label.grid(row=0, column=0, sticky='nsew')
        self.meter_container.columnconfigure(0, weight=1)
        self.meter_container.rowconfigure(0, weight=1)

    def save_window_geometry_to_config(self):
        from pathlib import Path
        from Modules.base import gui_utils
        config_path = gui_utils.get_module_config_path(Path(__file__))
        gui_utils.save_window_geometry(self.root, config_path)


    def winfo_exists(self) -> bool:
        try:
            return self.root.winfo_exists()
        except Exception:
            return False
