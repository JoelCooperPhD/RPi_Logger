"""Webcam audio recorder for built-in microphones.

Provides optional audio recording for USB webcams that have
integrated microphones. The audio is recorded alongside the
video stream and synchronized via timing metadata.
"""

from __future__ import annotations

import contextlib
import csv
import logging
import queue
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

# Optional import - sounddevice may not be installed
try:
    import sounddevice as sd
    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    SOUNDDEVICE_AVAILABLE = False
    sd = None  # type: ignore


# Audio recording parameters
AUDIO_BIT_DEPTH = 16
AUDIO_CHANNELS = 2  # Stereo for webcam mics (will be converted to mono)
DEFAULT_SAMPLE_RATE = 48000


@dataclass
class WebcamAudioInfo:
    """Information about a webcam's built-in microphone."""
    sounddevice_index: int
    channels: int = 2
    sample_rate: float = 48000.0
    alsa_card: Optional[int] = None

    @classmethod
    def from_command(cls, command: dict) -> Optional["WebcamAudioInfo"]:
        """Create from assign_device command data."""
        audio_index = command.get("camera_audio_index")
        if audio_index is None:
            return None
        return cls(
            sounddevice_index=int(audio_index),
            channels=int(command.get("camera_audio_channels", 2)),
            sample_rate=float(command.get("camera_audio_sample_rate", 48000.0)),
            alsa_card=command.get("camera_audio_alsa_card"),
        )


