import asyncio
from rpi_logger.core.logging_utils import get_module_logger
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Dict, Callable
from math import ceil

if TYPE_CHECKING:
    from ...drt_system import DRTSystem
    from ...drt_handler import DRTHandler


class SDRTConfigWindow:

    def __init__(self, drt_system: 'DRTSystem', async_bridge, parent=None):
        self.logger = get_module_logger("SDRTConfigWindow")
        self.system = drt_system
        self.async_bridge = async_bridge
        self.parent = parent
        self.config_window: Optional[tk.Toplevel] = None
        self.current_port: Optional[str] = None

        self.settings = {
            "lowerISI": tk.StringVar(),
            "upperISI": tk.StringVar(),
            "stimDur": tk.StringVar(),
            "intensity": tk.StringVar()
        }

    def show_for_device(self, port: str):
        if self.config_window and self.config_window.winfo_exists():
            self.config_window.focus_force()
            return

        self.current_port = port
        handler = self.system.get_device_handler(port)

        if not handler:
            logger.error(f"No device handler found for port {port}")
            return

        self._create_window(port, handler)

    def show_device_selector(self):
        devices = self.system.get_connected_devices()

        if not devices:
            logger.warning("No devices connected to configure")
            return

        if len(devices) == 1:
            port = list(devices.keys())[0]
            self.show_for_device(port)
            return

        selector_win = tk.Toplevel()
        selector_win.title("Select Device to Configure")
        selector_win.grab_set()
        selector_win.resizable(False, False)

        main_frame = ttk.LabelFrame(selector_win, text="Available sDRT Devices", padding=10)
        main_frame.grid(row=0, column=0, padx=10, pady=10, sticky='nsew')

        ttk.Label(main_frame, text="Select a device to configure:").grid(
            row=0, column=0, columnspan=2, pady=(0, 10)
        )

        for idx, (port, device) in enumerate(devices.items()):
            device_name = device.config.device_name
            btn = ttk.Button(
                main_frame,
                text=f"{port} - {device_name}",
                command=lambda p=port: self._on_device_selected(selector_win, p)
            )
            btn.grid(row=idx+1, column=0, pady=2, padx=5, sticky='ew')

        main_frame.columnconfigure(0, weight=1)

        selector_win.update_idletasks()
        selector_win.geometry(f"+{selector_win.winfo_screenwidth()//2 - selector_win.winfo_width()//2}+"
                            f"{selector_win.winfo_screenheight()//2 - selector_win.winfo_height()//2}")

    def _on_device_selected(self, selector_win: tk.Toplevel, port: str):
        selector_win.destroy()
        self.show_for_device(port)

    def _create_window(self, port: str, handler: 'DRTHandler'):
        master = self.parent
        if master is None:
            master = self._resolve_default_root()

        self.config_window = tk.Toplevel(master)
        self.config_window.withdraw()
        self.config_window.title(f"Configure sDRT Device - {port}")
        self.config_window.resizable(False, False)
        if master is not None:
            try:
                self.config_window.transient(master)
            except tk.TclError:
                pass

        config_frame = ttk.LabelFrame(self.config_window, text="Device Configuration", padding=10)
        config_frame.grid(row=0, column=0, sticky='nsew', pady=5, padx=5)
        config_frame.grid_columnconfigure(1, weight=1)

        ttk.Label(config_frame, text=f"Device: sDRT on {port}").grid(
            row=0, column=0, columnspan=3, sticky='w', pady=(0, 10)
        )

        ttk.Separator(config_frame, orient='horizontal').grid(
            row=1, column=0, columnspan=3, sticky='ew', pady=5
        )

        ttk.Label(config_frame, text="Upper ISI (ms):").grid(row=2, column=0, sticky='w', pady=2)
        first_field = ttk.Entry(config_frame, textvariable=self.settings['upperISI'], width=10)
        first_field.grid(
            row=2, column=2, sticky='w', padx=(5, 0)
        )

        ttk.Label(config_frame, text="Lower ISI (ms):").grid(row=3, column=0, sticky='w', pady=2)
        ttk.Entry(config_frame, textvariable=self.settings['lowerISI'], width=10).grid(
            row=3, column=2, sticky='w', padx=(5, 0)
        )

        ttk.Label(config_frame, text="Stimulus Duration (ms):").grid(row=4, column=0, sticky='w', pady=2)
        ttk.Entry(config_frame, textvariable=self.settings['stimDur'], width=10).grid(
            row=4, column=2, sticky='w', padx=(5, 0)
        )

        ttk.Label(config_frame, text="Stimulus Intensity (%):").grid(row=5, column=0, sticky='w', pady=2)
        ttk.Entry(config_frame, textvariable=self.settings['intensity'], width=10).grid(
            row=5, column=2, sticky='w', padx=(5, 0)
        )

        ttk.Separator(config_frame, orient='horizontal').grid(
            row=6, column=0, columnspan=3, sticky='ew', pady=5
        )

        button_frame = ttk.Frame(config_frame)
        button_frame.grid(row=7, column=0, columnspan=3, pady=(5, 0))

        ttk.Button(
            button_frame,
            text="Upload to Device",
            command=lambda: self._upload_to_device(handler)
        ).grid(row=0, column=0, padx=5, sticky='ew')

        preset_frame = ttk.LabelFrame(self.config_window, text="Standard Presets", padding=10)
        preset_frame.grid(row=1, column=0, sticky='nsew', pady=5, padx=5)
        preset_frame.grid_columnconfigure(0, weight=1)

        ttk.Button(
            preset_frame,
            text="ISO Standard Configuration",
            command=lambda: self._set_iso_preset(handler)
        ).grid(row=0, column=0, pady=5, padx=20, sticky='ew')

        if self.async_bridge:
            self.async_bridge.run_coroutine(self._load_current_config(handler))
        else:
            logger.error("No async_bridge available to load config")

        self.config_window.update_idletasks()
        self.config_window.geometry(f"+{self.config_window.winfo_screenwidth()//2 - self.config_window.winfo_width()//2}+"
                                   f"{self.config_window.winfo_screenheight()//2 - self.config_window.winfo_height()//2}")
        self.config_window.deiconify()
        self.config_window.lift()
        self.config_window.focus_force()
        first_field.focus_set()
        self.config_window.grab_set()

    def _resolve_default_root(self):
        return getattr(tk, "_default_root", None)

    async def _load_current_config(self, handler: 'DRTHandler'):
        try:
            config_data = await handler.get_device_config()
            if config_data:
                self._update_fields(config_data)
        except Exception as e:
            logger.warning(f"Could not load current device configuration: {e}")

    def _update_fields(self, config_data: Dict):
        if 'lowerISI' in config_data:
            self.settings['lowerISI'].set(str(config_data['lowerISI']))
        if 'upperISI' in config_data:
            self.settings['upperISI'].set(str(config_data['upperISI']))
        if 'stimDur' in config_data:
            self.settings['stimDur'].set(str(config_data['stimDur']))
        if 'intensity' in config_data:
            intensity_percent = int(config_data['intensity'] / 2.55)
            self.settings['intensity'].set(str(intensity_percent))

    @staticmethod
    def _filter_entry(val: str, default_value: int, lower: int, upper: int) -> int:
        if val.isnumeric():
            val_int = int(val)
            if lower <= val_int <= upper:
                return val_int
        return default_value

    def _upload_to_device(self, handler: 'DRTHandler'):
        try:
            lower_isi = self._filter_entry(self.settings['lowerISI'].get(), 3000, 0, 65535)
            upper_isi = self._filter_entry(self.settings['upperISI'].get(), 5000, lower_isi, 65535)
            intensity_percent = self._filter_entry(self.settings['intensity'].get(), 100, 0, 100)
            intensity = ceil(intensity_percent * 2.55)
            stim_dur = self._filter_entry(self.settings['stimDur'].get(), 1000, 0, 65535)

            if self.async_bridge:
                self.async_bridge.run_coroutine(self._send_config_and_reload(
                    handler, lower_isi, upper_isi, intensity, stim_dur
                ))
            else:
                logger.error("No async_bridge available to upload config")

            logger.info(f"Uploading configuration to device on {self.current_port}")
        except Exception as e:
            logger.error(f"Error uploading configuration: {e}", exc_info=True)

    async def _reload_config(self, handler: 'DRTHandler'):
        self._clear_settings()
        await asyncio.sleep(0.5)
        await self._load_current_config(handler)

    async def _send_config_and_reload(
        self,
        handler: 'DRTHandler',
        lower_isi: int,
        upper_isi: int,
        intensity: int,
        stim_dur: int
    ):
        try:
            await handler.set_lower_isi(lower_isi)
            await handler.set_upper_isi(upper_isi)
            await handler.set_intensity(intensity)
            await handler.set_stimulus_duration(stim_dur)
            logger.info("Configuration uploaded successfully")
            await self._reload_config(handler)
        except Exception as e:
            logger.error(f"Failed to send configuration: {e}", exc_info=True)

    def _set_iso_preset(self, handler: 'DRTHandler'):
        if self.async_bridge:
            self.async_bridge.run_coroutine(self._send_iso_preset(handler))
        else:
            logger.error("No async_bridge available to set ISO preset")

    async def _send_iso_preset(self, handler: 'DRTHandler'):
        try:
            await handler.set_iso_params()
            logger.info("ISO standard configuration sent to device")
            await self._reload_config(handler)
        except Exception as e:
            logger.error(f"Failed to send ISO preset: {e}", exc_info=True)

    def _clear_settings(self):
        for setting in self.settings.values():
            setting.set("")
