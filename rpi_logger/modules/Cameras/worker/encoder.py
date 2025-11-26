"""
Video encoder for the worker process.

Supports PyAV (preferred) with OpenCV fallback.
Handles overlay rendering and CSV timing logs.
"""
from __future__ import annotations

import csv
import os
import time
from fractions import Fraction
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np

try:
    import av
    _HAS_PYAV = True
except Exception:
    av = None
    _HAS_PYAV = False


class Encoder:
    """Video encoder with optional overlay and timing CSV."""

    def __init__(
        self,
        video_path: str,
        resolution: tuple[int, int],
        fps: float,
        *,
        overlay_enabled: bool = True,
        csv_path: Optional[str] = None,
        trial_number: Optional[int] = None,
        use_pyav: Optional[bool] = None,
    ) -> None:
        self.video_path = video_path
        self.csv_path = csv_path
        self._resolution = resolution
        self._fps = fps
        self._overlay_enabled = overlay_enabled
        self._trial_number = trial_number
        self._use_pyav = use_pyav if use_pyav is not None else _HAS_PYAV

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

    @property
    def duration_sec(self) -> float:
        if self._start_time_ns is None:
            return 0.0
        return (time.monotonic_ns() - self._start_time_ns) / 1_000_000_000

    def start(self) -> None:
        """Initialize encoder (blocking, call from thread)."""
        self._start_time_ns = time.monotonic_ns()

        if self._use_pyav and _HAS_PYAV:
            self._start_pyav()
        else:
            self._start_opencv()

        if self.csv_path:
            self._start_csv()

    def _start_pyav(self) -> None:
        import logging
        log = logging.getLogger(__name__)

        self._container = av.open(self.video_path, "w")
        fps_fraction = Fraction(self._fps).limit_denominator(1000)

        # Use mjpeg codec - works best with .avi and .mkv containers
        self._stream = self._container.add_stream("mjpeg", rate=fps_fraction)
        self._stream.width = self._resolution[0]
        self._stream.height = self._resolution[1]
        self._stream.pix_fmt = "yuvj420p"

        # Let PyAV manage time_base automatically - don't override it
        # The stream inherits time_base from the framerate (1/fps)

        log.info("PyAV encoder: %s %dx%d @ %s fps",
                self.video_path, self._resolution[0], self._resolution[1], fps_fraction)
        self._kind = "pyav"

    def _start_opencv(self) -> None:
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
            "frame_number",
            "write_time_unix",
            "monotonic_time",
            "sensor_timestamp_ns",
            "pts_us",
        ])

    def write_frame(
        self,
        frame: np.ndarray,
        *,
        timestamp: float,
        pts_time_ns: Optional[int] = None,
        color_format: str = "bgr",
    ) -> None:
        """Encode a single frame (blocking)."""
        self._frame_count += 1

        # Apply overlay if enabled
        if self._overlay_enabled:
            frame = self._apply_overlay(frame, timestamp, self._frame_count)

        if self._kind == "pyav":
            self._encode_pyav(frame, pts_time_ns, timestamp)
        else:
            self._encode_opencv(frame)

        # CSV logging
        if self._csv_writer:
            monotonic = time.monotonic()
            pts_us = self._last_pts if self._kind == "pyav" else None
            self._csv_writer.writerow([
                self._trial_number,
                self._frame_count,
                f"{timestamp:.6f}",
                f"{monotonic:.9f}",
                pts_time_ns,
                pts_us,
            ])

    def _encode_pyav(self, frame: np.ndarray, pts_time_ns: Optional[int], timestamp: float) -> None:
        try:
            av_frame = av.VideoFrame.from_ndarray(frame, format="bgr24")
        except Exception:
            return

        # Use simple frame index for PTS (time_base is 1/fps from stream rate)
        # This ensures consistent playback timing at the specified fps
        pts = self._frame_count  # Already incremented in write_frame()
        self._last_pts = pts

        av_frame.pts = pts

        packets = self._stream.encode(av_frame)
        for pkt in packets:
            self._container.mux(pkt)

        self._frames_since_flush += 1
        if self._frames_since_flush >= self._flush_interval:
            self._frames_since_flush = 0
            self._flush_pyav()

    def _encode_opencv(self, frame: np.ndarray) -> None:
        self._writer.write(frame)
        self._frames_since_flush += 1
        if self._frames_since_flush >= self._flush_interval:
            self._frames_since_flush = 0
            self._fsync()

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
        # Format timestamp
        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        text = f"{dt.strftime('%Y-%m-%dT%H:%M:%S')}.{int((timestamp % 1) * 1000):03d} #{frame_number}"

        # Draw text on frame
        frame = frame.copy()  # Don't modify original
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
        """Finalize and close encoder (blocking)."""
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
