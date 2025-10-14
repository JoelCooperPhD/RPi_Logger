#!/usr/bin/env python3
"""
Audio recording manager.

Coordinates recording for a single audio device.
"""

import asyncio
import logging
import wave
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import numpy as np

from ..constants import AUDIO_BIT_DEPTH, AUDIO_CHANNELS_MONO, CLEANUP_TIMEOUT_SECONDS, MAX_AUDIO_BUFFER_CHUNKS

logger = logging.getLogger("AudioRecordingManager")


class AudioRecordingManager:
    """Manages recording for a single audio device."""

    def __init__(self, device_id: int, device_name: str, sample_rate: int):
        """
        Initialize recording manager.

        Args:
            device_id: Audio device ID
            device_name: Human-readable device name
            sample_rate: Recording sample rate in Hz
        """
        self.logger = logging.getLogger(f"AudioRecorder{device_id}")
        self.device_id = device_id
        self.device_name = device_name
        self.sample_rate = sample_rate
        self.audio_data: List[np.ndarray] = []
        self.frames_recorded = 0
        self.recording = False
        self.audio_path: Optional[Path] = None

    def start_recording(self) -> None:
        """Start recording (prepare buffers)."""
        if self.recording:
            return

        self.audio_data = []
        self.frames_recorded = 0
        self.recording = True
        self.logger.debug("Recording started (buffers prepared)")

    def add_audio_chunk(self, audio_chunk: np.ndarray) -> None:
        """
        Add audio chunk to recording buffer with overflow protection.

        Args:
            audio_chunk: Audio data array
        """
        if not self.recording:
            return

        self.audio_data.append(audio_chunk.copy())
        self.frames_recorded += len(audio_chunk)

        # Warn if buffer is growing too large (prevents unbounded memory growth)
        if len(self.audio_data) > MAX_AUDIO_BUFFER_CHUNKS:
            self.logger.warning(
                "Audio buffer exceeds %d chunks (%d frames, ~%.1f seconds) - consider stopping recording",
                MAX_AUDIO_BUFFER_CHUNKS,
                self.frames_recorded,
                self.frames_recorded / self.sample_rate
            )

    async def stop_recording(self, session_dir: Path, recording_count: int) -> Optional[Path]:
        """
        Stop recording and save to file (async, non-blocking).

        Args:
            session_dir: Directory to save recording
            recording_count: Recording sequence number

        Returns:
            Path to saved file, or None if failed
        """
        if not self.recording:
            return None

        self.recording = False

        if not self.audio_data:
            self.logger.warning("No audio data to save")
            return None

        # Generate filename
        timestamp = datetime.now().strftime("%H%M%S")
        safe_device_name = self.device_name.replace(' ', '_').replace(':', '')
        filename = f"mic{self.device_id}_{safe_device_name}_rec{recording_count:03d}_{timestamp}.wav"
        self.audio_path = session_dir / filename

        # Process audio data in thread pool using modern asyncio.to_thread
        def prepare_audio_data():
            """Concatenate and convert audio data to int16."""
            audio_array = np.concatenate(self.audio_data)
            return (audio_array * 32767).astype(np.int16)

        audio_int16 = await asyncio.to_thread(prepare_audio_data)

        # Write WAV file in thread pool
        def write_wav_file():
            """Write WAV file to disk."""
            with wave.open(str(self.audio_path), 'wb') as wf:
                wf.setnchannels(AUDIO_CHANNELS_MONO)
                wf.setsampwidth(AUDIO_BIT_DEPTH // 8)
                wf.setframerate(self.sample_rate)
                wf.writeframes(audio_int16.tobytes())

        try:
            await asyncio.to_thread(write_wav_file)
            self.logger.info("Saved recording: %s", filename)
            return self.audio_path

        except Exception as e:
            self.logger.error("Failed to save recording: %s", e)
            return None

    async def cleanup(self) -> None:
        """Clean up recording resources."""
        self.recording = False
        self.audio_data.clear()
        self.frames_recorded = 0
        self.logger.debug("Cleanup completed")
