#!/usr/bin/env python3
"""
GUI mode with tkinter interface.

Provides a graphical control panel for audio recording operations.
Matches the layout and structure of the cameras module GUI.
"""

import asyncio
import logging
import re
import subprocess
import sys
import tkinter as tk
from datetime import datetime
from tkinter import ttk, scrolledtext
from typing import TYPE_CHECKING, Dict, Optional, List, Tuple
import struct
import math

from .base_mode import BaseMode
from ..audio_utils import DeviceDiscovery
from ..constants import USB_POLL_INTERVAL
from ..commands import CommandHandler, CommandMessage, StatusMessage

if TYPE_CHECKING:
    from ..audio_system import AudioSystem


class AudioLevelMeter:
    """Simple audio level meter for real-time monitoring.

    Tracks RMS and peak levels for horizontal bar meter display.
    """

    def __init__(self, peak_hold_time: float = 2.0):
        """Initialize audio level meter.

        Args:
            peak_hold_time: How long to hold peak indicator (seconds)
        """
        self.current_rms = 0.0
        self.current_peak = 0.0
        self.peak_hold = 0.0
        self.peak_hold_timestamp = 0.0
        self.peak_hold_time = peak_hold_time
        self.dirty = False

    def add_samples(self, samples: List[float], timestamp: float):
        """Process audio samples and update levels.

        Args:
            samples: List of normalized audio samples (-1.0 to 1.0)
            timestamp: Timestamp when samples were captured
        """
        if not samples:
            return

        # Calculate RMS (Root Mean Square) for current chunk
        rms = math.sqrt(sum(s * s for s in samples) / len(samples))

        # Calculate peak (maximum absolute value)
        peak = max(abs(s) for s in samples)

        # Update current levels
        self.current_rms = rms
        self.current_peak = peak

        # Update peak hold
        if peak > self.peak_hold:
            self.peak_hold = peak
            self.peak_hold_timestamp = timestamp

        # Expire old peak hold
        if timestamp - self.peak_hold_timestamp > self.peak_hold_time:
            self.peak_hold = peak

        self.dirty = True

    def get_db_levels(self) -> Tuple[float, float]:
        """Get current audio levels in dB.

        Returns:
            Tuple of (rms_db, peak_db)
        """
        # Convert to dB (with floor at -60 dB to avoid log(0))
        rms_db = 20 * math.log10(max(self.current_rms, 1e-6))
        peak_db = 20 * math.log10(max(self.peak_hold, 1e-6))

        return (rms_db, peak_db)

    def clear_dirty(self):
        """Clear the dirty flag."""
        self.dirty = False


