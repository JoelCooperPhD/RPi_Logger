"""Audio recording primitives built on sounddevice with streaming writes."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import queue
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import sounddevice as sd

from ..constants import AUDIO_BIT_DEPTH, AUDIO_CHANNELS_MONO
from ..level_meter import LevelMeter
from ..state import AudioDeviceInfo


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
        self.sample_rate = sample_rate
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


class RecorderService:
    """Manage AudioDeviceRecorder instances keyed by device id."""

    def __init__(
        self,
        logger: logging.Logger,
        sample_rate: int,
        start_timeout: float,
        stop_timeout: float,
    ) -> None:
        self.logger = logger.getChild("RecorderService")
        self.sample_rate = sample_rate
        self.start_timeout = start_timeout
        self.stop_timeout = stop_timeout
        self.recorders: Dict[int, AudioDeviceRecorder] = {}

    async def enable_device(self, device: AudioDeviceInfo, meter: LevelMeter) -> bool:
        recorder = self.recorders.get(device.device_id)
        if recorder is None:
            recorder = AudioDeviceRecorder(device, self.sample_rate, meter, self.logger)
            self.recorders[device.device_id] = recorder

        self.logger.debug("Enabling recorder for device %d (%s)", device.device_id, device.name)
        try:
            await asyncio.wait_for(
                asyncio.to_thread(recorder.start_stream),
                timeout=self.start_timeout,
            )
            return True
        except asyncio.TimeoutError:
            self.logger.error("Timeout starting device %d", device.device_id)
        except Exception as exc:
            self.logger.error("Failed to start device %d: %s", device.device_id, exc)
        self.recorders.pop(device.device_id, None)
        return False

    async def disable_device(self, device_id: int) -> None:
        recorder = self.recorders.pop(device_id, None)
        if not recorder:
            return
        self.logger.debug("Disabling recorder for device %d", device_id)
        try:
            await asyncio.wait_for(
                asyncio.to_thread(recorder.stop_stream),
                timeout=self.stop_timeout,
            )
        except Exception as exc:
            self.logger.debug("Device %d stop raised: %s", device_id, exc)

    async def begin_recording(
        self,
        device_ids: List[int],
        session_dir: Path,
        trial_number: int,
    ) -> int:
        started = 0
        for device_id in device_ids:
            recorder = self.recorders.get(device_id)
            if not recorder:
                continue
            try:
                self.logger.debug(
                    "Starting recording thread for device %d (trial %d)",
                    device_id,
                    trial_number,
                )
                await asyncio.to_thread(recorder.begin_recording, session_dir, trial_number)
                started += 1
            except Exception as exc:
                self.logger.error("Failed to prepare recorder %d: %s", device_id, exc)
        return started

    async def finish_recording(self) -> List[Path]:
        tasks = []
        for recorder in self.recorders.values():
            tasks.append(asyncio.to_thread(recorder.finish_recording))
        if not tasks:
            return []
        finished = await asyncio.gather(*tasks, return_exceptions=True)
        results: List[Path] = []
        for maybe_path in finished:
            if isinstance(maybe_path, Exception) or maybe_path is None:
                continue
            results.append(maybe_path)
        self.logger.debug("Finished %d recording file(s)", len(results))
        return results

    async def stop_all(self) -> None:
        device_ids = list(self.recorders.keys())
        if device_ids:
            self.logger.info("Stopping %d recorder(s)", len(device_ids))
        tasks = [self.disable_device(device_id) for device_id in device_ids]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.recorders.clear()

    @property
    def any_recording_active(self) -> bool:
        return any(recorder.recording for recorder in self.recorders.values())
