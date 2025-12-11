import asyncio
import contextlib
import time
from dataclasses import dataclass
from typing import Optional, Any, List, Callable

import numpy as np
from rpi_logger.core.logging_utils import get_module_logger
from pupil_labs.realtime_api import (
    receive_video_frames,
    receive_gaze_data,
    receive_imu_data,
    receive_eye_events_data,
    receive_audio_frames,
)
from .rolling_fps import RollingFPS

logger = get_module_logger(__name__)


@dataclass(slots=True)
class FramePacket:

    image: np.ndarray
    received_monotonic: float
    timestamp_unix_seconds: Optional[float]
    camera_frame_index: int
    wait_ms: float = 0.0  # Time spent waiting for frame


@dataclass(slots=True)
class EyesFramePacket:
    """Packet for eyes camera frames (384x192 combined left+right)."""

    image: np.ndarray
    received_monotonic: float
    timestamp_unix_seconds: Optional[float]
    timestamp_unix_ns: Optional[int]
    frame_index: int


class StreamHandler:

    def __init__(self):
        self.running = False
        self.last_frame: Optional[np.ndarray] = None
        self._last_frame_packet: Optional[FramePacket] = None
        self.last_gaze: Optional[Any] = None
        self.last_imu: Optional[Any] = None
        self.last_event: Optional[Any] = None
        self.last_audio: Optional[Any] = None
        self.last_eyes_frame: Optional[np.ndarray] = None

        self.imu_listener: Optional[Callable[[Any], None]] = None
        self.event_listener: Optional[Callable[[Any], None]] = None
        self.camera_frames = 0
        self._eyes_frames = 0
        self.tasks: List[asyncio.Task] = []
        self._video_task_active = False
        self._gaze_task_active = False
        self._imu_task_active = False
        self._event_task_active = False
        self._audio_task_active = False
        self._eyes_task_active = False
        self.camera_fps_tracker = RollingFPS(window_seconds=5.0)
        self._dropped_frames = 0
        self._total_wait_ms = 0.0
        self._frame_queue: asyncio.Queue[FramePacket] = asyncio.Queue(maxsize=6)
        self._gaze_queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=32)
        self._imu_queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=64)
        self._event_queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=64)
        self._audio_queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=128)
        self._eyes_queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=64)

        # Event-driven coordination (Phase 1.1 optimization)
        self._frame_ready_event = asyncio.Event()
        self._gaze_ready_event = asyncio.Event()
        self._imu_ready_event = asyncio.Event()
        self._event_ready_event = asyncio.Event()
        self._audio_ready_event = asyncio.Event()
        self._eyes_ready_event = asyncio.Event()

    def _update_running_flag(self) -> None:
        self.running = any(
            (
                self._video_task_active,
                self._gaze_task_active,
                self._imu_task_active,
                self._event_task_active,
                self._audio_task_active,
                self._eyes_task_active,
            )
        )

    async def start_streaming(
        self,
        video_url: str,
        gaze_url: str,
        *,
        imu_url: Optional[str] = None,
        events_url: Optional[str] = None,
        audio_url: Optional[str] = None,
        eyes_url: Optional[str] = None,
    ):
        if self.running:
            return

        self._video_task_active = True
        self._gaze_task_active = True
        self._imu_task_active = bool(imu_url)
        self._event_task_active = bool(events_url)
        self._audio_task_active = bool(audio_url)
        self._eyes_task_active = bool(eyes_url)
        self._update_running_flag()

        self.tasks = [
            asyncio.create_task(self._stream_video_frames(video_url), name="video-stream"),
            asyncio.create_task(self._stream_gaze_data(gaze_url), name="gaze-stream"),
        ]

        if imu_url:
            self.tasks.append(
                asyncio.create_task(self._stream_imu_data(imu_url), name="imu-stream")
            )
        if events_url:
            self.tasks.append(
                asyncio.create_task(self._stream_eye_events(events_url), name="events-stream")
            )
        if audio_url:
            self.tasks.append(
                asyncio.create_task(self._stream_audio_data(audio_url), name="audio-stream")
            )
        if eyes_url:
            self.tasks.append(
                asyncio.create_task(self._stream_eyes_frames(eyes_url), name="eyes-stream")
            )

        return self.tasks

    async def stop_streaming(self):
        self._video_task_active = False
        self._gaze_task_active = False
        self._imu_task_active = False
        self._event_task_active = False
        self._audio_task_active = False
        self._eyes_task_active = False
        self._update_running_flag()

        for task in self.tasks:
            if not task.done():
                task.cancel()

        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks = []
        self._drain_queues()

    async def _stream_video_frames(self, video_url: str):
        frame_count = 0
        try:
            async for frame in receive_video_frames(video_url):
                if not self.running:
                    break

                frame_count += 1

                if frame:
                    try:
                        pixel_data = frame.bgr_buffer()

                        if pixel_data is not None:
                            # Conditional array copy - avoid copy if already contiguous
                            if pixel_data.flags['C_CONTIGUOUS']:
                                frame_array = pixel_data
                            else:
                                frame_array = np.ascontiguousarray(pixel_data)
                            self.camera_frames += 1
                            self.last_frame = frame_array
                            packet = FramePacket(
                                image=frame_array,
                                received_monotonic=time.perf_counter(),
                                timestamp_unix_seconds=getattr(frame, "timestamp_unix_seconds", None),
                                camera_frame_index=self.camera_frames,
                            )
                            self._last_frame_packet = packet
                            self.camera_fps_tracker.add_frame()
                            self._enqueue_latest(self._frame_queue, packet, track_drops=True)
                            self._frame_ready_event.set()  # Signal frame available

                    except Exception as e:
                        if frame_count == 1:
                            logger.error("Video stream frame error: %s", e)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            if self.running:
                logger.error("Video stream error: %s", e)
        finally:
            self._video_task_active = False
            self._update_running_flag()

    async def _stream_gaze_data(self, gaze_url: str):
        try:
            async for gaze in receive_gaze_data(gaze_url):
                if not self.running:
                    break

                self.last_gaze = gaze
                self._enqueue_latest(self._gaze_queue, gaze)
                self._gaze_ready_event.set()  # Signal gaze available

        except asyncio.CancelledError:
            raise
        except Exception as e:
            if self.running:
                logger.error("Gaze stream error: %s", e)
        finally:
            self._gaze_task_active = False
            self._update_running_flag()

    async def _stream_imu_data(self, imu_url: str):
        try:
            async for imu in receive_imu_data(imu_url):
                if not self.running:
                    break

                self.last_imu = imu
                self._enqueue_latest(self._imu_queue, imu)
                self._imu_ready_event.set()  # Signal IMU available

                listener = self.imu_listener
                if listener is not None:
                    try:
                        listener(imu)
                    except Exception as exc:
                        logger.error("IMU listener error: %s", exc)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self.running:
                logger.error("IMU stream error: %s", exc)
        finally:
            self._imu_task_active = False
            self._update_running_flag()

    async def _stream_eye_events(self, events_url: str):
        try:
            async for event in receive_eye_events_data(events_url):
                if not self.running:
                    break

                self.last_event = event
                self._enqueue_latest(self._event_queue, event)
                self._event_ready_event.set()  # Signal event available

                listener = self.event_listener
                if listener is not None:
                    try:
                        listener(event)
                    except Exception as exc:
                        logger.error("Eye event listener error: %s", exc)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self.running:
                logger.error("Eye events stream error: %s", exc)
        finally:
            self._event_task_active = False
            self._update_running_flag()

    async def _stream_audio_data(self, audio_url: str):
        try:
            async for audio in receive_audio_frames(audio_url):
                if not self.running:
                    break

                self.last_audio = audio
                self._enqueue_latest(self._audio_queue, audio)
                self._audio_ready_event.set()

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self.running:
                logger.error("Audio stream error: %s", exc)
        finally:
            self._audio_task_active = False
            self._update_running_flag()

    async def _stream_eyes_frames(self, eyes_url: str):
        """Stream eye camera frames (384x192 combined left+right at 200Hz)."""
        frame_count = 0
        try:
            async for frame in receive_video_frames(eyes_url):
                if not self.running:
                    break

                frame_count += 1

                if frame:
                    try:
                        pixel_data = frame.bgr_buffer()

                        if pixel_data is not None:
                            if pixel_data.flags['C_CONTIGUOUS']:
                                frame_array = pixel_data
                            else:
                                frame_array = np.ascontiguousarray(pixel_data)
                            self._eyes_frames += 1
                            self.last_eyes_frame = frame_array

                            # Create packet for recording
                            packet = EyesFramePacket(
                                image=frame_array,
                                received_monotonic=time.perf_counter(),
                                timestamp_unix_seconds=getattr(frame, "timestamp_unix_seconds", None),
                                timestamp_unix_ns=getattr(frame, "timestamp_unix_ns", None),
                                frame_index=self._eyes_frames,
                            )
                            self._enqueue_latest(self._eyes_queue, packet)
                            self._eyes_ready_event.set()

                    except Exception as e:
                        if frame_count == 1:
                            logger.error("Eyes stream frame error: %s", e)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            if self.running:
                logger.error("Eyes stream error: %s", e)
        finally:
            self._eyes_task_active = False
            self._update_running_flag()

    def get_latest_frame(self) -> Optional[np.ndarray]:
        return self.last_frame

    def get_latest_frame_packet(self) -> Optional[FramePacket]:
        return self._last_frame_packet

    def get_latest_gaze(self) -> Optional[Any]:
        return self.last_gaze

    def get_latest_imu(self) -> Optional[Any]:
        return self.last_imu

    def get_latest_event(self) -> Optional[Any]:
        return self.last_event

    def set_imu_listener(self, listener: Optional[Callable[[Any], None]]) -> None:
        self.imu_listener = listener

    def set_event_listener(self, listener: Optional[Callable[[Any], None]]) -> None:
        self.event_listener = listener

    def get_latest_audio(self) -> Optional[Any]:
        return self.last_audio

    def get_latest_eyes_frame(self) -> Optional[np.ndarray]:
        return self.last_eyes_frame

    def get_camera_fps(self) -> float:
        return self.camera_fps_tracker.get_fps()

    @property
    def dropped_frames(self) -> int:
        return self._dropped_frames

    @property
    def avg_wait_ms(self) -> float:
        if self.camera_frames == 0:
            return 0.0
        return self._total_wait_ms / self.camera_frames

    async def next_frame(self, timeout: Optional[float] = None) -> Optional[FramePacket]:
        return await self._dequeue_with_timeout(self._frame_queue, timeout)

    async def next_gaze(self, timeout: Optional[float] = None) -> Optional[Any]:
        return await self._dequeue_with_timeout(self._gaze_queue, timeout)

    async def next_imu(self, timeout: Optional[float] = None) -> Optional[Any]:
        return await self._dequeue_with_timeout(self._imu_queue, timeout)

    async def next_event(self, timeout: Optional[float] = None) -> Optional[Any]:
        return await self._dequeue_with_timeout(self._event_queue, timeout)

    async def next_audio(self, timeout: Optional[float] = None) -> Optional[Any]:
        return await self._dequeue_with_timeout(self._audio_queue, timeout)

    async def next_eyes(self, timeout: Optional[float] = None) -> Optional[EyesFramePacket]:
        return await self._dequeue_with_timeout(self._eyes_queue, timeout)

    # Event-driven methods (Phase 1.1 optimization)
    async def wait_for_frame(self, timeout: Optional[float] = None) -> Optional[FramePacket]:
        """Wait for frame to be available, then retrieve it (event-driven)"""
        wait_start = time.perf_counter()
        try:
            await asyncio.wait_for(self._frame_ready_event.wait(), timeout=timeout)
            self._frame_ready_event.clear()
            packet = self._last_frame_packet
            if packet is not None:
                wait_ms = (time.perf_counter() - wait_start) * 1000
                self._total_wait_ms += wait_ms
                # Return packet with wait_ms populated
                return FramePacket(
                    image=packet.image,
                    received_monotonic=packet.received_monotonic,
                    timestamp_unix_seconds=packet.timestamp_unix_seconds,
                    camera_frame_index=packet.camera_frame_index,
                    wait_ms=wait_ms,
                )
            return None
        except asyncio.TimeoutError:
            return None

    async def wait_for_gaze(self, timeout: Optional[float] = None) -> Optional[Any]:
        """Wait for gaze data to be available (event-driven)"""
        try:
            await asyncio.wait_for(self._gaze_ready_event.wait(), timeout=timeout)
            self._gaze_ready_event.clear()
            return await self.next_gaze(timeout=0)
        except asyncio.TimeoutError:
            return None

    async def wait_for_audio(self, timeout: Optional[float] = None) -> Optional[Any]:
        """Wait for audio frame availability (event-driven)"""
        try:
            await asyncio.wait_for(self._audio_ready_event.wait(), timeout=timeout)
            self._audio_ready_event.clear()
            return await self.next_audio(timeout=0)
        except asyncio.TimeoutError:
            return None

    def _enqueue_latest(self, queue: asyncio.Queue, item: Any, *, track_drops: bool = False) -> None:
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty):
                _ = queue.get_nowait()
            if track_drops:
                self._dropped_frames += 1
            queue.put_nowait(item)

    @staticmethod
    async def _dequeue_with_timeout(queue: asyncio.Queue, timeout: Optional[float]) -> Optional[Any]:
        try:
            if timeout == 0:
                # Use get_nowait for immediate non-blocking dequeue
                return queue.get_nowait()
            elif timeout is None:
                return await queue.get()
            else:
                return await asyncio.wait_for(queue.get(), timeout=timeout)
        except asyncio.QueueEmpty:
            return None
        except asyncio.TimeoutError:
            return None

    def _drain_queues(self) -> None:
        for queue in (
            self._frame_queue,
            self._gaze_queue,
            self._imu_queue,
            self._event_queue,
            self._audio_queue,
            self._eyes_queue,
        ):
            while True:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
