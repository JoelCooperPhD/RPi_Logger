
import asyncio
import logging
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import numpy as np

from ..constants import AUDIO_BIT_DEPTH, AUDIO_CHANNELS_MONO, CLEANUP_TIMEOUT_SECONDS, MAX_AUDIO_BUFFER_CHUNKS
from .csv_logger import AudioCSVLogger

logger = logging.getLogger(__name__)


class AudioRecordingManager:

    def __init__(self, device_id: int, device_name: str, sample_rate: int):
        self.logger = logging.getLogger(f"AudioRecorder{device_id}")
        self.device_id = device_id
        self.device_name = device_name
        self.sample_rate = sample_rate
        self.audio_data: List[np.ndarray] = []
        self.frames_recorded = 0
        self.recording = False
        self.audio_path: Optional[Path] = None
        self.frame_timing_path: Optional[Path] = None

        self._recording_start_time_unix: Optional[float] = None
        self._recording_start_time_monotonic: Optional[float] = None
        self._chunk_counter = 0
        self._csv_logger: Optional[AudioCSVLogger] = None

    def start_recording(self, session_dir: Optional[Path] = None, trial_number: Optional[int] = None, enable_csv_logging: bool = True) -> None:
        if self.recording:
            return

        self.audio_data = []
        self.frames_recorded = 0
        self._chunk_counter = 0
        self._recording_start_time_unix = time.time()
        self._recording_start_time_monotonic = time.perf_counter()
        self.recording = True

        if session_dir and trial_number is not None and enable_csv_logging:
            session_name = session_dir.name
            if "_" in session_name:
                session_timestamp = session_name.split("_", 1)[1]
            else:
                session_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            timing_filename = f"{session_timestamp}_AUDIOTIMING_trial{trial_number:03d}_MIC{self.device_id}.csv"
            self.frame_timing_path = session_dir / timing_filename

            self._csv_logger = AudioCSVLogger(self.device_id, self.frame_timing_path, trial_number)
            try:
                self._csv_logger.start()
            except RuntimeError as e:
                self.logger.warning("Failed to start CSV logger: %s, disabling CSV logging", e)
                self._csv_logger = None

        self.logger.debug("Recording started (buffers prepared) at unix_time=%.6f",
                         self._recording_start_time_unix)

    def add_audio_chunk(self, audio_chunk: np.ndarray) -> None:
        if not self.recording:
            return

        self.audio_data.append(audio_chunk.copy())
        self.frames_recorded += len(audio_chunk)
        self._chunk_counter += 1

        if self._csv_logger is not None:
            self._csv_logger.log_chunk(self._chunk_counter, len(audio_chunk))

        if len(self.audio_data) > MAX_AUDIO_BUFFER_CHUNKS:
            self.logger.warning(
                "Audio buffer exceeds %d chunks (%d frames, ~%.1f seconds) - consider stopping recording",
                MAX_AUDIO_BUFFER_CHUNKS,
                self.frames_recorded,
                self.frames_recorded / self.sample_rate
            )

    async def stop_recording(self, session_dir: Path, trial_number: int) -> Optional[Path]:
        if not self.recording:
            return None

        self.recording = False

        if not self.audio_data:
            self.logger.warning("No audio data to save")
            return None

        session_name = session_dir.name
        if "_" in session_name:
            session_timestamp = session_name.split("_", 1)[1]
        else:
            session_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        safe_device_name = self.device_name.replace(' ', '-').replace(':', '').replace('_', '-').lower()
        filename = f"{session_timestamp}_AUDIO_trial{trial_number:03d}_MIC{self.device_id}_{safe_device_name}.wav"
        self.audio_path = session_dir / filename

        if self._csv_logger is not None:
            try:
                await self._csv_logger.stop()
            except RuntimeError:
                pass
            finally:
                self._csv_logger = None

        def prepare_audio_data():
            audio_array = np.concatenate(self.audio_data)
            return (audio_array * 32767).astype(np.int16)

        audio_int16 = await asyncio.to_thread(prepare_audio_data)

        def write_wav_file():
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

    async def pause_recording(self):
        raise NotImplementedError("Pause not supported by audio recording")

    async def resume_recording(self):
        raise NotImplementedError("Resume not supported by audio recording")

    def get_sync_metadata(self) -> dict:
        """Get synchronization metadata for audio recording"""
        return {
            "device_id": self.device_id,
            "device_name": self.device_name,
            "sample_rate": self.sample_rate,
            "chunk_size": 1024,
            "start_time_unix": self._recording_start_time_unix,
            "start_time_monotonic": self._recording_start_time_monotonic,
            "audio_file": str(self.audio_path) if self.audio_path else None,
            "timing_csv": str(self.frame_timing_path) if self.frame_timing_path else None,
        }

    async def cleanup(self) -> None:
        self.recording = False
        self.audio_data.clear()
        self.frames_recorded = 0

        if self._csv_logger is not None:
            try:
                await asyncio.wait_for(self._csv_logger.stop(), timeout=2.0)
            except asyncio.TimeoutError:
                self.logger.warning("CSV logger stop timed out after 2 seconds")
            except Exception as e:
                self.logger.warning("Error stopping CSV logger: %s", e)
            finally:
                self._csv_logger = None

        self.logger.debug("Cleanup completed")
