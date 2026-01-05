"""Mock audio device for testing Audio module.

Provides a sounddevice-compatible interface for testing without physical audio hardware.
"""

from __future__ import annotations

import numpy as np
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple, Union


@dataclass
class MockAudioDeviceInfo:
    """Information about a mock audio device."""
    name: str = "Mock Audio Input"
    index: int = 0
    hostapi: int = 0
    max_input_channels: int = 2
    max_output_channels: int = 0
    default_low_input_latency: float = 0.01
    default_high_input_latency: float = 0.1
    default_low_output_latency: float = 0.01
    default_high_output_latency: float = 0.1
    default_samplerate: float = 48000.0


class MockInputStream:
    """Mock audio input stream."""

    def __init__(
        self,
        samplerate: float = 48000,
        channels: int = 2,
        dtype: str = "float32",
        blocksize: int = 1024,
        callback: Optional[Callable] = None,
        device: Optional[int] = None,
        **kwargs,
    ):
        """Initialize mock input stream.

        Args:
            samplerate: Sample rate in Hz
            channels: Number of channels
            dtype: Data type for samples
            blocksize: Block size for callbacks
            callback: Callback function for streaming
            device: Device index (ignored for mock)
            **kwargs: Additional arguments (ignored)
        """
        self.samplerate = samplerate
        self.channels = channels
        self.dtype = dtype
        self.blocksize = blocksize
        self.callback = callback
        self.device = device

        self._active = False
        self._stopped = False
        self._stream_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Audio generation settings
        self._generate_sine = False
        self._sine_frequency = 440.0
        self._generate_noise = True
        self._noise_amplitude = 0.01

    @property
    def active(self) -> bool:
        """Return True if stream is active."""
        return self._active

    @property
    def stopped(self) -> bool:
        """Return True if stream is stopped."""
        return self._stopped

    def start(self) -> None:
        """Start the mock stream."""
        if self._active:
            return

        self._active = True
        self._stopped = False
        self._stop_event.clear()

        if self.callback:
            self._stream_thread = threading.Thread(target=self._callback_loop, daemon=True)
            self._stream_thread.start()

    def stop(self) -> None:
        """Stop the mock stream."""
        self._active = False
        self._stopped = True
        self._stop_event.set()

        if self._stream_thread:
            self._stream_thread.join(timeout=1.0)
            self._stream_thread = None

    def close(self) -> None:
        """Close the mock stream."""
        self.stop()

    def abort(self) -> None:
        """Abort the mock stream."""
        self.stop()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()

    def _callback_loop(self) -> None:
        """Generate audio data and call the callback."""
        sample_index = 0
        block_duration = self.blocksize / self.samplerate

        while not self._stop_event.is_set():
            # Generate audio block
            indata = self._generate_audio_block(sample_index)
            sample_index += self.blocksize

            # Call callback with generated data
            if self.callback:
                try:
                    self.callback(indata, self.blocksize, None, None)
                except Exception:
                    break

            # Sleep for block duration
            self._stop_event.wait(block_duration)

    def _generate_audio_block(self, start_sample: int) -> np.ndarray:
        """Generate a block of mock audio data.

        Args:
            start_sample: Starting sample index

        Returns:
            Audio data array of shape (blocksize, channels)
        """
        samples = np.zeros((self.blocksize, self.channels), dtype=np.float32)

        if self._generate_sine:
            # Generate sine wave
            t = (np.arange(self.blocksize) + start_sample) / self.samplerate
            sine = np.sin(2 * np.pi * self._sine_frequency * t)
            for ch in range(self.channels):
                samples[:, ch] = sine * 0.5

        if self._generate_noise:
            # Add low-level noise
            noise = np.random.randn(self.blocksize, self.channels) * self._noise_amplitude
            samples += noise.astype(np.float32)

        # Clip to valid range
        np.clip(samples, -1.0, 1.0, out=samples)

        return samples


class MockSoundDevice:
    """Mock sounddevice module for testing.

    Replaces the sounddevice module with mock implementations.

    Usage:
        # Patch sounddevice
        import sys
        sys.modules['sounddevice'] = MockSoundDevice()

        # Or use as context manager for temporary patching
        with MockSoundDevice.patch():
            # Your test code here
            pass
    """

    # Class-level device registry
    _devices: List[MockAudioDeviceInfo] = [
        MockAudioDeviceInfo(name="Mock Audio Input", index=0),
        MockAudioDeviceInfo(name="Mock USB Microphone", index=1, max_input_channels=1),
    ]
    _default_input: int = 0
    _default_output: int = -1

    # Stream class
    InputStream = MockInputStream

    def __init__(self):
        """Initialize mock sounddevice module."""
        self._active_streams: List[MockInputStream] = []

    @classmethod
    def query_devices(cls, device: Optional[Union[int, str]] = None, kind: Optional[str] = None) -> Any:
        """Query available devices.

        Args:
            device: Device index or name to query
            kind: 'input', 'output', or None for all

        Returns:
            Device info or list of devices
        """
        if device is not None:
            if isinstance(device, int):
                if 0 <= device < len(cls._devices):
                    return cls._devices[device].__dict__
                raise ValueError(f"Invalid device index: {device}")
            else:
                # Search by name
                for dev in cls._devices:
                    if device.lower() in dev.name.lower():
                        return dev.__dict__
                raise ValueError(f"Device not found: {device}")

        if kind == "input":
            inputs = [d for d in cls._devices if d.max_input_channels > 0]
            if inputs:
                return inputs[0].__dict__
            return None

        if kind == "output":
            outputs = [d for d in cls._devices if d.max_output_channels > 0]
            if outputs:
                return outputs[0].__dict__
            return None

        # Return all devices
        return [d.__dict__ for d in cls._devices]

    @classmethod
    def default(cls) -> Tuple[int, int]:
        """Get default input and output device indices."""
        return (cls._default_input, cls._default_output)

    @classmethod
    def check_input_settings(
        cls,
        device: Optional[int] = None,
        channels: Optional[int] = None,
        dtype: Optional[str] = None,
        samplerate: Optional[float] = None,
        **kwargs,
    ) -> None:
        """Check if input settings are valid (no-op for mock)."""
        pass

    @classmethod
    def check_output_settings(cls, **kwargs) -> None:
        """Check if output settings are valid (no-op for mock)."""
        pass

    @classmethod
    def add_mock_device(cls, device: MockAudioDeviceInfo) -> None:
        """Add a mock device to the registry.

        Args:
            device: Device info to add
        """
        device.index = len(cls._devices)
        cls._devices.append(device)

    @classmethod
    def clear_mock_devices(cls) -> None:
        """Clear all mock devices and restore defaults."""
        cls._devices = [
            MockAudioDeviceInfo(name="Mock Audio Input", index=0),
        ]
        cls._default_input = 0
        cls._default_output = -1

    @classmethod
    def patch(cls):
        """Context manager to temporarily patch sounddevice.

        Usage:
            with MockSoundDevice.patch():
                import sounddevice as sd
                # sd is now the mock
        """
        return _SoundDevicePatcher(cls())


class _SoundDevicePatcher:
    """Context manager for patching sounddevice."""

    def __init__(self, mock: MockSoundDevice):
        self.mock = mock
        self._original = None

    def __enter__(self):
        import sys
        self._original = sys.modules.get('sounddevice')
        sys.modules['sounddevice'] = self.mock
        return self.mock

    def __exit__(self, *args):
        import sys
        if self._original is not None:
            sys.modules['sounddevice'] = self._original
        else:
            sys.modules.pop('sounddevice', None)
