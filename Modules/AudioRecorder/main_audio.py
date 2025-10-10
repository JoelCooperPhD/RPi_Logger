#!/usr/bin/env python3

import argparse
import asyncio
import logging
import sys
import select
import tty
import termios
import concurrent.futures
from pathlib import Path
from datetime import datetime
import sounddevice as sd
import numpy as np
import wave
import aiofiles
from typing import Dict, List, Optional

# Add project root to path for cli_utils import
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli_utils import add_common_cli_arguments, configure_logging, ensure_directory, positive_int

logger = logging.getLogger("audio_recorder")


async def get_audio_input_devices():
    """Get all available audio input devices."""
    try:
        devices = sd.query_devices()
        input_devices = {}

        for idx, device in enumerate(devices):
            if device['max_input_channels'] > 0:  # Has input capability
                input_devices[idx] = {
                    'name': device['name'],
                    'channels': device['max_input_channels'],
                    'sample_rate': device['default_samplerate']
                }

        return input_devices
    except Exception as e:
        print(f"Error querying audio devices: {e}")
        return {}


async def get_usb_audio_devices():
    """Ultra-fast USB audio device check using /proc/asound."""
    devices = {}
    cards_path = Path('/proc/asound/cards')

    if not cards_path.exists():
        return devices

    try:
        async with aiofiles.open(cards_path, 'r') as f:
            content = await f.read()
            lines = content.splitlines()

        for i in range(0, len(lines), 2):
            if i + 1 < len(lines):
                card_line = lines[i].strip()
                name_line = lines[i + 1].strip()

                if 'USB' in card_line or 'USB' in name_line:
                    card_num = card_line.split()[0]
                    card_name = card_line.split(']:')[1].strip() if ']:' in card_line else card_line
                    devices[f"card_{card_num}"] = card_name
    except:
        pass

    return devices


