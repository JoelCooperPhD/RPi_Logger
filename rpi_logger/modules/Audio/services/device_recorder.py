"""Low-level audio recorder that streams samples from sounddevice to disk."""

from __future__ import annotations

import contextlib
import logging
import queue
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd

from ..domain import AUDIO_BIT_DEPTH, AUDIO_CHANNELS_MONO, AudioDeviceInfo, LevelMeter


@dataclass(slots=True)
class RecordingHandle:
    file_path: Path
    session_dir: Path
    trial_number: int


class AudioDeviceRecorder:
    """Owns the sounddevice stream + sample buffering for one device."""

    def __init__(
        self,
        device: AudioDeviceInfo,
        sample_rate: int,
        level_meter: LevelMeter,
        logger: logging.Logger,
    ) -> None:
        self.device = device
        self.sample_rate = max(1, int(sample_rate))
        self.level_meter = level_meter
        self.logger = logger.getChild(f"Dev{device.device_id}")
        self.stream: Optional[sd.InputStream] = None
        self.recording = False
        self._last_status: Optional[str] = None
        self._writer_thread: Optional[threading.Thread] = None
        self._writer_stop = threading.Event()
        self._write_queue: queue.Queue[bytes] = queue.Queue(maxsize=64)
        self._active_handle: Optional[RecordingHandle] = None
        self._dropped_blocks = 0

    # ------------------------------------------------------------------
    # Stream lifecycle

    def start_stream(self) -> None:
        if self.stream is not None:
            return

        def _callback(indata, frames, time_info, status):
            self._handle_callback(indata, status)

        channels = max(1, min(self.device.channels or 1, AUDIO_CHANNELS_MONO))
        self.logger.debug(
            "Opening input stream for device %d (%s)",
            self.device.device_id,
            self.device.name,
        )
        try:
            stream = sd.InputStream(
                device=self.device.device_id,
                channels=channels,
                samplerate=self.sample_rate,
                dtype="float32",
                callback=_callback,
                blocksize=0,
            )
            stream.start()
            try:
                actual_rate = int(stream.samplerate)
            except Exception:
                actual_rate = None
            if actual_rate and actual_rate != self.sample_rate:
                self.logger.info(
                    "Device %d sample rate adjusted from %d to %d",
                    self.device.device_id,
                    self.sample_rate,
                    actual_rate,
                )
                self.sample_rate = actual_rate
            self.stream = stream
            self.logger.info("Input stream started (%d Hz)", self.sample_rate)
        except Exception as exc:
            self.stream = None
            self.logger.error("Failed to start stream: %s", exc)
            raise

    def stop_stream(self) -> None:
        stream = self.stream
        if stream is None:
            return
        self.stream = None
        self.logger.debug("Stopping input stream for device %d", self.device.device_id)
        try:
            stream.stop()
            stream.close()
        except Exception as exc:
            self.logger.debug("Stream close error: %s", exc)
        self.logger.info("Input stream stopped")

    # ------------------------------------------------------------------
    # Recording helpers

    def begin_recording(self, session_dir: Path, trial_number: int) -> None:
        if self.recording:
            return
        session_dir.mkdir(parents=True, exist_ok=True)
        file_path = self._make_filename(session_dir, trial_number)
        wave_handle = wave.open(str(file_path), "wb")
        wave_handle.setnchannels(1)
        wave_handle.setsampwidth(AUDIO_BIT_DEPTH // 8)
        wave_handle.setframerate(self.sample_rate)

        self._writer_stop.clear()
        self._write_queue = queue.Queue(maxsize=128)
        self._active_handle = RecordingHandle(file_path=file_path, session_dir=session_dir, trial_number=trial_number)
        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            args=(wave_handle,),
            name=f"AudioWriter-{self.device.device_id}",
            daemon=True,
        )
        self._writer_thread.start()
        self.recording = True
        self.logger.info("Recording to %s", file_path.name)

    def finish_recording(self) -> Optional[Path]:
        if not self.recording:
            return None
        self.recording = False
        self._writer_stop.set()
        thread = self._writer_thread
        if thread is not None:
            thread.join(timeout=5)
        handle = self._active_handle
        self._writer_thread = None
        self._active_handle = None
        self._dropped_blocks = 0
        if handle:
            self.logger.info("Recording finished (%s)", handle.file_path.name)
        return handle.file_path if handle else None

    # ------------------------------------------------------------------
    # Audio callback

    def _handle_callback(self, indata, status: sd.CallbackFlags) -> None:
        mono = indata[:, 0] if indata.ndim > 1 else indata
        now = time.time()
        try:
            self.level_meter.add_samples(mono.tolist(), now)
        except Exception:
            pass

        if self.recording:
            chunk = self._to_pcm_bytes(mono)
            try:
                self._write_queue.put_nowait(chunk)
            except queue.Full:
                self._dropped_blocks += 1
                if self._dropped_blocks % 25 == 0:
                    self.logger.warning("Dropped %d audio blocks due to slow writer", self._dropped_blocks)

        if status:
            status_str = str(status)
            if status_str != self._last_status:
                self.logger.warning("Audio callback status: %s", status_str)
                self._last_status = status_str

    def _writer_loop(self, wave_handle: wave.Wave_write) -> None:
        try:
            while not self._writer_stop.is_set() or not self._write_queue.empty():
                try:
                    chunk = self._write_queue.get(timeout=0.2)
                except queue.Empty:
                    continue
                try:
                    wave_handle.writeframes(chunk)
                except Exception as exc:
                    self.logger.error("Failed to write audio chunk: %s", exc)
                    break
        finally:
            with contextlib.suppress(Exception):
                wave_handle.close()

    def _to_pcm_bytes(self, samples) -> bytes:
        array = np.asarray(samples, dtype=np.float32)
        if array.ndim > 1:
            array = array[:, 0]
        scaled = np.clip(array, -1.0, 1.0)
        max_int = (2 ** (AUDIO_BIT_DEPTH - 1)) - 1
        int_samples = (scaled * max_int).astype(np.int16)
        return int_samples.tobytes()

    def _make_filename(self, session_dir: Path, trial_number: int) -> Path:
        safe_name = (
            self.device.name.replace(" ", "-")
            .replace(":", "")
            .replace("_", "-")
            .lower()
        )
        session_name = session_dir.name
        if "_" in session_name:
            timestamp = session_name.split("_", 1)[1]
        else:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_AUDIO_trial{trial_number:03d}_MIC{self.device.device_id}_{safe_name}.wav"
        return session_dir / filename


__all__ = ["AudioDeviceRecorder", "RecordingHandle"]
