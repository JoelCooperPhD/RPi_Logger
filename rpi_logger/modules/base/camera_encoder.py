"""
Video encoder for camera modules.

Supports PyAV (preferred) with OpenCV fallback.
Handles overlay rendering and CSV timing logs.

Uses a long-lived worker thread with bounded queue for backpressure.
This encoder is backend-agnostic and works with both USB and CSI cameras.
"""
from __future__ import annotations

import csv
import os
import queue
import threading
import time
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Optional

import numpy as np

from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger(__name__)

try:
    import cv2
    _HAS_CV2 = True
except ImportError:
    cv2 = None
    _HAS_CV2 = False

try:
    import av
    _HAS_PYAV = True
except Exception:
    av = None
    _HAS_PYAV = False


# Default queue size - provides ~1 second of buffering at 30fps
_DEFAULT_QUEUE_SIZE = 30


@dataclass(slots=True)
class _FrameItem:
    """Frame data queued for encoding."""
    data: np.ndarray
    timestamp: float
    pts_time_ns: Optional[int]
    color_format: str


class _EncodeWorker:
    """Long-lived encoding thread with bounded queue.

    Processes frames from a queue in a dedicated thread, providing
    clean backpressure when encoding can't keep up with capture.
    """

    def __init__(
        self,
        encoder: "Encoder",
        queue_size: int = _DEFAULT_QUEUE_SIZE,
    ) -> None:
        self._encoder = encoder
        self._queue: queue.Queue[Optional[_FrameItem]] = queue.Queue(maxsize=queue_size)
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._error: Optional[Exception] = None
        self._frames_dropped = 0
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start the worker thread."""
        if self._thread is not None:
            return
        self._running = True
        self._error = None
        self._frames_dropped = 0
        self._thread = threading.Thread(
            target=self._run,
            name=f"encode-worker-{id(self)}",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the worker thread and wait for completion."""
        if not self._thread:
            return

        self._running = False
        # Signal shutdown with None sentinel
        try:
            self._queue.put(None, block=False)
        except queue.Full:
            # Queue is full, drain one item to make room for sentinel
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put(None, block=False)
            except queue.Full:
                pass

        self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            # Thread didn't stop in time - it's a daemon so it'll be killed on exit
            pass
        self._thread = None

    def submit(self, frame: np.ndarray, timestamp: float, pts_time_ns: Optional[int], color_format: str) -> bool:
        """Submit a frame for encoding.

        Returns True if frame was queued, False if queue is full (backpressure).
        Non-blocking - returns immediately.
        """
        if not self._running or self._error:
            return False

        item = _FrameItem(
            data=frame,
            timestamp=timestamp,
            pts_time_ns=pts_time_ns,
            color_format=color_format,
        )

        try:
            self._queue.put_nowait(item)
            return True
        except queue.Full:
            with self._lock:
                self._frames_dropped += 1
            return False

    @property
    def frames_dropped(self) -> int:
        """Number of frames dropped due to backpressure."""
        with self._lock:
            return self._frames_dropped

    @property
    def queue_depth(self) -> int:
        """Current number of frames waiting to be encoded."""
        return self._queue.qsize()

    @property
    def error(self) -> Optional[Exception]:
        """Error from worker thread, if any."""
        return self._error

    def _run(self) -> None:
        """Worker thread main loop."""
        while self._running:
            try:
                item = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if item is None:
                # Shutdown sentinel
                break

            try:
                self._encoder._write_frame_internal(
                    item.data,
                    timestamp=item.timestamp,
                    pts_time_ns=item.pts_time_ns,
                    color_format=item.color_format,
                )
            except Exception as e:
                self._error = e
                # Continue processing to drain queue on error

        # Drain remaining frames on shutdown
        while True:
            try:
                item = self._queue.get_nowait()
                if item is None:
                    continue
                try:
                    self._encoder._write_frame_internal(
                        item.data,
                        timestamp=item.timestamp,
                        pts_time_ns=item.pts_time_ns,
                        color_format=item.color_format,
                    )
                except Exception:
                    pass  # Best effort on drain
            except queue.Empty:
                break