class MultiMicRecorder:
    """Manages multi-microphone recording with sounddevice."""

    def __init__(self, experiment_dir: Path, sample_rate: int, auto_select_new: bool) -> None:
        self.experiment_dir = experiment_dir
        self.recording_count = 0
        self.sample_rate = sample_rate
        self.auto_select_new = auto_select_new

        # Track multiple microphones
        self.available_devices = {}  # device_id -> device_info
        self.selected_devices = set()  # device_ids selected for recording
        self.active_recorders = {}  # device_id -> recorder_state

        self.feedback_queue = asyncio.Queue()
        self.is_recording = False
        self.start_time = None
        self._known_devices: set[int] = set()

    async def initialize_devices(self):
        """Initialize and display available input devices."""
        previous = set(self._known_devices)
        self.available_devices = await get_audio_input_devices()
        current = set(self.available_devices)
        self._known_devices = current
        newly_added = sorted(current - previous)

        print("\nAvailable Input Devices:")
        print("=" * 40)
        for device_id, info in self.available_devices.items():
            status = "[SELECTED]" if device_id in self.selected_devices else "[ ]"
            print(f"{status} {device_id}: {info['name']} ({info['channels']} ch)")

        if not self.available_devices:
            print("No input devices found!")
        print()

        if self.auto_select_new and newly_added and not self.selected_devices:
            for device_id in newly_added:
                if self.toggle_device_selection(device_id):
                    break

    def toggle_device_selection(self, device_id: int):
        """Toggle device selection for recording."""
        if device_id not in self.available_devices:
            print(f"Device {device_id} not found")
            return False

        if device_id in self.selected_devices:
            self.selected_devices.remove(device_id)
            print(f"Deselected: {self.available_devices[device_id]['name']}")
        else:
            self.selected_devices.add(device_id)
            print(f"Selected: {self.available_devices[device_id]['name']}")

        return True

    def start_recording(self):
        """Start recording from all selected devices."""
        if self.is_recording or not self.selected_devices:
            if not self.selected_devices:
                print("No devices selected for recording!")
            return False

        self.recording_count += 1
        self.is_recording = True
        self.start_time = datetime.now()
        success_count = 0

        for device_id in self.selected_devices:
            device_info = self.available_devices[device_id]

            # Create recorder state for this device
            recorder_state = {
                'stream': None,
                'audio_data': [],
                'frames_recorded': 0,
                'device_info': device_info
            }

            def make_callback(device_id, recorder_state):
                def audio_callback(indata, frames, time, status):
                    if not self.is_recording:
                        return

                    recorder_state['audio_data'].append(indata.copy())
                    recorder_state['frames_recorded'] += frames

                    # Queue feedback every ~2 seconds
                    if recorder_state['frames_recorded'] % (self.sample_rate * 2) < frames:
                        try:
                            self.feedback_queue.put_nowait(f'feedback:{device_id}')
                        except asyncio.QueueFull:
                            pass

                    if status:
                        try:
                            self.feedback_queue.put_nowait(f'error:{device_id}:{status}')
                        except asyncio.QueueFull:
                            pass

                return audio_callback

            try:
                stream = sd.InputStream(
                    device=device_id,
                    callback=make_callback(device_id, recorder_state),
                    channels=1,  # Mono recording per device
                    samplerate=self.sample_rate,
                    dtype=np.float32,
                    blocksize=1024
                )
                stream.start()
                recorder_state['stream'] = stream
                self.active_recorders[device_id] = recorder_state
                success_count += 1

            except Exception as e:
                print(f"Failed to start recording on device {device_id}: {e}")

        if success_count > 0:
            device_names = [self.available_devices[did]['name'] for did in self.active_recorders.keys()]
            print(f"[REC] Started recording #{self.recording_count} on {len(self.active_recorders)} devices")
            print(f"      Devices: {', '.join(device_names)}")
            return True
        else:
            self.is_recording = False
            return False

    async def stop_recording(self):
        """Stop recording on all active devices and save files."""
        if not self.is_recording:
            return False

        self.is_recording = False

        # Stop all streams
        for device_id, recorder_state in self.active_recorders.items():
            if recorder_state['stream']:
                recorder_state['stream'].stop()
                recorder_state['stream'].close()

        # Save all recordings asynchronously
        save_tasks = []
        for device_id, recorder_state in self.active_recorders.items():
            if recorder_state['audio_data']:
                task = self._save_device_recording(device_id, recorder_state)
                save_tasks.append(task)

        if save_tasks:
            await asyncio.gather(*save_tasks)

        # Clear active recorders
        self.active_recorders.clear()

        duration = int((datetime.now() - self.start_time).total_seconds()) if self.start_time else 0
        print(f"\n[SAVE] All recordings saved ({duration}s)")
        return True

    async def _save_device_recording(self, device_id: int, recorder_state: dict):
        """Save recording for a specific device."""
        device_info = recorder_state['device_info']
        device_name = device_info['name'].replace(' ', '_').replace(':', '')

        # Process audio data in thread pool
        loop = asyncio.get_event_loop()

        def prepare_audio_data():
            audio_array = np.concatenate(recorder_state['audio_data'])
            return (audio_array * 32767).astype(np.int16)

        with concurrent.futures.ThreadPoolExecutor() as executor:
            audio_int16 = await loop.run_in_executor(executor, prepare_audio_data)

        # Save file
        timestamp = datetime.now().strftime("%H%M%S")
        filename = f"mic{device_id}_{device_name}_rec{self.recording_count:03d}_{timestamp}.wav"
        filepath = self.experiment_dir / filename

        def write_wav_file():
            with wave.open(str(filepath), 'wb') as wf:
                wf.setnchannels(1)  # Mono
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(self.sample_rate)
                wf.writeframes(audio_int16.tobytes())

        with concurrent.futures.ThreadPoolExecutor() as executor:
            await loop.run_in_executor(executor, write_wav_file)

        print(f"[SAVE] Device {device_id}: {filename}")

    async def process_feedback(self):
        """Process audio feedback messages from queue."""
        try:
            while True:
                message = self.feedback_queue.get_nowait()

                if message.startswith('feedback:') and self.is_recording and self.start_time:
                    device_id = message.split(':')[1]
                    duration = int((datetime.now() - self.start_time).total_seconds())
                    active_count = len(self.active_recorders)
                    print(f"\r[REC] Recording... {duration}s ({active_count} devices)", end="", flush=True)

                elif message.startswith('error:'):
                    _, device_id, error = message.split(':', 2)
                    device_name = self.available_devices.get(int(device_id), {}).get('name', f'Device {device_id}')
                    print(f"\n[ERROR] {device_name}: {error}")
        except asyncio.QueueEmpty:
            pass



async def create_experiment_folder(base_dir: Path, prefix: str) -> Path:
    """Create a timestamped experiment folder in the configured directory."""

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = prefix.rstrip("_")
    experiment_name = f"{prefix}_{timestamp}" if prefix else timestamp

    base_dir = ensure_directory(base_dir)
    experiment_dir = base_dir / experiment_name

    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor() as executor:
        await loop.run_in_executor(executor, lambda: experiment_dir.mkdir(exist_ok=True))

    return experiment_dir