class WebcamAudioRecorder:
    """Records audio from a webcam's built-in microphone.

    This is a simplified recorder designed to work alongside the
    video capture. It records to a WAV file with timing metadata.
    """

    def __init__(
        self,
        audio_info: WebcamAudioInfo,
        logger: logging.Logger,
    ) -> None:
        if not SOUNDDEVICE_AVAILABLE:
            raise RuntimeError("sounddevice not available")

        self.audio_info = audio_info
        self.logger = logger.getChild("WebcamAudio")

        self._stream: Optional[sd.InputStream] = None
        self._recording = False
        self._write_queue: queue.Queue = queue.Queue(maxsize=128)
        self._writer_thread: Optional[threading.Thread] = None
        self._writer_stop = threading.Event()

        # Recording state
        self._wave_path: Optional[Path] = None
        self._csv_path: Optional[Path] = None
        self._chunk_counter = 0
        self._total_frames = 0
        self._dropped_blocks = 0
        self._sample_rate = int(audio_info.sample_rate)

    @property
    def is_recording(self) -> bool:
        return self._recording

    def start_stream(self) -> None:
        """Start the audio input stream (for monitoring)."""
        if self._stream is not None:
            return

        channels = min(self.audio_info.channels, 2)  # Max stereo

        self.logger.debug(
            "Opening webcam audio stream: device=%d, rate=%d, channels=%d",
            self.audio_info.sounddevice_index,
            self._sample_rate,
            channels,
        )

        try:
            self._stream = sd.InputStream(
                device=self.audio_info.sounddevice_index,
                channels=channels,
                samplerate=self._sample_rate,
                dtype="float32",
                callback=self._audio_callback,
                blocksize=0,
            )
            self._stream.start()

            # Check actual sample rate
            actual_rate = int(self._stream.samplerate)
            if actual_rate != self._sample_rate:
                self.logger.info(
                    "Sample rate adjusted from %d to %d",
                    self._sample_rate,
                    actual_rate,
                )
                self._sample_rate = actual_rate

            self.logger.info("Webcam audio stream started")

        except Exception as e:
            self._stream = None
            self.logger.error("Failed to start webcam audio stream: %s", e)
            raise

    def stop_stream(self) -> None:
        """Stop the audio input stream."""
        if self._stream is None:
            return

        stream = self._stream
        self._stream = None

        try:
            stream.stop()
            stream.close()
        except Exception as e:
            self.logger.debug("Stream close error: %s", e)

        self.logger.info("Webcam audio stream stopped")

    def start_recording(self, session_dir: Path, camera_id: str, trial_number: int) -> None:
        """Start recording audio to a WAV file."""
        if self._recording:
            return

        session_dir.mkdir(parents=True, exist_ok=True)

        # Generate filenames
        safe_id = camera_id.replace(":", "-").replace("/", "-")
        prefix = f"T{trial_number:03d}"
        self._wave_path = session_dir / f"{prefix}_CAM_{safe_id}_audio.wav"
        self._csv_path = session_dir / f"{prefix}_CAM_{safe_id}_audio_timing.csv"

        # Open wave file
        wave_handle = wave.open(str(self._wave_path), "wb")
        wave_handle.setnchannels(1)  # Mono output
        wave_handle.setsampwidth(AUDIO_BIT_DEPTH // 8)
        wave_handle.setframerate(self._sample_rate)

        # Reset counters
        self._chunk_counter = 0
        self._total_frames = 0
        self._dropped_blocks = 0
        self._writer_stop.clear()
        self._write_queue = queue.Queue(maxsize=128)

        # Start writer thread
        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            args=(wave_handle,),
            name="WebcamAudioWriter",
            daemon=True,
        )
        self._writer_thread.start()

        self._recording = True
        self.logger.info("Recording webcam audio to %s", self._wave_path.name)

    def stop_recording(self) -> Optional[Path]:
        """Stop recording and return the audio file path."""
        if not self._recording:
            return None

        self._recording = False
        self._writer_stop.set()

        if self._writer_thread:
            self._writer_thread.join(timeout=5)
            self._writer_thread = None

        path = self._wave_path
        self._wave_path = None
        self._csv_path = None

        if path:
            self.logger.info(
                "Webcam audio recording finished: %s (%d frames)",
                path.name,
                self._total_frames,
            )

        return path

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info,
        status: sd.CallbackFlags,
    ) -> None:
        """Handle incoming audio data."""
        if not self._recording:
            return

        now_unix = time.time()
        now_mono = time.perf_counter()

        # Convert to mono by averaging channels
        if indata.ndim > 1 and indata.shape[1] > 1:
            mono = indata.mean(axis=1)
        else:
            mono = indata.flatten()

        # Convert to PCM bytes
        pcm_bytes = self._to_pcm_bytes(mono)

        chunk_index = self._chunk_counter + 1
        total_frames = self._total_frames + frames

        chunk = {
            "data": pcm_bytes,
            "frames": frames,
            "chunk_index": chunk_index,
            "unix_time": now_unix,
            "mono_time": now_mono,
            "total_frames": total_frames,
        }

        self._chunk_counter = chunk_index
        self._total_frames = total_frames

        try:
            self._write_queue.put_nowait(chunk)
        except queue.Full:
            self._dropped_blocks += 1
            if self._dropped_blocks % 25 == 0:
                self.logger.warning(
                    "Dropped %d audio blocks due to slow writer",
                    self._dropped_blocks,
                )

        if status:
            self.logger.debug("Audio callback status: %s", status)

    def _writer_loop(self, wave_handle: wave.Wave_write) -> None:
        """Background thread that writes audio to disk."""
        csv_file = None
        csv_writer = None

        try:
            # Open timing CSV
            if self._csv_path:
                csv_file = open(self._csv_path, "w", newline="", encoding="utf-8")
                csv_writer = csv.writer(csv_file)
                csv_writer.writerow([
                    "chunk_index",
                    "frames",
                    "total_frames",
                    "record_time_unix",
                    "record_time_mono",
                    "write_time_unix",
                ])

            # Process chunks
            while not self._writer_stop.is_set() or not self._write_queue.empty():
                try:
                    chunk = self._write_queue.get(timeout=0.2)
                except queue.Empty:
                    continue

                try:
                    wave_handle.writeframes(chunk["data"])
                    write_time = time.time()

                    if csv_writer:
                        csv_writer.writerow([
                            chunk["chunk_index"],
                            chunk["frames"],
                            chunk["total_frames"],
                            f"{chunk['unix_time']:.6f}",
                            f"{chunk['mono_time']:.9f}",
                            f"{write_time:.6f}",
                        ])

                except Exception as e:
                    self.logger.error("Failed to write audio chunk: %s", e)
                    break

        finally:
            with contextlib.suppress(Exception):
                wave_handle.close()
            if csv_file:
                with contextlib.suppress(Exception):
                    csv_file.flush()
                    csv_file.close()

    def _to_pcm_bytes(self, samples: np.ndarray) -> bytes:
        """Convert float32 samples to 16-bit PCM bytes."""
        array = np.asarray(samples, dtype=np.float32)
        scaled = np.clip(array, -1.0, 1.0)
        max_int = (2 ** (AUDIO_BIT_DEPTH - 1)) - 1
        int_samples = (scaled * max_int).astype(np.int16)
        return int_samples.tobytes()


__all__ = ["WebcamAudioRecorder", "WebcamAudioInfo", "SOUNDDEVICE_AVAILABLE"]