class Encoder:
    """Video encoder with optional overlay and timing CSV.

    Uses a dedicated worker thread with bounded queue for backpressure.
    Frames are submitted via write_frame() and encoded asynchronously.

    This encoder is backend-agnostic and works with both USB and CSI cameras.
    """

    def __init__(
        self,
        video_path: str,
        resolution: tuple[int, int],
        fps: float,
        *,
        overlay_enabled: bool = True,
        csv_path: Optional[str] = None,
        trial_number: Optional[int] = None,
        device_id: Optional[str] = None,
        module_name: str = "Cameras",
        use_pyav: Optional[bool] = None,
        queue_size: Optional[int] = None,
    ) -> None:
        self.video_path = video_path
        self.csv_path = csv_path
        self._resolution = resolution
        self._fps = fps
        self._overlay_enabled = overlay_enabled
        self._trial_number = trial_number
        self._device_id = device_id or ""
        self._module_name = module_name
        self._use_pyav = use_pyav if use_pyav is not None else _HAS_PYAV
        self._queue_size = queue_size if queue_size is not None else _DEFAULT_QUEUE_SIZE

        # Encoder state
        self._container: Any = None
        self._stream: Any = None
        self._writer: Any = None
        self._kind: str = ""

        # PTS tracking
        self._base_pts_ns: Optional[int] = None
        self._last_pts: int = 0
        self._start_time_ns: Optional[int] = None
        self._frame_count: int = 0

        # Periodic flush
        self._flush_interval = 600
        self._frames_since_flush = 0

        # CSV logger
        self._csv_file = None
        self._csv_writer = None

        # Worker thread
        self._worker: Optional[_EncodeWorker] = None

    @property
    def duration_sec(self) -> float:
        if self._start_time_ns is None:
            return 0.0
        return (time.monotonic_ns() - self._start_time_ns) / 1_000_000_000

    @property
    def frame_count(self) -> int:
        """Number of frames successfully written to video (matches CSV row count)."""
        return self._frame_count

    @property
    def frames_dropped(self) -> int:
        """Number of frames dropped due to backpressure."""
        if self._worker:
            return self._worker.frames_dropped
        return 0

    @property
    def queue_depth(self) -> int:
        """Current number of frames waiting to be encoded."""
        if self._worker:
            return self._worker.queue_depth
        return 0

    def start(self) -> None:
        """Initialize encoder and start worker thread."""
        self._start_time_ns = time.monotonic_ns()

        if self._use_pyav and _HAS_PYAV:
            self._start_pyav()
        else:
            self._start_opencv()

        if self.csv_path:
            self._start_csv()

        # Start worker thread
        self._worker = _EncodeWorker(self, queue_size=self._queue_size)
        self._worker.start()

    def _start_pyav(self) -> None:
        self._container = av.open(self.video_path, "w")
        fps_fraction = Fraction(self._fps).limit_denominator(1000)

        # Use mjpeg codec - works best with .avi and .mkv containers
        self._stream = self._container.add_stream("mjpeg", rate=fps_fraction)
        self._stream.width = self._resolution[0]
        self._stream.height = self._resolution[1]
        self._stream.pix_fmt = "yuvj420p"

        # Let PyAV manage time_base automatically - don't override it
        # The stream inherits time_base from the framerate (1/fps)

        logger.info("PyAV encoder: %s %dx%d @ %s fps",
                self.video_path, self._resolution[0], self._resolution[1], fps_fraction)
        self._kind = "pyav"

    def _start_opencv(self) -> None:
        if not _HAS_CV2:
            raise RuntimeError("OpenCV not available for video encoding")
        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        self._writer = cv2.VideoWriter(
            self.video_path,
            fourcc,
            self._fps,
            self._resolution,
        )
        self._kind = "opencv"

    def _start_csv(self) -> None:
        self._csv_file = open(self.csv_path, "w", newline="")
        self._csv_writer = csv.writer(self._csv_file)
        self._csv_writer.writerow([
            "trial",
            "module",
            "device_id",
            "label",
            "record_time_unix",  # wall clock time when frame was captured
            "record_time_mono",  # monotonic time when frame was encoded
            "frame_index",  # 1-indexed frame number in video file
            "sensor_timestamp_ns",  # hardware sensor timestamp (if available)
            "video_pts",  # presentation timestamp in video stream
        ])

    def write_frame(
        self,
        frame: np.ndarray,
        *,
        timestamp: float,
        pts_time_ns: Optional[int] = None,
        color_format: str = "bgr",
    ) -> bool:
        """Submit a frame for encoding (non-blocking).

        Returns True if frame was queued, False if queue is full (backpressure).
        The actual encoding happens asynchronously in the worker thread.
        """
        if not self._worker:
            return False
        return self._worker.submit(frame, timestamp, pts_time_ns, color_format)

    def _write_frame_internal(
        self,
        frame: np.ndarray,
        *,
        timestamp: float,
        pts_time_ns: Optional[int] = None,
        color_format: str = "bgr",
    ) -> bool:
        """Encode a single frame (blocking, called by worker thread).

        Returns True if frame was successfully encoded, False otherwise.
        CSV timing is only written for successfully encoded frames.
        """
        # Tentatively increment frame count (will be used for PTS)
        next_frame_num = self._frame_count + 1

        # Apply overlay if enabled
        if self._overlay_enabled:
            frame = self._apply_overlay(frame, timestamp, next_frame_num)

        # Encode the frame - returns True only if actually written to video
        if self._kind == "pyav":
            success = self._encode_pyav(frame, pts_time_ns, timestamp, next_frame_num)
        else:
            success = self._encode_opencv(frame)

        if not success:
            return False

        # Frame was successfully encoded - commit the frame count
        self._frame_count = next_frame_num

        # CSV logging - only for successfully encoded frames
        if self._csv_writer:
            monotonic = time.perf_counter()
            pts_us = self._last_pts if self._kind == "pyav" else None
            self._csv_writer.writerow([
                self._trial_number,
                self._module_name,
                self._device_id,
                "",
                f"{timestamp:.6f}",
                f"{monotonic:.9f}",
                self._frame_count,
                pts_time_ns,
                pts_us,
            ])

        return True

    def _encode_pyav(self, frame: np.ndarray, pts_time_ns: Optional[int], timestamp: float, frame_num: int) -> bool:
        """Encode frame with PyAV. Returns True if frame was successfully muxed."""
        try:
            av_frame = av.VideoFrame.from_ndarray(frame, format="bgr24")
        except Exception:
            return False

        # Use frame index for PTS (time_base is 1/fps from stream rate)
        # This ensures consistent playback timing at the specified fps
        pts = frame_num
        self._last_pts = pts
        av_frame.pts = pts

        try:
            packets = self._stream.encode(av_frame)
            for pkt in packets:
                self._container.mux(pkt)
        except Exception:
            return False

        self._frames_since_flush += 1
        if self._frames_since_flush >= self._flush_interval:
            self._frames_since_flush = 0
            self._flush_pyav()

        return True

    def _encode_opencv(self, frame: np.ndarray) -> bool:
        """Encode frame with OpenCV. Returns True if frame was successfully written."""
        if not self._writer or not self._writer.isOpened():
            return False

        try:
            self._writer.write(frame)
        except Exception:
            return False

        self._frames_since_flush += 1
        if self._frames_since_flush >= self._flush_interval:
            self._frames_since_flush = 0
            self._fsync()

        return True

    def _flush_pyav(self) -> None:
        try:
            flush_fn = getattr(self._container, "flush", None)
            if callable(flush_fn):
                flush_fn()
        except Exception:
            pass
        self._fsync()

    def _fsync(self) -> None:
        try:
            fd = os.open(self.video_path, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except Exception:
            pass

    def _apply_overlay(self, frame: np.ndarray, timestamp: float, frame_number: int) -> np.ndarray:
        if not _HAS_CV2:
            return frame

        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        text = f"{dt.strftime('%Y-%m-%dT%H:%M:%S')}.{int((timestamp % 1) * 1000):03d} #{frame_number}"

        frame = frame.copy()
        cv2.putText(
            frame,
            text,
            (8, 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        return frame

    def stop(self) -> None:
        """Finalize and close encoder (blocking).

        Stops the worker thread first, draining any queued frames,
        then finalizes the video container.
        """
        # Stop worker thread first - this drains queued frames
        if self._worker:
            self._worker.stop()
            self._worker = None

        if self._kind == "pyav":
            self._finalize_pyav()
        else:
            self._finalize_opencv()

        if self._csv_file:
            try:
                self._csv_file.close()
            except Exception:
                pass
            self._csv_file = None
            self._csv_writer = None

    def _finalize_pyav(self) -> None:
        if not self._container:
            return
        try:
            packets = self._stream.encode(None)
            for pkt in packets:
                self._container.mux(pkt)
        except Exception:
            pass
        try:
            self._container.close()
        except Exception:
            pass
        self._container = None
        self._stream = None

    def _finalize_opencv(self) -> None:
        if self._writer:
            try:
                self._writer.release()
            except Exception:
                pass
            self._writer = None


__all__ = ["Encoder"]
