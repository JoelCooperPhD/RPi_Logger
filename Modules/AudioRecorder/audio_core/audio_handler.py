
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

logger = logging.getLogger(__name__)


class AudioHandler:

    def __init__(self, device_id: int, device_info: dict, sample_rate: int):
        self.logger = logging.getLogger(f"AudioDevice{device_id}")
        self.device_id = device_id
        self.device_info = device_info
        self.device_name = device_info['name']
        self.sample_rate = sample_rate
        self.recording = False

        self.stream: Optional[sd.InputStream] = None

        self.recording_manager = AudioRecordingManager(
            device_id=device_id,
            device_name=self.device_name,
            sample_rate=sample_rate
        )

        self.feedback_queue: Optional[asyncio.Queue] = None
        self.frames_since_feedback = 0

        self.logger.info("Initialized device %d: %s", device_id, self.device_name)

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info, status: sd.CallbackFlags) -> None:
        if not self.recording:
            return

        self.recording_manager.add_audio_chunk(indata)

        self.frames_since_feedback += frames
        if self.frames_since_feedback >= (self.sample_rate * FEEDBACK_INTERVAL_SECONDS):
            self.frames_since_feedback = 0
            if self.feedback_queue:
                try:
                    self.feedback_queue.put_nowait(f'feedback:{self.device_id}')
                except asyncio.QueueFull:
                    pass

        if status:
            if self.feedback_queue:
                try:
                    self.feedback_queue.put_nowait(f'error:{self.device_id}:{status}')
                except asyncio.QueueFull:
                    pass

    def start_stream(self, feedback_queue: Optional[asyncio.Queue] = None) -> bool:
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
        if self.recording:
            self.logger.warning("Already recording")
            return False

        if self.stream is None:
            self.logger.error("Cannot record - stream not started")
            return False

        self.recording_manager.start_recording()
        self.recording = True
        self.frames_since_feedback = 0
        self.logger.info("=" * 80)
        self.logger.info("========== RECORDING STARTED: Device %d ==========", self.device_id)
        self.logger.info("=" * 80)
        return True

    async def stop_recording(self, session_dir: Path, recording_count: int) -> Optional[Path]:
        if not self.recording:
            return None

        self.recording = False
        audio_path = await self.recording_manager.stop_recording(session_dir, recording_count)
        self.logger.info("=" * 80)
        self.logger.info("========== RECORDING STOPPED: Device %d ==========", self.device_id)
        self.logger.info("=" * 80)
        return audio_path

    async def cleanup(self) -> None:
        if self.recording:
            self.recording = False

        if self.stream:
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