class GUIMode(BaseMode):
    """GUI mode with tkinter control panel (matching cameras module style)."""

    def __init__(self, audio_system: 'AudioSystem', enable_commands: bool = False):
        super().__init__(audio_system)
        self.window: Optional[tk.Tk] = None
        self.current_usb_devices: Dict[int, str] = {}
        self.recording_start_time: Optional[datetime] = None
        self.enable_commands = enable_commands
        self.command_handler = None  # Will be initialized after window is created
        self.command_task = None

        # UI Widgets
        self.meter_container: Optional[ttk.Frame] = None
        self.level_canvases: Dict[int, tk.Canvas] = {}  # One canvas per device
        self.log_text: Optional[scrolledtext.ScrolledText] = None
        self.log_handler = None

        # Devices menu toggle states
        self.meter_visible_var: Optional[tk.BooleanVar] = None
        self.device_active_vars: Dict[int, tk.BooleanVar] = {}

        # Audio level meter display (one per device)
        self.level_meters: Dict[int, AudioLevelMeter] = {}
        self.audio_processes: Dict[int, asyncio.subprocess.Process] = {}
        self.audio_sample_rate = 8000  # Capture at 8kHz for visualization

        # Background task tracking for error monitoring
        self.background_tasks: List[asyncio.Task] = []

    def _task_done_callback(self, task: asyncio.Task) -> None:
        """
        Callback for background tasks to log exceptions.

        Args:
            task: Completed asyncio task
        """
        try:
            # This will raise if the task failed with an exception
            task.result()
        except asyncio.CancelledError:
            # Normal cancellation, don't log
            pass
        except Exception as e:
            self.logger.exception("Background task failed: %s", e)

    def _create_window(self):
        """Create and configure the main tkinter window."""
        self.window = tk.Tk()
        self.window.title("Audio System")

        # Window dimensions (matching cameras module style)
        log_height = 100  # Logger frame height
        menu_height = 25  # Menu bar height
        meter_height = 120  # Level meter height

        # Set minimum size for narrow, compact window
        min_width = 300
        min_height = meter_height + log_height + menu_height
        self.window.minsize(min_width, min_height)

        # Apply window geometry (from master logger) or use calculated size
        if hasattr(self.system.args, 'window_geometry') and self.system.args.window_geometry:
            self.window.geometry(self.system.args.window_geometry)
            self.logger.info("Applied window geometry from master: %s", self.system.args.window_geometry)
        else:
            # Start with minimal width, moderate height
            window_width = 400
            window_height = min_height + 50  # Add some padding
            self.window.geometry(f"{window_width}x{window_height}")

        # Set window protocol for proper cleanup
        self.window.protocol("WM_DELETE_WINDOW", self._on_closing)

        # Create menu bar
        self._create_menu_bar()

        # Create widgets
        self._create_widgets()

        self.logger.info("Audio GUI initialized")

    def _create_menu_bar(self):
        """Create menu bar with File, View, Controls menus (matching cameras module)."""
        menubar = tk.Menu(self.window)
        self.window.config(menu=menubar)

        # File Menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Open Output Directory", command=self._open_output_dir)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self._on_closing)

        # Devices Menu (for device selection and meter visibility)
        devices_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Devices", menu=devices_menu)

        # Add "Show Level Meters" toggle
        self.meter_visible_var = tk.BooleanVar(value=True)
        devices_menu.add_checkbutton(
            label="Show Level Meters",
            variable=self.meter_visible_var,
            command=self._toggle_meter_visibility
        )
        devices_menu.add_separator()
        # Device toggles will be added dynamically by _populate_device_toggles()

        # Controls Menu
        controls_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Controls", menu=controls_menu)
        controls_menu.add_command(label="▶ Start Recording", command=self._start_recording)
        controls_menu.add_command(label="⏹ Stop Recording", command=self._stop_recording)

        # Store menu references
        self.file_menu = file_menu
        self.devices_menu = devices_menu
        self.controls_menu = controls_menu

    def _create_widgets(self):
        """Create GUI widgets (matching cameras module layout)."""
        # Main container
        main_frame = ttk.Frame(self.window, padding="5")
        main_frame.grid(row=0, column=0, sticky='nsew')
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)

        # Configure main_frame grid: level meter area + log feed
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(0, weight=1)  # Level meter area (expandable)
        main_frame.rowconfigure(1, weight=0)  # Log feed (fixed, 3 lines)

        # === LEVEL METERS (top, expandable) ===
        meter_frame = ttk.LabelFrame(main_frame, text="Audio Input Levels", padding="3")
        meter_frame.grid(row=0, column=0, sticky='nsew', pady=(0, 5))
        meter_frame.columnconfigure(0, weight=1)
        meter_frame.rowconfigure(0, weight=1)

        # Container for meter canvases (side-by-side layout)
        self.meter_container = ttk.Frame(meter_frame)
        self.meter_container.grid(row=0, column=0, sticky='nsew')
        # Individual meter canvases will be created dynamically in _create_meter_canvases()

        # === LOGGER FEED (bottom, 3 lines) ===
        log_frame = ttk.LabelFrame(main_frame, text="Logger", padding="3")
        log_frame.grid(row=1, column=0, sticky='ew')
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=0)

        # Scrolled text widget for log feed (3 lines high, scrollable)
        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            height=3,
            wrap=tk.WORD,
            font=('TkFixedFont', 8),
            bg='#f5f5f5',
            fg='#333333'
        )
        self.log_text.grid(row=0, column=0, sticky='ew')
        self.log_text.config(state='disabled')  # Read-only

        # Set up logging handler to feed into this widget
        self._setup_log_handler()

    def _setup_log_handler(self):
        """Set up logging handler to feed logs into the GUI text widget."""
        class TextHandler(logging.Handler):
            def __init__(self, text_widget):
                super().__init__()
                self.text_widget = text_widget
                # Format logs nicely
                self.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                                                   datefmt='%H:%M:%S'))

            def emit(self, record):
                msg = self.format(record) + '\n'
                # Schedule GUI update on main thread
                self.text_widget.after(0, self._append_log, msg)

            def _append_log(self, msg):
                self.text_widget.config(state='normal')
                self.text_widget.insert(tk.END, msg)
                self.text_widget.see(tk.END)  # Auto-scroll
                # Limit buffer to last 500 lines
                lines = int(self.text_widget.index('end-1c').split('.')[0])
                if lines > 500:
                    self.text_widget.delete('1.0', f'{lines-500}.0')
                self.text_widget.config(state='disabled')

        # Add handler to root logger
        text_handler = TextHandler(self.log_text)
        text_handler.setLevel(logging.INFO)
        logging.getLogger().addHandler(text_handler)
        self.log_handler = text_handler

    def _open_output_dir(self):
        """Open output directory in file manager."""
        output_dir = self.system.session_dir.parent
        try:
            subprocess.Popen(['xdg-open', str(output_dir)])
            self.logger.info("Opened output directory: %s", output_dir)
        except Exception as e:
            self.logger.error("Failed to open output directory: %s", e)

    def _create_meter_canvases(self):
        """Create meter canvas widgets for selected devices (side by side).

        Follows the pattern from cameras module for dynamic canvas creation.
        Each selected device gets its own vertical meter canvas.
        """
        if not self.meter_container:
            return

        # Clear existing canvases
        for canvas in self.level_canvases.values():
            canvas.destroy()
        self.level_canvases.clear()

        # Get sorted list of selected devices
        selected_device_ids = sorted(self.system.selected_devices)

        if not selected_device_ids:
            # No devices selected - show message
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

        # Configure meter_container grid
        self.meter_container.rowconfigure(0, weight=0)  # Label row (fixed)
        self.meter_container.rowconfigure(1, weight=1)  # Canvas row (expandable)

        # Create canvas for each selected device (side by side)
        for i, device_id in enumerate(selected_device_ids):
            # Configure column to expand equally
            self.meter_container.columnconfigure(i, weight=1)

            # Device label above canvas
            device_info = self.system.available_devices.get(device_id, {})
            device_name = device_info.get('name', f'Device {device_id}')
            label = ttk.Label(
                self.meter_container,
                text=f"Device {device_id}: {device_name}",
                font=('TkDefaultFont', 9, 'bold')
            )
            label.grid(row=0, column=i, sticky='w', padx=5, pady=(5, 2))

            # Meter canvas - vertical meter, scales with window
            canvas = tk.Canvas(
                self.meter_container,
                width=80,  # Narrow width for vertical meter
                height=100,  # Minimum height
                bg='#1a1a1a',
                highlightthickness=1,
                highlightbackground='gray'
            )
            canvas.grid(row=1, column=i, sticky='nsew',
                       padx=(0, 5 if i < len(selected_device_ids)-1 else 0))

            # Bind resize event for this canvas
            canvas.bind('<Configure>', lambda e, did=device_id: self._on_canvas_resize(e, did))

            # Store canvas reference
            self.level_canvases[device_id] = canvas

            # Create AudioLevelMeter for this device if it doesn't exist
            if device_id not in self.level_meters:
                self.level_meters[device_id] = AudioLevelMeter(peak_hold_time=2.0)

        self.logger.info("Created %d meter canvas(es)", len(selected_device_ids))

    def _start_recording(self):
        """Start recording."""
        if self.system.recording:
            return

        # Check if devices are selected
        if not self.system.selected_devices:
            self.logger.warning("No devices selected!")
            return

        # Start recording
        if self.system.start_recording():
            self.recording_start_time = datetime.now()
            self.window.title(f"Audio System - ⬤ RECORDING")

            # Disable device toggles during recording (safety)
            for device_id in self.device_active_vars.keys():
                device_info = self.system.available_devices[device_id]
                device_label = f"Device {device_id}: {device_info['name']} ({device_info['channels']}ch, {device_info['sample_rate']:.0f}Hz)"
                try:
                    self.devices_menu.entryconfig(device_label, state='disabled')
                except tk.TclError:
                    pass  # Menu item might not exist

            self.logger.info("Recording started")
        else:
            self.logger.error("Failed to start recording")

    def _stop_recording(self):
        """Stop recording."""
        if not self.system.recording:
            return

        # Stop recording asynchronously
        asyncio.create_task(self._stop_recording_async())

    async def _stop_recording_async(self):
        """Stop recording asynchronously."""
        await self.system.stop_recording()
        self.recording_start_time = None
        self.window.title("Audio System")

        # Re-enable device toggles after recording
        for device_id in self.device_active_vars.keys():
            device_info = self.system.available_devices[device_id]
            device_label = f"Device {device_id}: {device_info['name']} ({device_info['channels']}ch, {device_info['sample_rate']:.0f}Hz)"
            try:
                self.devices_menu.entryconfig(device_label, state='normal')
            except tk.TclError:
                pass  # Menu item might not exist

        self.logger.info("Recording stopped")

    def _on_canvas_resize(self, event, device_id: int):
        """Handle canvas resize event for a specific device.

        Args:
            event: Tkinter event
            device_id: Device ID whose canvas was resized
        """
        # Force redraw on resize by setting dirty flag for this device
        if device_id in self.level_meters:
            self.level_meters[device_id].dirty = True
            self._draw_level_meter(device_id)

    def _draw_level_meter(self, device_id: int):
        """Draw vertical audio level meter with color zones (bottom to top) for a specific device.

        Args:
            device_id: Device ID to draw meter for
        """
        # Check if device has a canvas
        if device_id not in self.level_canvases:
            return

        canvas = self.level_canvases[device_id]

        # Check if meter is visible
        if not self.meter_visible_var.get():
            # Clear canvas and show message
            canvas.delete('all')
            width = canvas.winfo_width()
            height = canvas.winfo_height()
            if width > 10 and height > 10:
                canvas.create_text(
                    width // 2, height // 2,
                    text="Meters\nHidden",
                    fill='gray', font=('TkDefaultFont', 8),
                    justify='center'
                )
            return

        # Check if device has a meter
        if device_id not in self.level_meters:
            return

        meter = self.level_meters[device_id]

        # Only redraw if meter has changed
        if not meter.dirty:
            return

        # Clear canvas
        canvas.delete('all')

        width = canvas.winfo_width()
        height = canvas.winfo_height()

        if width < 10 or height < 10:
            return

        # Get current levels in dB
        rms_db, peak_db = meter.get_db_levels()

        # Define dB ranges and colors (like OBS/Discord)
        # Green: -60 to -12 dB, Yellow: -12 to -6 dB, Red: -6 to 0 dB
        db_min = -60
        db_max = 0
        green_threshold = -12
        yellow_threshold = -6

        # Padding
        padding = 10
        meter_width = width - (2 * padding)
        meter_x = padding

        # Calculate zone heights (vertical now)
        total_db_range = db_max - db_min
        green_height = ((green_threshold - db_min) / total_db_range) * (height - 2 * padding)
        yellow_height = ((yellow_threshold - green_threshold) / total_db_range) * (height - 2 * padding)
        red_height = ((db_max - yellow_threshold) / total_db_range) * (height - 2 * padding)

        # Draw background zones (dark colors) - from bottom to top
        y_offset = height - padding  # Start at bottom
        # Green zone (bottom)
        canvas.create_rectangle(
            meter_x, y_offset - green_height,
            meter_x + meter_width, y_offset,
            fill='#1a3a1a', outline='#2a4a2a'
        )
        y_offset -= green_height
        # Yellow zone (middle)
        canvas.create_rectangle(
            meter_x, y_offset - yellow_height,
            meter_x + meter_width, y_offset,
            fill='#3a3a1a', outline='#4a4a2a'
        )
        y_offset -= yellow_height
        # Red zone (top)
        canvas.create_rectangle(
            meter_x, y_offset - red_height,
            meter_x + meter_width, y_offset,
            fill='#3a1a1a', outline='#4a2a2a'
        )

        # Calculate RMS bar height
        rms_position = max(db_min, min(rms_db, db_max))
        rms_fraction = (rms_position - db_min) / total_db_range
        rms_height = rms_fraction * (height - 2 * padding)

        # Draw RMS level bar (filled portion) - from bottom upward
        if rms_height > 0:
            y_offset = height - padding  # Start at bottom
            remaining = rms_height

            # Green portion
            green_fill = min(remaining, green_height)
            if green_fill > 0:
                canvas.create_rectangle(
                    meter_x, y_offset - green_fill,
                    meter_x + meter_width, y_offset,
                    fill='#00ff00', outline=''
                )
                remaining -= green_fill
                y_offset -= green_fill

            # Yellow portion
            if remaining > 0:
                yellow_fill = min(remaining, yellow_height)
                if yellow_fill > 0:
                    canvas.create_rectangle(
                        meter_x, y_offset - yellow_fill,
                        meter_x + meter_width, y_offset,
                        fill='#ffff00', outline=''
                    )
                    remaining -= yellow_fill
                    y_offset -= yellow_fill

            # Red portion
            if remaining > 0:
                red_fill = min(remaining, red_height)
                if red_fill > 0:
                    canvas.create_rectangle(
                        meter_x, y_offset - red_fill,
                        meter_x + meter_width, y_offset,
                        fill='#ff0000', outline=''
                    )

        # Draw peak hold indicator (thin horizontal line)
        if peak_db > db_min:
            peak_position = max(db_min, min(peak_db, db_max))
            peak_fraction = (peak_position - db_min) / total_db_range
            peak_y = (height - padding) - (peak_fraction * (height - 2 * padding))

            canvas.create_line(
                meter_x, peak_y,
                meter_x + meter_width, peak_y,
                fill='#ffffff', width=2
            )

        # Draw dB scale labels (on left side)
        canvas.create_text(
            5, height - padding,
            text=f"{db_min}", fill='#666666', anchor='w', font=('Arial', 7)
        )
        canvas.create_text(
            5, padding,
            text=f"{db_max}", fill='#666666', anchor='w', font=('Arial', 7)
        )

        # Clear dirty flag after drawing
        meter.clear_dirty()

    def _on_closing(self):
        """Handle window close event."""
        self.logger.info("GUI window closing")

        # Send final geometry to parent before quitting
        try:
            from logger_core.commands import StatusMessage
            # Get current window geometry
            geometry_str = self.window.geometry()  # Returns "WIDTHxHEIGHT+X+Y"
            parts = geometry_str.replace('+', 'x').replace('-', 'x-').split('x')
            if len(parts) >= 4:
                width = int(parts[0])
                height = int(parts[1])
                x = int(parts[2])
                y = int(parts[3])
                StatusMessage.send("geometry_changed", {
                    "width": width,
                    "height": height,
                    "x": x,
                    "y": y
                })
                self.logger.debug("Sent final geometry to parent: %dx%d+%d+%d", width, height, x, y)
        except Exception as e:
            self.logger.debug("Failed to send geometry: %s", e)

        # Always send quitting status to parent process (master logger)
        # This allows master to properly track module state
        try:
            from logger_core.commands import StatusMessage
            StatusMessage.send("quitting", {"reason": "user_closed_window"})
            self.logger.debug("Sent quitting status to parent")
        except Exception as e:
            self.logger.debug("Failed to send quitting status: %s", e)

        # Immediately hide the window for instant visual feedback
        try:
            self.window.withdraw()
        except Exception:
            pass

        # Set shutdown flags - the async cleanup in run() will handle destruction
        self.system.running = False
        self.system.shutdown_event.set()

        # Note: Don't call window.quit() here - we're using async update() pattern
        # not mainloop(), so quit() doesn't work properly. The finally block
        # in run() will handle proper window destruction.

    def _toggle_meter_visibility(self):
        """Toggle level meters visibility."""
        visible = self.meter_visible_var.get()
        if visible:
            self.logger.info("Level meters shown")
        else:
            self.logger.info("Level meters hidden")
        # Force redraw for all meters
        for device_id in self.level_meters.keys():
            self.level_meters[device_id].dirty = True
            self._draw_level_meter(device_id)

    def _populate_device_toggles(self):
        """Populate device toggle checkboxes in Devices menu (matching cameras pattern)."""
        # Clear existing device menu items (keep "Show Level Meters" and separator)
        # Devices menu structure: [Show Level Meters, Separator, Device0, Device1, ...]
        menu_size = self.devices_menu.index('end')
        if menu_size is not None and menu_size >= 2:
            # Delete everything after the separator (index 2+)
            for _ in range(menu_size, 1, -1):
                self.devices_menu.delete(menu_size)
                menu_size -= 1

        # Clear tracking dict
        self.device_active_vars.clear()

        # Add toggle for each available device
        for device_id in sorted(self.system.available_devices.keys()):
            device_info = self.system.available_devices[device_id]
            # Check if device is currently selected
            is_selected = device_id in self.system.selected_devices

            # Create BooleanVar for this device
            active_var = tk.BooleanVar(value=is_selected)
            self.device_active_vars[device_id] = active_var

            # Add checkbutton to Devices menu
            device_label = f"Device {device_id}: {device_info['name']} ({device_info['channels']}ch, {device_info['sample_rate']:.0f}Hz)"
            self.devices_menu.add_checkbutton(
                label=device_label,
                variable=active_var,
                command=lambda did=device_id, var=active_var: self._toggle_device(did, var.get())
            )

    def _toggle_device(self, device_id: int, active: bool):
        """
        Toggle device selection and dynamically update meter layout.

        Args:
            device_id: Device ID to toggle
            active: True to select, False to deselect
        """
        if active:
            # Select device
            if self.system.select_device(device_id):
                self.logger.info("Selected device %d", device_id)
                # Recreate meter canvases to include new device
                self._create_meter_canvases()
                # Start audio capture for this device
                asyncio.create_task(self._start_audio_capture_for_device(device_id))
        else:
            # Deselect device
            if self.system.deselect_device(device_id):
                self.logger.info("Deselected device %d", device_id)
                # Stop audio capture for this device
                asyncio.create_task(self._stop_audio_capture_for_device(device_id))
                # Recreate meter canvases to exclude deselected device
                self._create_meter_canvases()

    async def _start_audio_capture_for_device(self, device_id: int):
        """Start capturing audio for a specific device's level meter visualization.

        Args:
            device_id: Device ID to capture from
        """
        # Don't start if already running for this device
        if device_id in self.audio_processes:
            return

        # Get device info to extract ALSA device name
        device_info = self.system.available_devices.get(device_id)
        if not device_info:
            self.logger.error("Device %d not found in available devices", device_id)
            return

        # Extract ALSA device name from device name
        # Device names look like "USB Microphoner: Audio (hw:2,0)"
        # We need to extract "hw:2,0" from the parentheses
        device_name = device_info['name']
        alsa_match = re.search(r'\(([^)]+)\)$', device_name)
        if alsa_match:
            alsa_device = alsa_match.group(1)
        else:
            # Fallback: try using the device_id directly (might not work)
            alsa_device = f'hw:{device_id}'
            self.logger.warning(
                "Could not extract ALSA device from name '%s', using fallback '%s'",
                device_name, alsa_device
            )

        try:
            # Start arecord to capture audio data
            # Use a lower sample rate for visualization (8kHz is plenty for level meter)
            cmd = [
                'arecord',
                '-D', alsa_device,
                '-f', 'S16_LE',
                '-r', '8000',
                '-c', '1',
                '-t', 'raw',
                '--quiet'
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE  # Capture errors for logging
            )
            self.audio_processes[device_id] = process

            # Give the process a moment to start and verify it's running
            await asyncio.sleep(0.1)

            # Check if process failed immediately
            if process.returncode is not None:
                # Process failed to start
                try:
                    stderr_data = await asyncio.wait_for(process.stderr.read(), timeout=0.5)
                    error_msg = stderr_data.decode().strip() if stderr_data else "Unknown error"
                    self.logger.error(
                        "arecord failed to start for device %d (exit code %d): %s",
                        device_id, process.returncode, error_msg
                    )
                except Exception:
                    self.logger.error(
                        "arecord failed to start for device %d (exit code %d)",
                        device_id, process.returncode
                    )
                # Remove from tracking
                del self.audio_processes[device_id]
                return

            self.logger.info("Started audio capture for device %d (pid: %s)", device_id, process.pid)

            # Start capture loop for this device with exception tracking
            task = asyncio.create_task(self._audio_capture_loop_for_device(device_id))
            task.add_done_callback(self._task_done_callback)
            self.background_tasks.append(task)

        except Exception as e:
            self.logger.error("Failed to start audio capture for device %d: %s", device_id, e)
            # Clean up if process was added
            if device_id in self.audio_processes:
                del self.audio_processes[device_id]

    async def _stop_audio_capture_for_device(self, device_id: int):
        """Stop capturing audio for a specific device.

        Args:
            device_id: Device ID to stop capture for
        """
        if device_id in self.audio_processes:
            process = self.audio_processes[device_id]
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                process.kill()
            except Exception as e:
                self.logger.error("Error stopping audio capture for device %d: %s", device_id, e)
            finally:
                del self.audio_processes[device_id]
                self.logger.info("Stopped audio capture for device %d", device_id)

    async def _read_audio_data_for_device(self, device_id: int):
        """Read audio data and update level meter for a specific device.

        Reads larger chunks less frequently for better performance.
        At 8kHz, read 100ms worth of data = 800 samples.

        Args:
            device_id: Device ID to read data for
        """
        if device_id not in self.audio_processes:
            return

        process = self.audio_processes[device_id]
        if not process.stdout:
            return

        try:
            # Read 100ms worth of audio (at 8kHz = 800 samples)
            # 2 bytes per sample (S16_LE format)
            chunk_duration = 0.1  # 100ms
            chunk_samples = int(self.audio_sample_rate * chunk_duration)
            chunk_bytes = chunk_samples * 2

            # Add timeout to prevent blocking during shutdown
            # Give it 2x the chunk duration plus some margin (300ms)
            try:
                data = await asyncio.wait_for(
                    process.stdout.read(chunk_bytes),
                    timeout=0.3
                )
            except asyncio.TimeoutError:
                # Timeout during read - likely shutting down or process stalled
                self.logger.debug("Audio read timeout for device %d", device_id)
                return

            if data and device_id in self.level_meters:
                # Get current timestamp
                timestamp = datetime.now().timestamp()

                # Convert bytes to 16-bit signed integers
                samples = struct.unpack(f'{len(data)//2}h', data)

                # Normalize to -1.0 to 1.0 range
                normalized = [s / 32768.0 for s in samples]

                # Update level meter for this device
                self.level_meters[device_id].add_samples(normalized, timestamp)

        except Exception as e:
            self.logger.debug("Error reading audio data for device %d: %s", device_id, e)

    async def _audio_capture_loop_for_device(self, device_id: int):
        """Audio capture loop for a specific device - reads audio data continuously.

        Args:
            device_id: Device ID to capture from
        """
        while self.is_running() and self.window and device_id in self.audio_processes:
            try:
                # Read audio data (this will block for ~100ms based on chunk size)
                await self._read_audio_data_for_device(device_id)
            except Exception as e:
                self.logger.error("Audio capture loop error for device %d: %s", device_id, e)
                await asyncio.sleep(0.1)

        # Check if process failed and log stderr
        if device_id in self.audio_processes:
            process = self.audio_processes[device_id]
            if process.returncode and process.returncode != 0:
                try:
                    stderr_data = await asyncio.wait_for(process.stderr.read(), timeout=0.5)
                    if stderr_data:
                        self.logger.error(
                            "arecord error for device %d (exit code %d): %s",
                            device_id,
                            process.returncode,
                            stderr_data.decode().strip()
                        )
                except asyncio.TimeoutError:
                    self.logger.error("arecord failed for device %d (exit code %d)", device_id, process.returncode)
                except Exception as e:
                    self.logger.debug("Error reading stderr for device %d: %s", device_id, e)

    async def _display_update_loop(self):
        """Display update loop - refreshes all level meters at lower frequency."""
        while self.is_running() and self.window:
            try:
                # Draw all level meters (only if dirty flag is set for each)
                for device_id in list(self.level_canvases.keys()):
                    self._draw_level_meter(device_id)

                # Sleep for 50ms = 20fps display update (responsive for meters)
                await asyncio.sleep(0.05)

            except Exception as e:
                self.logger.error("Display update loop error: %s", e)
                await asyncio.sleep(0.05)

    async def _update_loop(self):
        """Main update loop for USB device monitoring."""
        # Counter for USB monitoring (less frequent)
        usb_poll_counter = 0
        usb_poll_interval_cycles = int(USB_POLL_INTERVAL / 0.5)  # Convert to 500ms cycles

        while self.is_running() and self.window:
            try:
                # Monitor USB devices (every ~USB_POLL_INTERVAL seconds)
                usb_poll_counter += 1
                if usb_poll_counter >= usb_poll_interval_cycles:
                    usb_poll_counter = 0

                    usb_devices = await DeviceDiscovery.get_usb_audio_devices()

                    if usb_devices != self.current_usb_devices:
                        added = set(usb_devices) - set(self.current_usb_devices)
                        removed = set(self.current_usb_devices) - set(usb_devices)

                        if added or removed:
                            # Refresh device list
                            self.system.available_devices = await DeviceDiscovery.get_audio_input_devices()

                            # Detect new devices
                            new_device_ids = set(self.system.available_devices.keys()) - self.system._known_devices
                            self.system._known_devices = set(self.system.available_devices.keys())

                            # Auto-select new devices
                            if self.system.auto_select_new and new_device_ids:
                                for device_id in new_device_ids:
                                    self.system.select_device(device_id)
                                    self.logger.info("Auto-selected new device %d", device_id)

                            # Handle removed devices
                            missing_selected = {
                                device_id
                                for device_id in list(self.system.selected_devices)
                                if device_id not in self.system.available_devices
                            }
                            if missing_selected:
                                for device_id in missing_selected:
                                    self.system.deselect_device(device_id)
                                    # Stop audio capture for removed device
                                    await self._stop_audio_capture_for_device(device_id)

                                if self.system.recording:
                                    await self.system.stop_recording()
                                    self.logger.warning("Recording stopped (device removed)")

                                # Recreate meter canvases to reflect removed devices
                                self._create_meter_canvases()

                            # Repopulate device toggles in View menu
                            self._populate_device_toggles()

                            self.current_usb_devices = usb_devices

                # Sleep for 500ms between main loop iterations
                await asyncio.sleep(0.5)

            except Exception as e:
                self.logger.error("Update loop error: %s", e)
                await asyncio.sleep(0.5)

    async def _setup_stdin_reader(self) -> asyncio.StreamReader:
        """
        Set up async stdin reader for parent communication.

        Returns:
            AsyncIO StreamReader connected to stdin
        """
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        return reader

    async def _command_listener(self, reader: asyncio.StreamReader) -> None:
        """
        Listen for commands from parent process via stdin.

        Commands are JSON-formatted, one per line.
        Status updates are sent to stdout as JSON.

        Args:
            reader: AsyncIO StreamReader for stdin
        """
        self.logger.info("Command listener started (parent communication enabled)")

        while self.is_running():
            try:
                # Read line with timeout to allow checking is_running()
                try:
                    line = await asyncio.wait_for(reader.readline(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue

                if not line:
                    # EOF reached - parent closed stdin
                    self.logger.info("Parent closed stdin, initiating shutdown")
                    self.system.running = False
                    self.system.shutdown_event.set()
                    break

                line_str = line.decode().strip()
                if line_str:
                    command_data = CommandMessage.parse(line_str)
                    if command_data:
                        # Handle command and check for quit
                        continue_running = await self._handle_command_with_gui_sync(command_data)
                        if not continue_running:
                            # Quit command received - exit listener
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
        """
        Handle command and sync GUI state.

        This wraps the standard command handler and ensures the GUI
        reflects changes made by commands from parent process.

        Args:
            command_data: Parsed command dict from JSON

        Returns:
            True to continue, False to shutdown (quit command received)
        """
        cmd = command_data.get("command")

        # Execute command via standard handler (returns False for quit command)
        continue_running = await self.command_handler.handle_command(command_data)

        if not continue_running:
            # Quit command received - trigger shutdown
            return False

        # Sync GUI state after command execution (thread-safe via root.after)
        if self.window and self.window.winfo_exists():
            if cmd == "start_recording":
                # Ensure GUI reflects recording state
                self.window.after(0, self._sync_gui_recording_state)
            elif cmd == "stop_recording":
                # Ensure GUI reflects stopped state
                self.window.after(0, self._sync_gui_recording_state)

        return True

    def _sync_gui_recording_state(self):
        """
        Sync GUI to reflect current recording state.

        Called from command handler to update GUI when parent
        sends start/stop commands.
        """
        if not self.window:
            return

        if self.system.recording:
            # Update window title to show recording
            self.window.title("Audio System - ⬤ RECORDING")

            # Disable device toggles during recording (safety)
            for device_id in self.device_active_vars.keys():
                device_info = self.system.available_devices.get(device_id, {})
                device_label = f"Device {device_id}: {device_info.get('name', 'Unknown')} ({device_info.get('channels', 0)}ch, {device_info.get('sample_rate', 0):.0f}Hz)"
                try:
                    self.devices_menu.entryconfig(device_label, state='disabled')
                except Exception:
                    pass
        else:
            # Update window title to default
            self.window.title("Audio System")

            # Re-enable device toggles after recording
            for device_id in self.device_active_vars.keys():
                device_info = self.system.available_devices.get(device_id, {})
                device_label = f"Device {device_id}: {device_info.get('name', 'Unknown')} ({device_info.get('channels', 0)}ch, {device_info.get('sample_rate', 0):.0f}Hz)"
                try:
                    self.devices_menu.entryconfig(device_label, state='normal')
                except Exception:
                    pass

    async def _run_gui_async(self):
        """
        Run tkinter event loop in async context using non-blocking pattern.

        Uses loop.call_later() to schedule GUI updates without blocking
        the event loop, allowing all async tasks to run concurrently.
        Based on Camera module's working pattern.
        """
        loop = asyncio.get_event_loop()

        def update_gui():
            """Update tkinter window (called via loop.call_later)."""
            try:
                if self.window and self.window.winfo_exists():
                    # Process pending GUI events without blocking
                    self.window.update()
                    if self.system.running:
                        # Schedule next update at 100Hz (0.01s) for responsive UI
                        loop.call_later(0.01, update_gui)
                else:
                    # Window closed
                    self.system.running = False
            except tk.TclError:
                # Window destroyed
                self.system.running = False

        try:
            # Start GUI update loop
            loop.call_soon(update_gui)

            # Wait for shutdown event (yields control to event loop)
            await self.system.shutdown_event.wait()
        finally:
            # Ensure window is properly closed
            if self.window:
                try:
                    self.window.quit()
                except Exception:
                    pass

    async def run(self) -> None:
        """Run GUI mode."""
        self.system.running = True

        if self.enable_commands:
            self.logger.info("Starting GUI mode with parent command support")
        else:
            self.logger.info("GUI mode: launching tkinter interface")

        # Create window
        self._create_window()

        # Initialize command handler with GUI reference (needed for get_geometry)
        if self.enable_commands:
            self.command_handler = CommandHandler(self.system, gui=self)

        # Populate device toggles in Devices menu
        self._populate_device_toggles()

        # Create meter canvases for selected devices
        self._create_meter_canvases()

        # Start audio capture for all selected devices
        for device_id in self.system.selected_devices:
            await self._start_audio_capture_for_device(device_id)

        # Auto-start recording if enabled
        if self.system.auto_start_recording:
            if self.system.start_recording():
                self.recording_start_time = datetime.now()
                self.window.title("Audio System - ⬤ RECORDING (auto-started)")
                self.logger.info("Recording auto-started")

        # Start all async loops
        update_task = asyncio.create_task(self._update_loop())
        display_task = asyncio.create_task(self._display_update_loop())

        # Start command listener if parent communication enabled
        if self.enable_commands:
            reader = await self._setup_stdin_reader()
            self.command_task = asyncio.create_task(self._command_listener(reader))

        # Run all tasks concurrently using asyncio.gather()
        try:
            tasks = [
                self._run_gui_async(),
                update_task,
                display_task,
            ]

            if self.command_task:
                tasks.append(self.command_task)

            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Log any exceptions from tasks
            task_names = ['GUI', 'Update Loop', 'Display Loop', 'Command Listener']
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    task_name = task_names[i] if i < len(task_names) else f"Task {i}"
                    self.logger.exception(
                        "%s task failed with exception: %s",
                        task_name, result,
                        exc_info=result
                    )

        finally:
            # Cancel tasks
            if update_task and not update_task.done():
                update_task.cancel()
            if display_task and not display_task.done():
                display_task.cancel()
            if self.command_task and not self.command_task.done():
                self.command_task.cancel()

            # Wait for tasks to complete
            pending = []
            if update_task:
                pending.append(update_task)
            if display_task:
                pending.append(display_task)
            if self.command_task:
                pending.append(self.command_task)

            if pending:
                results = await asyncio.gather(*pending, return_exceptions=True)
                # Log unexpected exceptions (CancelledError is expected here)
                for i, result in enumerate(results):
                    if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                        self.logger.exception(
                            "Task cleanup failed with exception: %s",
                            result,
                            exc_info=result
                        )

            # Stop all audio capture processes in parallel for faster shutdown
            if self.audio_processes:
                stop_tasks = [
                    self._stop_audio_capture_for_device(device_id)
                    for device_id in list(self.audio_processes.keys())
                ]
                await asyncio.gather(*stop_tasks, return_exceptions=True)

            if self.system.recording:
                await self.system.stop_recording()

            if self.window:
                try:
                    self.window.destroy()
                except Exception as e:
                    self.logger.debug("Error destroying window: %s", e)

            self.logger.info("GUI mode ended")