async def get_keyboard_input():
    """Non-blocking keyboard input detection."""
    if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
        return sys.stdin.read(1)
    return None


async def monitor_loop(args) -> None:
    """Main monitoring loop with audio recording capability."""
    current_devices = {}
    running = True

    # Create experiment folder
    experiment_dir = await create_experiment_folder(args.output_dir, args.session_prefix)
    print(f"Created experiment folder: {experiment_dir}")

    # Initialize multi-mic recorder
    recorder = MultiMicRecorder(
        experiment_dir,
        sample_rate=args.sample_rate,
        auto_select_new=args.auto_select_new,
    )
    await recorder.initialize_devices()

    print("Multi-Microphone Audio Recorder - Controls:")
    print("  [r] = Start/Stop recording from selected devices")
    print("  [1-9] = Toggle device selection (device ID)")
    print("  [s] = Show device selection status")
    print("  [q] = Quit program")
    print("  [Ctrl+C] = Quit")
    print()

    # Set up non-blocking input
    old_settings = None
    try:
        old_settings = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())
    except:
        print("Warning: Could not set up keyboard input")

    while running:
        # Process audio feedback
        await recorder.process_feedback()

        # Check for keyboard input
        try:
            key = await get_keyboard_input()
            if key == 'r' or key == 'R':
                if recorder.is_recording:
                    await recorder.stop_recording()
                else:
                    recorder.start_recording()
            elif key == 's' or key == 'S':
                await recorder.initialize_devices()  # Refresh and show devices
            elif key.isdigit():
                device_id = int(key)
                recorder.toggle_device_selection(device_id)
            elif key == 'q' or key == 'Q':
                print("\nQuitting...")
                running = False
        except:
            pass

        # Monitor USB devices
        devices = await get_usb_audio_devices()

        if devices != current_devices:
            added = set(devices) - set(current_devices)
            removed = set(current_devices) - set(devices)

            for dev in removed:
                print(f"[-] {current_devices[dev]}")
            for dev in added:
                print(f"[+] {devices[dev]}")

            if devices:
                print(f"Active: {', '.join(devices.values())}")
            else:
                print("No USB audio devices")
            print()

            await recorder.initialize_devices()
            current_devices = devices

            if (
                args.auto_record_on_attach
                and recorder.selected_devices
                and not recorder.is_recording
            ):
                logger.info("Auto-starting recording after device attachment")
                started = recorder.start_recording()
                if not started:
                    logger.warning("Unable to auto-start recording; verify device selection")

            missing_selected = {
                device_id
                for device_id in list(recorder.selected_devices)
                if device_id not in recorder.available_devices
            }
            if missing_selected:
                for device_id in missing_selected:
                    recorder.selected_devices.discard(device_id)
                    recorder.active_recorders.pop(device_id, None)
                    logger.info("Deselected removed device %s", device_id)
                if recorder.is_recording:
                    logger.info("Stopping recording after device removal to keep data consistent")
                    await recorder.stop_recording()

        await asyncio.sleep(0.005)  # 5ms

    # Cleanup
    if recorder.is_recording:
        await recorder.stop_recording()  # Now async

    if old_settings:
        try:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        except:
            pass


def parse_args(argv: Optional[list[str]] = None):
    parser = argparse.ArgumentParser(description="Multi-microphone audio recorder")
    add_common_cli_arguments(
        parser,
        default_output=Path("recordings/audio"),
        allowed_modes=("interactive",),
        default_mode="interactive",
    )
    parser.add_argument(
        "--sample-rate",
        type=positive_int,
        default=48000,
        help="Sample rate (Hz) for each active microphone",
    )
    parser.add_argument(
        "--session-prefix",
        type=str,
        default="experiment",
        help="Prefix for experiment directories",
    )
    parser.add_argument(
        "--auto-record-on-attach",
        action="store_true",
        help="Automatically start recording when devices become available",
    )
    parser.add_argument(
        "--no-auto-select-new",
        action="store_false",
        dest="auto_select_new",
        help="Disable automatic selection of newly detected input devices",
    )
    parser.set_defaults(auto_select_new=True, auto_record_on_attach=False)

    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)
    configure_logging(args.log_level, args.log_file)
    args.output_dir = ensure_directory(args.output_dir)

    try:
        asyncio.run(monitor_loop(args))
    except KeyboardInterrupt:
        logger.info("Interrupted by user")


if __name__ == "__main__":
    main()
