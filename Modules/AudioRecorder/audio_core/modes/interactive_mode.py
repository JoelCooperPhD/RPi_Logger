#!/usr/bin/env python3
"""
Interactive mode with keyboard controls.

Standalone operation with keyboard shortcuts for recording control.
"""

import asyncio
import logging
import select
import sys
import termios
import tty
from datetime import datetime
from typing import TYPE_CHECKING

from .base_mode import BaseMode
from ..audio_utils import DeviceDiscovery
from ..constants import USB_POLL_INTERVAL

if TYPE_CHECKING:
    from ..audio_system import AudioSystem


class InteractiveMode(BaseMode):
    """Interactive mode with keyboard controls."""

    def __init__(self, audio_system: 'AudioSystem'):
        super().__init__(audio_system)

    async def _get_keyboard_input(self):
        """Non-blocking keyboard input detection using asyncio."""
        loop = asyncio.get_running_loop()

        # Run blocking select/read in thread pool to avoid blocking event loop
        def _check_stdin():
            if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
                return sys.stdin.read(1)
            return None

        return await asyncio.to_thread(_check_stdin)

    async def _process_feedback(self) -> None:
        """Process audio feedback messages from queue."""
        try:
            while True:
                message = self.system.feedback_queue.get_nowait()

                if message.startswith('feedback:') and self.system.recording:
                    device_id = message.split(':')[1]
                    active_count = len(self.system.active_handlers)
                    if self.system.recording:
                        # Calculate duration
                        duration = "recording..."
                        print(f"\r[REC] {duration} ({active_count} devices)", end="", flush=True)

                elif message.startswith('error:'):
                    _, device_id, error = message.split(':', 2)
                    device_name = self.system.available_devices.get(
                        int(device_id), {}
                    ).get('name', f'Device {device_id}')
                    print(f"\n[ERROR] {device_name}: {error}")

        except asyncio.QueueEmpty:
            pass

    async def run(self) -> None:
        """Run interactive mode with keyboard controls."""
        self.system.running = True

        self.logger.info("Interactive mode: keyboard controls active")

        # Get console output (original stdout before redirection)
        console = self.system.console

        # Print control instructions to console (always visible to user)
        print("\n" + "="*60, file=console)
        print("INTERACTIVE MODE", file=console)
        print("="*60, file=console)
        print("Commands:", file=console)
        print("  r : Toggle recording on/off", file=console)
        print("  s : Show device selection status", file=console)
        print("  1-9 : Toggle device selection (device ID)", file=console)
        print("  q : Quit application", file=console)
        print("  Ctrl+C : Also quits gracefully", file=console)
        print("="*60 + "\n", file=console)
        console.flush()

        # Display available devices
        await self._display_devices()

        # Auto-start recording if enabled
        if self.system.auto_start_recording:
            if self.system.start_recording():
                print(f"✓ Recording auto-started → {self.system.session_dir.name}", file=console)
                console.flush()

        # Set up non-blocking input
        old_settings = None
        try:
            old_settings = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())
        except (termios.error, OSError) as e:
            self.logger.warning("Could not set up keyboard input: %s", e)
            print(f"Warning: Keyboard input may not work properly: {e}", file=console)

        current_usb_devices = {}

        while self.is_running():
            # Process audio feedback
            await self._process_feedback()

            # Check for keyboard input
            try:
                key = await self._get_keyboard_input()
                if key == 'r' or key == 'R':
                    if self.system.recording:
                        await self.system.stop_recording()
                        print("✓ Recording stopped", file=console)
                        console.flush()
                    else:
                        if self.system.start_recording():
                            print(f"✓ Recording started → {self.system.session_dir.name}", file=console)
                            console.flush()
                        else:
                            print("✗ Failed to start recording", file=console)
                            console.flush()
                elif key == 's' or key == 'S':
                    print("", file=console)
                    await self._display_devices()
                elif key.isdigit():
                    device_id = int(key)
                    if device_id in self.system.selected_devices:
                        self.system.deselect_device(device_id)
                        print(f"✓ Device {device_id} deselected", file=console)
                        console.flush()
                    else:
                        if self.system.select_device(device_id):
                            print(f"✓ Device {device_id} selected", file=console)
                            console.flush()
                elif key == 'q' or key == 'Q':
                    print("✓ Quitting...", file=console)
                    console.flush()
                    self.system.shutdown_event.set()
                    break
            except Exception as e:
                self.logger.debug("Keyboard input error: %s", e)

            # Monitor USB devices
            usb_devices = await DeviceDiscovery.get_usb_audio_devices()

            if usb_devices != current_usb_devices:
                added = set(usb_devices) - set(current_usb_devices)
                removed = set(current_usb_devices) - set(usb_devices)

                for dev in removed:
                    print(f"[-] {current_usb_devices[dev]}", file=console)
                for dev in added:
                    print(f"[+] {usb_devices[dev]}", file=console)

                if usb_devices:
                    print(f"Active: {', '.join(usb_devices.values())}", file=console)
                else:
                    print("No USB audio devices", file=console)
                console.flush()

                # Refresh device list
                self.system.available_devices = await DeviceDiscovery.get_audio_input_devices()

                # Detect new devices BEFORE updating known devices
                new_device_ids = set(self.system.available_devices.keys()) - self.system._known_devices

                # Update known devices
                self.system._known_devices = set(self.system.available_devices.keys())

                # Auto-select new devices if enabled
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
                    if self.system.recording:
                        self.logger.info("Stopping recording after device removal")
                        await self.system.stop_recording()
                        print("✓ Recording stopped (device removed)", file=console)
                        console.flush()

                current_usb_devices = usb_devices

            await asyncio.sleep(USB_POLL_INTERVAL)

        # Cleanup
        if self.system.recording:
            await self.system.stop_recording()

        if old_settings:
            try:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
            except (termios.error, OSError) as e:
                self.logger.debug("Could not restore terminal settings: %s", e)

        self.logger.info("Interactive mode ended")

    async def _display_devices(self) -> None:
        """Display available devices and selection status."""
        console = self.system.console

        print("\nAvailable Input Devices:", file=console)
        print("=" * 40, file=console)
        for device_id, info in self.system.available_devices.items():
            status = "[SELECTED]" if device_id in self.system.selected_devices else "[ ]"
            print(f"{status} {device_id}: {info['name']} ({info['channels']} ch)", file=console)

        if not self.system.available_devices:
            print("No input devices found!", file=console)
        print("", file=console)
        console.flush()
