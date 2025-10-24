
import asyncio
import logging
import wave
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import numpy as np

from ..constants import AUDIO_BIT_DEPTH, AUDIO_CHANNELS_MONO, CLEANUP_TIMEOUT_SECONDS, MAX_AUDIO_BUFFER_CHUNKS

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

    def start_recording(self) -> None:
        if self.recording:
            return

        self.audio_data = []
        self.frames_recorded = 0
        self.recording = True
        self.logger.debug("Recording started (buffers prepared)")

    def add_audio_chunk(self, audio_chunk: np.ndarray) -> None:
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

        safe_device_name = self.device_name.replace(' ', '_').replace(':', '')
        filename = f"AUDIO_mic{self.device_id}_{safe_device_name}_trial{trial_number:03d}_{session_timestamp}.wav"
        self.audio_path = session_dir / filename

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

    async def cleanup(self) -> None:
        self.recording = False
        self.audio_data.clear()
        self.frames_recorded = 0
        self.logger.debug("Cleanup completed")
