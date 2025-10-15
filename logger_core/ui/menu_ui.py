#!/usr/bin/env python3
"""
Master Logger Menu UI

Tkinter-based interface for selecting modules and controlling recording.
"""

import asyncio
import datetime
import logging
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox
from pathlib import Path
from typing import Optional, Dict

from ..logger_system import LoggerSystem
from ..module_process import ModuleState
from ..config_manager import get_config_manager


class MenuUI:
    """Tkinter UI for master logger system."""

    def __init__(self, logger_system: LoggerSystem):
        """
        Initialize UI.

        Args:
            logger_system: Logger system instance
        """
        self.logger = logging.getLogger("MenuUI")
        self.logger_system = logger_system
        self.logger_system.ui_callback = self._status_callback

        # UI elements
        self.root: Optional[tk.Tk] = None
        self.module_status_indicators: Dict[str, tk.Menu] = {}  # Menu reference for each module
        self.module_menu_indices: Dict[str, int] = {}  # Menu index for each module
        self.module_vars: Dict[str, tk.BooleanVar] = {}

        # Control buttons
        self.start_session_button: Optional[ttk.Button] = None
        self.stop_session_button: Optional[ttk.Button] = None
        self.start_trial_button: Optional[ttk.Button] = None
        self.stop_trial_button: Optional[ttk.Button] = None
        self.shutdown_button: Optional[ttk.Button] = None

        # Status labels
        self.session_status_label: Optional[tk.Label] = None
        self.session_timer_label: Optional[tk.Label] = None
        self.trial_timer_label: Optional[tk.Label] = None
        self.trial_counter_label: Optional[tk.Label] = None
        self.session_path_label: Optional[tk.Label] = None

        # Timers and counters
        self.session_start_time: Optional[datetime.datetime] = None
        self.trial_start_time: Optional[datetime.datetime] = None
        self.trial_counter: int = 0
        self.session_timer_task: Optional[asyncio.Task] = None
        self.trial_timer_task: Optional[asyncio.Task] = None

        # State
        self.running = False
        self.session_active = False
        self.trial_active = False

    def build_ui(self) -> None:
        """Build the Tkinter UI."""
        self.root = tk.Tk()
        self.root.title("RPi Logger")

        # Load window geometry from config
        config_path = Path(__file__).parent.parent.parent / "config.txt"
        config_manager = get_config_manager()

        if config_path.exists():
            config = config_manager.read_config(config_path)
            window_x = config_manager.get_int(config, 'window_x', default=0)
            window_y = config_manager.get_int(config, 'window_y', default=0)
            window_width = config_manager.get_int(config, 'window_width', default=800)
            window_height = config_manager.get_int(config, 'window_height', default=600)

            # Apply saved geometry if non-default
            if window_x != 0 or window_y != 0:
                self.root.geometry(f"{window_width}x{window_height}+{window_x}+{window_y}")
                self.logger.info("Applied saved window geometry: %dx%d+%d+%d", window_width, window_height, window_x, window_y)
            else:
                self.root.geometry(f"{window_width}x{window_height}")
        else:
            self.root.geometry("800x600")

        self.root.minsize(700, 500)

        # Apple-style background color
        self.root.configure(bg='#F5F5F7')

        # Configure root grid to resize
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        # === MENU BAR ===
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        # Modules menu
        modules_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Modules", menu=modules_menu)

        # Add module checkboxes to menu - initialize from config enabled state
        for idx, module_info in enumerate(self.logger_system.get_available_modules()):
            # Check if module is enabled in config
            is_enabled = self.logger_system.is_module_selected(module_info.name)
            var = tk.BooleanVar(value=is_enabled)
            self.module_vars[module_info.name] = var

            # Add checkbutton to menu with status indicator
            modules_menu.add_checkbutton(
                label=f"{module_info.display_name}  [Inactive]",
                variable=var,
                command=lambda name=module_info.name: self._on_module_menu_toggle(name)
            )

            # Store reference to menu and index for status updates
            self.module_status_indicators[module_info.name] = modules_menu
            self.module_menu_indices[module_info.name] = idx

        # Main container
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(0, weight=1)  # Control panel expands

        # Configure ttk button styles for Apple-like appearance
        style = ttk.Style()
        style.theme_use('clam')  # Use clam theme for better customization

        # Check for available fonts
        available_fonts = tkfont.families()
        button_font = ('Helvetica', 14, 'bold')
        if 'SF Pro Display' in available_fonts:
            button_font = ('SF Pro Display', 14, 'bold')
        elif 'Segoe UI' in available_fonts:
            button_font = ('Segoe UI', 14, 'bold')

        # Active button style (blue)
        style.configure(
            'Active.TButton',
            background='#007AFF',
            foreground='white',
            borderwidth=1,
            bordercolor='#007AFF',
            relief='flat',
            padding=(20, 15),
            font=button_font
        )
        style.map('Active.TButton',
                  background=[('pressed', '#0051D5'), ('active', '#0062CC')],
                  foreground=[('pressed', 'white'), ('active', 'white')])

        # Inactive button style (gray)
        style.configure(
            'Inactive.TButton',
            background='#E5E5EA',
            foreground='#8E8E93',
            borderwidth=1,
            bordercolor='#C7C7CC',
            relief='flat',
            padding=(20, 15),
            font=button_font
        )
        style.map('Inactive.TButton',
                  background=[('pressed', '#D1D1D6'), ('active', '#D1D1D6')],
                  foreground=[('pressed', '#8E8E93'), ('active', '#8E8E93')])

        # === CENTER: Control Panel ===
        control_frame = ttk.Frame(main_frame)
        control_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 15))
        control_frame.columnconfigure(0, weight=1)
        control_frame.columnconfigure(1, weight=1)
        control_frame.rowconfigure(0, weight=1)

        # Left side: Session Control
        session_control_frame = ttk.LabelFrame(control_frame, text="Session", padding="25")
        session_control_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(0, 10))
        session_control_frame.columnconfigure(0, weight=1)

        # Start Session button (initially active/blue)
        self.start_session_button = ttk.Button(
            session_control_frame,
            text="Start Session",
            style='Active.TButton',
            command=self._on_start_session
        )
        self.start_session_button.pack(fill=tk.X, pady=(0, 10))

        # Stop Session button (initially inactive/gray)
        self.stop_session_button = ttk.Button(
            session_control_frame,
            text="Stop Session",
            style='Inactive.TButton',
            command=self._on_stop_session
        )
        self.stop_session_button.pack(fill=tk.X, pady=(0, 20))

        # Session info
        self.session_status_label = ttk.Label(
            session_control_frame,
            text="Status: Idle",
            font=("Helvetica", 12)
        )
        self.session_status_label.pack(pady=(0, 5))

        self.session_timer_label = ttk.Label(
            session_control_frame,
            text="Session Time: --:--:--",
            font=("Helvetica", 11)
        )
        self.session_timer_label.pack()

        # Right side: Trial Control
        trial_control_frame = ttk.LabelFrame(control_frame, text="Trial", padding="25")
        trial_control_frame.grid(row=0, column=1, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(10, 0))
        trial_control_frame.columnconfigure(0, weight=1)

        # Start Trial button (initially inactive/gray)
        self.start_trial_button = ttk.Button(
            trial_control_frame,
            text="Start Trial",
            style='Inactive.TButton',
            command=self._on_start_trial
        )
        self.start_trial_button.pack(fill=tk.X, pady=(0, 10))

        # Stop Trial button (initially inactive/gray)
        self.stop_trial_button = ttk.Button(
            trial_control_frame,
            text="Stop Trial",
            style='Inactive.TButton',
            command=self._on_stop_trial
        )
        self.stop_trial_button.pack(fill=tk.X, pady=(0, 20))

        # Trial info
        self.trial_counter_label = ttk.Label(
            trial_control_frame,
            text="Trials Completed: 0",
            font=("Helvetica", 12)
        )
        self.trial_counter_label.pack(pady=(0, 5))

        self.trial_timer_label = ttk.Label(
            trial_control_frame,
            text="Trial Time: --:--:--",
            font=("Helvetica", 11)
        )
        self.trial_timer_label.pack()

        # === BOTTOM: Session Info ===
        info_frame = ttk.LabelFrame(main_frame, text="Session Information", padding="10")
        info_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 10))

        session_info = self.logger_system.get_session_info()
        self.session_path_label = ttk.Label(
            info_frame,
            text=f"Path: {session_info['session_dir']}",
            font=("Arial", 9)
        )
        self.session_path_label.pack(anchor=tk.W)

        # === SHUTDOWN BUTTON ===
        shutdown_frame = ttk.Frame(main_frame)
        shutdown_frame.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=(0, 0))
        shutdown_frame.columnconfigure(0, weight=1)

        # Shutdown Logger button (red/destructive style)
        style.configure(
            'Shutdown.TButton',
            background='#FF3B30',
            foreground='white',
            borderwidth=1,
            bordercolor='#FF3B30',
            relief='flat',
            padding=(20, 12),
            font=button_font
        )
        style.map('Shutdown.TButton',
                  background=[('pressed', '#CC0000'), ('active', '#E60000')],
                  foreground=[('pressed', 'white'), ('active', 'white')])

        self.shutdown_button = ttk.Button(
            shutdown_frame,
            text="Shutdown Logger",
            style='Shutdown.TButton',
            command=self._on_shutdown
        )
        self.shutdown_button.pack(fill=tk.X)

        # Set close handler
        self.root.protocol("WM_DELETE_WINDOW", self._on_quit)


    def _on_module_menu_toggle(self, module_name: str) -> None:
        """Handle module menu toggle - toggle module on/off."""
        current_state = self.module_vars[module_name].get()

        # Update config file to persist enabled state
        self.logger_system.toggle_module_enabled(module_name, current_state)

        if current_state:
            # Module checked - start it
            self.logger.info("Starting module: %s", module_name)
            asyncio.create_task(self._start_module_async(module_name))
        else:
            # Module unchecked - stop it
            self.logger.info("Stopping module: %s", module_name)
            asyncio.create_task(self._stop_module_async(module_name))

    async def _start_module_async(self, module_name: str) -> None:
        """Start a single module asynchronously."""
        try:
            # Update menu label to show starting
            self._update_menu_label(module_name, "Starting...")

            # Start the module (this waits for any existing process to stop first)
            success = await self.logger_system.start_module(module_name)

            if not success:
                # Failed to start - reset status
                self.module_vars[module_name].set(False)
                self._update_menu_label(module_name, "Error")
                messagebox.showerror(
                    "Start Failed",
                    f"Failed to start module: {module_name}\nCheck logs for details."
                )
            else:
                self.logger.info("Module %s started successfully", module_name)

        except Exception as e:
            self.logger.error("Error starting module %s: %s", module_name, e, exc_info=True)
            self.module_vars[module_name].set(False)
            self._update_menu_label(module_name, "Error")
            messagebox.showerror("Error", f"Failed to start {module_name}: {e}")

    async def _stop_module_async(self, module_name: str) -> None:
        """Stop a single module asynchronously."""
        try:
            # Update menu label to show stopping
            self._update_menu_label(module_name, "Stopping...")

            # Stop the module
            success = await self.logger_system.stop_module(module_name)

            if not success:
                self.logger.warning("Failed to stop module: %s", module_name)
            else:
                self.logger.info("Module %s stopped successfully", module_name)

            # Update status to inactive
            self._update_menu_label(module_name, "Inactive")

        except Exception as e:
            self.logger.error("Error stopping module %s: %s", module_name, e, exc_info=True)
            self._update_menu_label(module_name, "Error")
            messagebox.showerror("Error", f"Failed to stop {module_name}: {e}")

    def _update_menu_label(self, module_name: str, status: str) -> None:
        """Update the menu label for a module to show status."""
        if module_name in self.module_status_indicators and module_name in self.module_menu_indices:
            menu = self.module_status_indicators[module_name]
            idx = self.module_menu_indices[module_name]

            # Get the module's display name
            module_info = next(
                (m for m in self.logger_system.get_available_modules() if m.name == module_name),
                None
            )
            if module_info:
                # Update the menu item label
                menu.entryconfig(idx, label=f"{module_info.display_name}  [{status}]")

    def _on_start_session(self) -> None:
        """Handle start session button."""
        self.logger.info("Starting session...")
        asyncio.create_task(self._start_session_async())

    def _on_stop_session(self) -> None:
        """Handle stop session button."""
        self.logger.info("Stopping session...")
        asyncio.create_task(self._stop_session_async())

    async def _start_session_async(self) -> None:
        """Start session asynchronously."""
        try:
            # Check if any modules are running
            has_running = any(
                self.logger_system.is_module_running(name)
                for name in self.module_vars.keys()
            )

            if not has_running:
                messagebox.showwarning(
                    "No Modules",
                    "Please select at least one module before starting a session."
                )
                return

            # Update UI
            self.session_active = True
            self.session_start_time = datetime.datetime.now()
            self.trial_counter = 0

            # Toggle button styles: Start -> gray, Stop -> blue
            self.start_session_button.config(style='Inactive.TButton')
            self.stop_session_button.config(style='Active.TButton')

            # Update status
            self.session_status_label.config(text="Status: Active")

            # Enable trial start button
            self.start_trial_button.config(style='Active.TButton')

            # Start session timer
            if self.session_timer_task:
                self.session_timer_task.cancel()
            self.session_timer_task = asyncio.create_task(self._update_session_timer())

            self.logger.info("Session started")

        except Exception as e:
            self.logger.error("Error starting session: %s", e, exc_info=True)
            messagebox.showerror("Error", f"Failed to start session: {e}")
            self.session_active = False

    async def _stop_session_async(self) -> None:
        """Stop session asynchronously."""
        try:
            # Stop any active trial first
            if self.trial_active:
                await self._stop_trial_async()

            # Update UI
            self.session_active = False
            self.session_start_time = None

            # Toggle button styles: Start -> blue, Stop -> gray
            self.start_session_button.config(style='Active.TButton')
            self.stop_session_button.config(style='Inactive.TButton')

            # Update status
            self.session_status_label.config(text="Status: Idle")
            self.session_timer_label.config(text="Session Time: --:--:--")

            # Disable trial buttons
            self.start_trial_button.config(style='Inactive.TButton')
            self.stop_trial_button.config(style='Inactive.TButton')

            # Stop session timer
            if self.session_timer_task:
                self.session_timer_task.cancel()
                self.session_timer_task = None

            self.logger.info("Session stopped")

        except Exception as e:
            self.logger.error("Error stopping session: %s", e, exc_info=True)
            messagebox.showerror("Error", f"Failed to stop session: {e}")

    def _on_start_trial(self) -> None:
        """Handle start trial button."""
        if not self.session_active:
            messagebox.showwarning("No Active Session", "Please start a session first.")
            return
        self.logger.info("Starting trial...")
        asyncio.create_task(self._start_trial_async())

    def _on_stop_trial(self) -> None:
        """Handle stop trial button."""
        self.logger.info("Stopping trial...")
        asyncio.create_task(self._stop_trial_async())

    async def _start_trial_async(self) -> None:
        """Start trial (start recording on all modules)."""
        try:
            # Start recording on all modules
            results = await self.logger_system.start_recording_all()

            # Check results
            failed = [name for name, success in results.items() if not success]
            if failed:
                messagebox.showwarning(
                    "Recording Warning",
                    f"Failed to start recording on: {', '.join(failed)}"
                )

            # Update UI
            self.trial_active = True
            self.trial_start_time = datetime.datetime.now()

            # Toggle button styles: Start -> gray, Stop -> blue
            self.start_trial_button.config(style='Inactive.TButton')
            self.stop_trial_button.config(style='Active.TButton')

            # Start trial timer
            if self.trial_timer_task:
                self.trial_timer_task.cancel()
            self.trial_timer_task = asyncio.create_task(self._update_trial_timer())

            self.logger.info("Trial started")

        except Exception as e:
            self.logger.error("Error starting trial: %s", e, exc_info=True)
            messagebox.showerror("Error", f"Failed to start trial: {e}")

    async def _stop_trial_async(self) -> None:
        """Stop trial (stop recording on all modules)."""
        try:
            # Stop recording on all modules
            results = await self.logger_system.stop_recording_all()

            # Check results
            failed = [name for name, success in results.items() if not success]
            if failed:
                messagebox.showwarning(
                    "Stop Warning",
                    f"Failed to stop recording on: {', '.join(failed)}"
                )

            # Update UI
            self.trial_active = False
            self.trial_start_time = None
            self.trial_counter += 1

            # Toggle button styles: Start -> blue, Stop -> gray
            self.start_trial_button.config(style='Active.TButton')
            self.stop_trial_button.config(style='Inactive.TButton')

            # Update trial counter
            self.trial_counter_label.config(text=f"Trials Completed: {self.trial_counter}")
            self.trial_timer_label.config(text="Trial Time: --:--:--")

            # Stop trial timer
            if self.trial_timer_task:
                self.trial_timer_task.cancel()
                self.trial_timer_task = None

            self.logger.info("Trial stopped (trial #%d)", self.trial_counter)

        except Exception as e:
            self.logger.error("Error stopping trial: %s", e, exc_info=True)
            messagebox.showerror("Error", f"Failed to stop trial: {e}")

    def _on_shutdown(self) -> None:
        """Handle Shutdown Logger button - always saves module state."""
        # Check if session is active
        if self.session_active:
            response = messagebox.askyesno(
                "Confirm Shutdown",
                "Session is active. Shutdown anyway?"
            )
            if not response:
                return

        self.logger.info("Shutting down logger (preserving module state)...")

        # Disable button and update text to show shutdown in progress
        self.shutdown_button.config(state='disabled')
        self.shutdown_button.config(text="Shutting Down...")

        # Mark UI as shutting down
        self.running = False

        # Schedule quit task - let the main loop handle it
        asyncio.create_task(self._quit_async(save_running_modules=True))

    def _on_quit(self) -> None:
        """Handle window close (X button) - always saves module state."""
        # Check if session is active
        if self.session_active:
            if not messagebox.askyesno("Confirm", "Session is active. Quit anyway?"):
                return

        self.logger.info("Quitting (preserving module state)...")

        # Mark UI as shutting down
        self.running = False

        asyncio.create_task(self._quit_async(save_running_modules=True))

    async def _quit_async(self, save_running_modules: bool = False) -> None:
        """
        Quit asynchronously.

        Args:
            save_running_modules: If True, save currently running modules for next startup
        """
        try:
            # Save window geometry before quitting
            if self.root:
                try:
                    geometry_str = self.root.geometry()  # Returns "WIDTHxHEIGHT+X+Y"
                    parts = geometry_str.replace('+', 'x').replace('-', 'x-').split('x')
                    if len(parts) >= 4:
                        width = int(parts[0])
                        height = int(parts[1])
                        x = int(parts[2])
                        y = int(parts[3])

                        # Save to config.txt
                        config_path = Path(__file__).parent.parent.parent / "config.txt"
                        config_manager = get_config_manager()
                        updates = {
                            'window_x': x,
                            'window_y': y,
                            'window_width': width,
                            'window_height': height,
                        }
                        if config_manager.write_config(config_path, updates):
                            self.logger.info("Saved main logger window geometry: %dx%d+%d+%d", width, height, x, y)
                        else:
                            self.logger.warning("Failed to save window geometry")
                except Exception as e:
                    self.logger.error("Error saving window geometry: %s", e)

            # Save running modules state if requested
            if save_running_modules:
                await self.logger_system.save_running_modules_state()

            await self.logger_system.cleanup()
        finally:
            self.running = False
            if self.root:
                self.root.quit()

    async def _update_session_timer(self) -> None:
        """Update session timer."""
        try:
            while self.session_start_time and self.running:
                elapsed = datetime.datetime.now() - self.session_start_time
                hours = int(elapsed.total_seconds() // 3600)
                minutes = int((elapsed.total_seconds() % 3600) // 60)
                seconds = int(elapsed.total_seconds() % 60)

                self.session_timer_label.config(text=f"Session Time: {hours:02d}:{minutes:02d}:{seconds:02d}")

                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass

    async def _update_trial_timer(self) -> None:
        """Update trial timer."""
        try:
            while self.trial_start_time and self.running:
                elapsed = datetime.datetime.now() - self.trial_start_time
                hours = int(elapsed.total_seconds() // 3600)
                minutes = int((elapsed.total_seconds() % 3600) // 60)
                seconds = int(elapsed.total_seconds() % 60)

                self.trial_timer_label.config(text=f"Trial Time: {hours:02d}:{minutes:02d}:{seconds:02d}")

                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass

    async def _status_callback(self, module_name: str, state: ModuleState, status) -> None:
        """
        Handle status updates from modules.

        Args:
            module_name: Module name
            state: Module state
            status: Status message
        """
        # Map state to status text
        status_text = "Unknown"

        if state == ModuleState.STOPPED:
            status_text = "Inactive"
        elif state == ModuleState.STARTING:
            status_text = "Starting..."
        elif state == ModuleState.INITIALIZING:
            status_text = "Initializing..."
        elif state == ModuleState.IDLE:
            status_text = "Ready"
        elif state == ModuleState.RECORDING:
            status_text = "RECORDING"
        elif state == ModuleState.STOPPING:
            status_text = "Stopping..."
        elif state == ModuleState.ERROR:
            status_text = "Error"
        elif state == ModuleState.CRASHED:
            status_text = "Crashed"

        # Update menu label
        self._update_menu_label(module_name, status_text)

        # Sync module var state with module state
        if module_name in self.module_vars:
            var = self.module_vars[module_name]

            # Don't sync during startup
            if status_text == "Starting...":
                pass
            # Module stopped/crashed/error → uncheck
            elif state in (ModuleState.STOPPED, ModuleState.CRASHED, ModuleState.ERROR):
                if var.get():
                    self.logger.info("Unchecking %s (state: %s)", module_name, state.value)
                    var.set(False)
            # Module running → check
            elif state in (ModuleState.IDLE, ModuleState.RECORDING, ModuleState.INITIALIZING):
                if not var.get():
                    self.logger.info("Checking %s (state: %s)", module_name, state.value)
                    var.set(True)

    async def run(self) -> None:
        """Run the UI event loop."""
        self.running = True
        self.build_ui()

        # Auto-start all modules (they default to checked)
        await self._auto_start_modules()

        # Run Tkinter event loop with asyncio integration
        while self.running:
            try:
                self.root.update()
                await asyncio.sleep(0.01)  # 10ms update rate
            except tk.TclError:
                # Window closed
                break
            except Exception as e:
                self.logger.error("UI loop error: %s", e)
                break

        self.logger.info("UI stopped")

    async def _auto_start_modules(self) -> None:
        """Auto-start all modules that are enabled in config."""
        # Give UI time to render
        await asyncio.sleep(0.5)

        # Start all enabled modules (loaded from config)
        for module_name in self.logger_system.get_selected_modules():
            self.logger.info("Auto-starting module: %s", module_name)
            await self._start_module_async(module_name)
