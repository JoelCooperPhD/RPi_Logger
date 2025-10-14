#!/usr/bin/env python3
"""
Single audio device handler.

Manages recording from a single audio input device with async architecture.
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd

from .recording import AudioRecordingManager
from .constants import (
    AUDIO_BLOCKSIZE,
    AUDIO_CHANNELS_MONO,
    AUDIO_DTYPE,
    FEEDBACK_INTERVAL_SECONDS,
    STREAM_STOP_TIMEOUT_SECONDS,
)

logger = logging.getLogger("AudioHandler")


class AudioHandler:
    """Handles individual audio device with recording capabilities."""

    def __init__(self, device_id: int, device_info: dict, sample_rate: int):
        """
        Initialize audio handler.

        Args:
            device_id: Audio device ID
            device_info: Device information dictionary
            sample_rate: Recording sample rate in Hz
        """
        self.logger = logging.getLogger(f"AudioDevice{device_id}")
        self.device_id = device_id
        self.device_info = device_info
        self.device_name = device_info['name']
        self.sample_rate = sample_rate
        self.recording = False

        # Audio stream
        self.stream: Optional[sd.InputStream] = None

        # Recording manager
        self.recording_manager = AudioRecordingManager(
            device_id=device_id,
            device_name=self.device_name,
            sample_rate=sample_rate
        )

        # Feedback tracking
        self.feedback_queue: Optional[asyncio.Queue] = None
        self.frames_since_feedback = 0

        self.logger.info("Initialized device %d: %s", device_id, self.device_name)

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info, status: sd.CallbackFlags) -> None:
        """
        Audio input callback from sounddevice.

        Args:
            indata: Input audio data
            frames: Number of frames
            time_info: Timing information (dict with input_buffer_adc_time, etc.)
            status: Stream status flags
        """
        if not self.recording:
            return

        # Add audio chunk to recording manager
        self.recording_manager.add_audio_chunk(indata)

        # Send feedback periodically
        self.frames_since_feedback += frames
        if self.frames_since_feedback >= (self.sample_rate * FEEDBACK_INTERVAL_SECONDS):
            self.frames_since_feedback = 0
            if self.feedback_queue:
                try:
                    self.feedback_queue.put_nowait(f'feedback:{self.device_id}')
                except asyncio.QueueFull:
                    pass

        # Report stream errors
        if status:
            if self.feedback_queue:
                try:
                    self.feedback_queue.put_nowait(f'error:{self.device_id}:{status}')
                except asyncio.QueueFull:
                    pass

    def start_stream(self, feedback_queue: Optional[asyncio.Queue] = None) -> bool:
        """
        Start audio input stream.

        Args:
            feedback_queue: Optional queue for status messages

        Returns:
            True if stream started successfully
        """
        if self.stream is not None:
            self.logger.warning("Stream already running")
            return False

        self.feedback_queue = feedback_queue

        try:
            self.stream = sd.InputStream(
                device=self.device_id,
                callback=self._audio_callback,
                channels=AUDIO_CHANNELS_MONO,
                samplerate=self.sample_rate,
                dtype=AUDIO_DTYPE,
                blocksize=AUDIO_BLOCKSIZE
            )
            self.stream.start()
            self.logger.info("Audio stream started")
            return True

        except Exception as e:
            self.logger.error("Failed to start stream: %s", e)
            self.stream = None
            return False

    def start_recording(self) -> bool:
        """
        Start recording audio.

        Returns:
            True if recording started successfully
        """
        if self.recording:
            self.logger.warning("Already recording")
            return False

        if self.stream is None:
            self.logger.error("Cannot record - stream not started")
            return False

        self.recording_manager.start_recording()
        self.recording = True
        self.frames_since_feedback = 0
        self.logger.info("Recording started")
        return True

    async def stop_recording(self, session_dir: Path, recording_count: int) -> Optional[Path]:
        """
        Stop recording and save file.

        Args:
            session_dir: Directory to save recording
            recording_count: Recording sequence number

        Returns:
            Path to saved file
        """
        if not self.recording:
            return None

        self.recording = False
        audio_path = await self.recording_manager.stop_recording(session_dir, recording_count)
        self.logger.info("Recording stopped")
        return audio_path

    async def cleanup(self) -> None:
        """Clean up audio device resources (async, non-blocking)."""
        if self.recording:
            self.recording = False

        if self.stream:
            # Run potentially blocking stream operations in thread pool
            def _close_stream():
                try:
                    self.stream.stop()
                    self.stream.close()
                    self.logger.debug("Stream closed")
                except Exception as e:
                    self.logger.debug("Stream close error: %s", e)

            try:
                await asyncio.to_thread(_close_stream)
            finally:
                self.stream = None

        await self.recording_manager.cleanup()
        self.logger.info("Cleanup completed")
