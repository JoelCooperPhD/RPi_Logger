"""Low-level audio recorder that streams samples from sounddevice to disk."""

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

import numpy as np
import sounddevice as sd

from ..domain import AUDIO_BIT_DEPTH, AUDIO_CHANNELS_MONO, AudioDeviceInfo, LevelMeter
from rpi_logger.modules.base.storage_utils import module_filename_prefix

_CSV_FLUSH_INTERVAL = 200


@dataclass(slots=True)
class RecordingHandle:
    file_path: Path
    timing_csv_path: Path
    session_dir: Path
    trial_number: int
    device_id: int
    device_name: str
    start_time_unix: float | None = None
    start_time_monotonic: float | None = None


@dataclass(slots=True)
class AudioChunk:
    data: bytes
    frames: int
    chunk_index: int
    unix_time: float
    monotonic_time: float
    adc_timestamp: float | None
    total_frames: int


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
        self.stream: sd.InputStream | None = None
        self.recording = False
        self._last_status: str | None = None
        self._writer_thread: threading.Thread | None = None
        self._writer_stop = threading.Event()
        self._write_queue: queue.Queue[AudioChunk] = queue.Queue(maxsize=64)
        self._active_handle: RecordingHandle | None = None
        self._dropped_blocks = 0
        self._chunk_counter = 0
        self._total_frames = 0
        self._meter_errors = 0

    # ------------------------------------------------------------------
    # Stream lifecycle

    def start_stream(self) -> None:
        if self.stream is not None:
            return

        def _callback(indata, frames, time_info, status):
            self._handle_callback(indata, frames, time_info, status)

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
        timing_csv = self._make_timing_filename(file_path)
        wave_handle = wave.open(str(file_path), "wb")
        wave_handle.setnchannels(1)
        wave_handle.setsampwidth(AUDIO_BIT_DEPTH // 8)
        wave_handle.setframerate(self.sample_rate)

        self._writer_stop.clear()
        self._write_queue = queue.Queue(maxsize=128)
        self._chunk_counter = 0
        self._total_frames = 0
        handle = RecordingHandle(
            file_path=file_path,
            timing_csv_path=timing_csv,
            session_dir=session_dir,
            trial_number=trial_number,
            device_id=self.device.device_id,
            device_name=self.device.name,
        )
        self._active_handle = handle
        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            args=(wave_handle, handle),
            name=f"AudioWriter-{self.device.device_id}",
            daemon=True,
        )
        self._writer_thread.start()
        self.recording = True
        self.logger.info("Recording to %s (timing -> %s)", file_path.name, timing_csv.name)

    def finish_recording(self) -> RecordingHandle | None:
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
            self.logger.info(
                "Recording finished (%s) with timing metadata in %s",
                handle.file_path.name,
                handle.timing_csv_path.name,
            )
        return handle

    # ------------------------------------------------------------------
    # Audio callback

    def _handle_callback(self, indata, frames: int, time_info, status: sd.CallbackFlags) -> None:
        mono = indata[:, 0] if indata.ndim > 1 else indata
        now_unix = time.time()
        now_monotonic = time.perf_counter()
        try:
            self.level_meter.add_samples(mono, now_unix)
        except Exception:
            self._meter_errors += 1
            if self._meter_errors == 1:
                self.logger.warning("Level meter error (suppressing further)", exc_info=True)

        if self.recording and self._active_handle:
            chunk_bytes = self._to_pcm_bytes(mono)
            chunk_index = self._chunk_counter + 1
            total_frames = self._total_frames + frames
            adc_time = self._extract_time_info(time_info)
            chunk = AudioChunk(
                data=chunk_bytes,
                frames=frames,
                chunk_index=chunk_index,
                unix_time=now_unix,
                monotonic_time=now_monotonic,
                adc_timestamp=adc_time,
                total_frames=total_frames,
            )
            self._chunk_counter = chunk_index
            self._total_frames = total_frames

            if self._active_handle.start_time_unix is None:
                self._active_handle.start_time_unix = adc_time or now_unix
                self._active_handle.start_time_monotonic = now_monotonic

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
            status_str = str(status)
            if status_str != self._last_status:
                self.logger.warning("Audio callback status: %s", status_str)
                self._last_status = status_str

    def _writer_loop(self, wave_handle: wave.Wave_write, handle: RecordingHandle) -> None:
        csv_file = None
        writer = None
        written_rows = 0
        try:
            csv_file = open(handle.timing_csv_path, 'w', newline='', encoding='utf-8')
            writer = csv.writer(csv_file)
            writer.writerow([
                'trial',
                'module',
                'device_id',
                'label',
                'record_time_unix',
                'record_time_mono',
                'device_time_unix',
                'device_time_seconds',
                'write_time_unix',
                'write_time_mono',
                'chunk_index',
                'frames',
                'total_frames',
            ])

            while not self._writer_stop.is_set() or not self._write_queue.empty():
                try:
                    chunk = self._write_queue.get(timeout=0.2)
                except queue.Empty:
                    continue
                try:
                    wave_handle.writeframes(chunk.data)
                    write_time_unix = time.time()
                    write_time_mono = time.perf_counter()
                    writer.writerow([
                        handle.trial_number,
                        'Audio',
                        handle.device_id,
                        handle.device_name,
                        f"{chunk.unix_time:.6f}",
                        f"{chunk.monotonic_time:.9f}",
                        '',
                        f"{chunk.adc_timestamp:.9f}" if chunk.adc_timestamp is not None else '',
                        f"{write_time_unix:.6f}",
                        f"{write_time_mono:.9f}",
                        chunk.chunk_index,
                        chunk.frames,
                        chunk.total_frames,
                    ])
                    written_rows += 1
                    if written_rows % _CSV_FLUSH_INTERVAL == 0:
                        csv_file.flush()
                except Exception as exc:
                    self.logger.error("Failed to persist audio chunk: %s", exc)
                    break
        finally:
            with contextlib.suppress(Exception):
                wave_handle.close()
            if csv_file is not None:
                with contextlib.suppress(Exception):
                    csv_file.flush()
                    csv_file.close()

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
        prefix = module_filename_prefix(session_dir, "Audio", trial_number, code="AUD")
        filename = f"{prefix}_MIC{self.device.device_id}_{safe_name}.wav"
        return session_dir / filename

    def _make_timing_filename(self, audio_path: Path) -> Path:
        return audio_path.with_name(f"{audio_path.stem}_timing.csv")

    def _extract_time_info(self, time_info) -> float | None:
        if not time_info:
            return None
        for attr in ("input_buffer_adc_time", "current_time", "output_buffer_dac_time"):
            value = getattr(time_info, attr, None)
            if value:
                try:
                    return float(value)
                except Exception:
                    continue
        return None


__all__ = ["AudioDeviceRecorder", "RecordingHandle", "AudioChunk"]
