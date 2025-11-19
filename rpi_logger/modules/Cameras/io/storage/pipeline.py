"""Shared storage pipeline for Cameras compatible modules."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, Union

import cv2
import numpy as np


try:
    from picamera2.request import MappedArray
except Exception:  # pragma: no cover - allows dev environments without Picamera2
    MappedArray = None  # type: ignore[arg-type]

from .csv_logger import CameraCSVLogger
from .fps_tracker import VideoFpsTracker
from ...domain.model import FramePayload
from rpi_logger.core.logging_utils import get_module_logger, ensure_structured_logger


@dataclass(slots=True)
class StorageWriteResult:
    """Outcome of a storage pipeline write operation."""

    video_written: bool
    image_path: Optional[Path]
    video_fps: float
    writer_codec: Optional[str]


@dataclass(slots=True)
class OverlayRenderInfo:
    """Metadata rendered into video/still overlays and the hardware encoder overlay."""

    frame_number: int
    timestamp_unix: float
    sensor_timestamp_ns: Optional[int]

    @property
    def timestamp_text(self) -> str:
        dt = datetime.fromtimestamp(self.timestamp_unix)
        return dt.strftime("%H:%M:%S.%f")[:-3]

    @property
    def sensor_text(self) -> Optional[str]:
        if self.sensor_timestamp_ns is None:
            return None
        microseconds = self.sensor_timestamp_ns // 1_000
        return f"{microseconds}"


class CameraStoragePipeline:
    """Encapsulates CSV logging, video writing, and image saving for a camera."""

    def __init__(
        self,
        camera_index: int,
        save_dir: Path,
        *,
        camera_alias: Optional[str] = None,
        camera_slug: Optional[str] = None,
        main_size: Optional[tuple[int, int]] = None,
        camera: Optional[Any] = None,
        save_format: str = "jpeg",
        save_quality: int = 90,
        max_fps: float = 60.0,
        overlay_config: Optional[dict] = None,

        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.camera_index = camera_index
        self.save_dir = save_dir
        self.camera = camera
        self.camera_alias = camera_alias or f"Camera {camera_index + 1}"
        self.camera_slug = self._coerce_slug(camera_slug, f"cam{camera_index}")
        self.main_size = main_size
        self.save_format = save_format
        self.save_quality = save_quality
        self.max_fps = max_fps
        self.overlay_config = overlay_config or {}

        component = f"StoragePipeline.cam{camera_index}"
        self._logger = ensure_structured_logger(
            logger,
            component=component,
            fallback_name=f"{__name__}.{component}",
        )
        self.uses_hardware_encoder = camera is not None

        self._csv_logger: Optional[CameraCSVLogger] = None
        self._csv_path: Optional[Path] = None

        self._video_writer: Optional[cv2.VideoWriter] = None
        self._picamera_encoder: Optional[object] = None
        self._picamera_output: Optional[object] = None
        self._overlay_previous_callback: Optional[Callable] = None
        self._overlay_callback = None
        self._overlay_frame_counter = 0
        self._video_path: Optional[Path] = None
        self._writer_codec: Optional[str] = None
        self._writer_fps: float = 30.0
        self._video_fps_hint: Optional[float] = None
        self._pending_video_frames: list[tuple[OverlayRenderInfo, np.ndarray]] = []
        self._pending_frame_limit = 120
        self._pending_fps_warning_logged = False
        self._overlay_metadata: deque[OverlayRenderInfo] = deque()
        self._overlay_metadata_limit = self._pending_frame_limit * 4
        self._overlay_lock = threading.Lock()
        self._fps_tracker = VideoFpsTracker()
        self.trial_number: int = 1
        self.trial_label: str = ""
        self._sensor_last_timestamp_ns: Optional[int] = None
        self._sensor_fps_estimate: Optional[float] = None
        self._sensor_smoothing = 0.2
        self._sensor_timestamp_failures = 0
        self._sensor_timestamp_failure_limit = 15
        self._waiting_for_sensor_fps = True

        self._codec_candidates = ("mp4v", "avc1", "H264", "XVID")
        self._fourcc = cv2.VideoWriter_fourcc(*"mp4v")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @property
    def csv_path(self) -> Optional[Path]:
        return self._csv_path

    @property
    def video_path(self) -> Optional[Path]:
        return self._video_path

    @property
    def video_frame_count(self) -> int:
        return self._fps_tracker.frame_count

    async def start(self) -> None:
        """Prepare CSV logger and reset video writer state."""
        await asyncio.to_thread(self.save_dir.mkdir, parents=True, exist_ok=True)
        self._sensor_last_timestamp_ns = None
        self._sensor_fps_estimate = None
        self._sensor_timestamp_failures = 0
        self._fps_tracker.reset()
        self._waiting_for_sensor_fps = True
        slug = self.camera_slug or f"cam{self.camera_index}"
        suffix = self._trial_suffix
        self._video_path = self.save_dir / f"{slug}{suffix}_recording.mp4"
        self._csv_path = self.save_dir / f"{slug}{suffix}_frame_timing.csv"
        csv_logger = CameraCSVLogger(self.camera_index, self._csv_path, trial_number=self.trial_number)
        await csv_logger.start()
        self._csv_logger = csv_logger
        self._logger.info(
            "Storage targets prepared -> video: %s | csv: %s",
            self._video_path,
            self._csv_path,
        )

    async def stop(self) -> None:
        """Flush and close storage resources."""
        await self.stop_video_recording()
        await self._release_video_writer()

        if self._csv_logger is not None:
            try:
                await self._csv_logger.stop()
            except Exception as exc:  # pragma: no cover - defensive
                self._logger.debug("CSV logger stop error: %s", exc)
            self._csv_logger = None
        self._csv_path = None

    async def write_frame(
        self,
        bgr_frame: Optional[np.ndarray],
        payload: "FramePayload",
        *,
        fps_hint: float,
    ) -> StorageWriteResult:
        """Persist a frame to disk and optionally to the video writer.
        
        Args:
            bgr_frame: BGR numpy array (OpenCV format) for video writing.
            payload: Metadata for the frame.
            fps_hint: Expected FPS for video writing.
        """
        sensor_fps = self._update_sensor_fps(payload)
        if sensor_fps is not None:
            fps_hint = sensor_fps
        elif self._waiting_for_sensor_fps:
            fps_hint = 0.0
        if fps_hint > 0:
            self._video_fps_hint = fps_hint

        overlay_info = self._build_overlay_info(payload)

        if self.uses_hardware_encoder and self._picamera_encoder is not None:
            image_path: Optional[Path] = None

            if not self._fps_tracker.hardware_tracking:
                self._fps_tracker.record_fallback_hardware_frame()
            return StorageWriteResult(
                video_written=True,
                image_path=None,
                video_fps=self.video_output_fps,
                writer_codec=self._writer_codec,
            )

        if bgr_frame is None:
            raise RuntimeError("BGR frame required for software encoding path")

        video_written = False
        writer_ready = self._video_writer is not None
        frame_size = (bgr_frame.shape[1], bgr_frame.shape[0])
        if not writer_ready:
            writer_ready = await self._try_prepare_video_writer(frame_size, fps_hint)
            if not writer_ready:
                self._queue_pending_frame(bgr_frame, overlay_info)

        if writer_ready and self._video_writer is not None:
            video_written = await self._write_video_frame(bgr_frame, overlay_info)



        return StorageWriteResult(
            video_written=video_written,
            image_path=image_path,
            video_fps=self.video_output_fps,
            writer_codec=self._writer_codec,
        )

    @property
    def video_output_fps(self) -> float:
        return self._fps_tracker.output_fps()

    def log_frame(self, payload: "FramePayload", *, queue_drops: int = 0) -> None:
        """Record frame metadata to CSV if logging is active."""
        if self._csv_logger is None:
            return

        self._csv_logger.log_frame(
            payload.capture_index,
            frame_time_unix=payload.timestamp,
            monotonic_time=payload.monotonic,
            sensor_timestamp_ns=payload.sensor_timestamp_ns,
            hardware_frame_number=payload.hardware_frame_number,
            dropped_since_last=payload.dropped_since_last,
            storage_queue_drops=queue_drops,
        )

    def record_overlay_metadata(
        self,
        *,
        frame_number: int,
        timestamp_unix: float,
        sensor_timestamp_ns: Optional[int],
    ) -> None:
        """Queue overlay metadata so hardware encoders can stay in sync with CSV IDs."""
        if not self.overlay_config.get("show_frame_number", True):
            return
        overlay = OverlayRenderInfo(
            frame_number=frame_number,
            timestamp_unix=timestamp_unix,
            sensor_timestamp_ns=sensor_timestamp_ns,
        )
        with self._overlay_lock:
            self._overlay_metadata.append(overlay)
            while len(self._overlay_metadata) > self._overlay_metadata_limit:
                self._overlay_metadata.popleft()

    def _build_overlay_info(self, payload: "FramePayload") -> OverlayRenderInfo:
        return OverlayRenderInfo(
            frame_number=payload.capture_index,
            timestamp_unix=payload.timestamp,
            sensor_timestamp_ns=payload.sensor_timestamp_ns,
        )

    def _next_overlay_metadata(self) -> Optional[OverlayRenderInfo]:
        with self._overlay_lock:
            if self._overlay_metadata:
                return self._overlay_metadata.popleft()
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    async def start_video_recording(self, fps_hint: Optional[float] = None) -> None:
        """Start Picamera2-based recording when a camera handle is available."""
        self._fps_tracker.reset()

        hardware_active = bool(self.uses_hardware_encoder and self.camera and self._video_path)
        if not hardware_active:
            self.uses_hardware_encoder = False
            self._video_fps_hint = None
            return
        if self._picamera_encoder is not None:
            return

        if fps_hint is not None and fps_hint > 0:
            self._video_fps_hint = self._normalize_fps(fps_hint)
        else:
            self._video_fps_hint = self.max_fps

        try:
            from picamera2.encoders import H264Encoder, Quality
            from picamera2.outputs import FfmpegOutput
        except Exception as exc:  # pragma: no cover - Picamera2 should be available on target
            self._logger.warning("Picamera2 encoder unavailable, falling back to software video writer: %s", exc)
            self.uses_hardware_encoder = False
            return

        if fps_hint is not None:
            self._video_fps_hint = fps_hint
        fps = self._normalize_fps(self._video_fps_hint or 0.0)

        from fractions import Fraction

        try:
            encoder = H264Encoder(framerate=Fraction(fps), enable_sps_framerate=True)
        except TypeError:
            encoder = H264Encoder(framerate=Fraction(fps))
            if hasattr(encoder, "_enable_framerate"):
                encoder._enable_framerate = True  # type: ignore[attr-defined]
        output = FfmpegOutput(str(self._video_path))

        try:
            await asyncio.to_thread(self.camera.start_recording, encoder, output, Quality.HIGH)
        except Exception as exc:
            self._logger.error("Failed to start Picamera2 recording, using software fallback: %s", exc)
            try:
                await asyncio.to_thread(output.close)  # type: ignore[attr-defined]
            except Exception:
                pass
            self.uses_hardware_encoder = False
            return

        self._picamera_encoder = encoder
        self._picamera_output = output
        self._writer_codec = "H264"
        self._install_overlay_callback()
        self._logger.info("Picamera2 recording started -> %s", self._video_path)

    async def stop_video_recording(self) -> None:
        if self._picamera_encoder is None or self.camera is None:
            return

        try:
            await asyncio.to_thread(self.camera.stop_recording)
        except Exception as exc:
            self._logger.warning("Error stopping Picamera2 recording: %s", exc)

        output = self._picamera_output
        if output is not None and hasattr(output, "close"):
            try:
                await asyncio.to_thread(output.close)
            except Exception:
                pass

        self._remove_overlay_callback()
        self._logger.info(
            "Picamera2 recording stopped -> %s (%d frames)",
            self._video_path,
            self._fps_tracker.frame_count,
        )
        self._picamera_encoder = None
        self._picamera_output = None
        self._fps_tracker.stop_hardware_tracking()

    async def _ensure_video_writer(self, frame_size: tuple[int, int], fps_hint: float) -> None:
        if self._video_writer is not None or self.uses_hardware_encoder:
            return

        width, height = frame_size
        fps = self._normalize_fps(fps_hint or (self._video_fps_hint or 0.0))
        slug = self.camera_slug or f"cam{self.camera_index}"
        video_path = self._video_path or (self.save_dir / f"{slug}_recording.mp4")
        last_error: Optional[str] = None

        def create_writer(codec: str) -> Optional[cv2.VideoWriter]:
            fourcc = cv2.VideoWriter_fourcc(*codec)
            writer = cv2.VideoWriter(str(video_path), fourcc, fps, (width, height))
            if not writer.isOpened():
                writer.release()
                return None
            return writer, fourcc

        for codec in self._codec_candidates:
            result = await asyncio.to_thread(create_writer, codec)
            if result is None:
                last_error = codec
                continue
            writer, fourcc = result
            self._video_writer = writer
            self._video_path = video_path
            self._writer_codec = codec
            self._writer_fps = fps
            self._fourcc = fourcc
            self._fps_tracker.reset()
            self._logger.info(
                "Video writer opened -> %s (fps=%.2f, size=%dx%d, codec=%s)",
                video_path,
                fps,
                width,
                height,
                codec,
            )
            return

        raise RuntimeError(
            f"Failed to open video writer for {video_path} (attempted codecs: {', '.join(self._codec_candidates)})"
        )

    async def _try_prepare_video_writer(self, frame_size: tuple[int, int], fps_hint: float) -> bool:
        if self._video_writer is not None or self.uses_hardware_encoder:
            return True
        fps = fps_hint if fps_hint > 0 else (self._video_fps_hint or 0.0)
        if fps <= 0:
            return False
        await self._ensure_video_writer(frame_size, fps)
        await self._flush_pending_frames()
        return self._video_writer is not None

    def _queue_pending_frame(
        self,
        bgr_frame: np.ndarray,
        overlay: OverlayRenderInfo,
    ) -> None:
        if bgr_frame is None:
            return
        frame_copy = np.array(bgr_frame, copy=True)
        self._pending_video_frames.append((overlay, frame_copy))
        if (
            len(self._pending_video_frames) >= self._pending_frame_limit
            and not self._pending_fps_warning_logged
        ):
            self._logger.warning(
                "Video writer waiting for FPS hint; buffering %d frames",
                len(self._pending_video_frames),
            )
            self._pending_fps_warning_logged = True

    async def _flush_pending_frames(self) -> None:
        if not self._pending_video_frames or self._video_writer is None:
            return
        pending = list(self._pending_video_frames)
        self._pending_video_frames.clear()
        self._pending_fps_warning_logged = False
        for overlay, frame in pending:
            await self._write_video_frame(frame, overlay)

    async def _write_video_frame(self, bgr_frame: np.ndarray, overlay: OverlayRenderInfo) -> bool:
        if self._video_writer is None:
            return False

        writer = self._video_writer
        overlay_cfg = dict(self.overlay_config)

        def convert_and_write() -> bool:
            # Input is already BGR, just copy to avoid modifying the original if we render overlay
            # (Actually, we can modify in place if we are sure it's a copy or we don't care, 
            # but let's be safe and copy if we render overlay. 
            # Wait, _render_overlay modifies in place.
            # The bgr_frame comes from frame_to_bgr which returns a new array.
            # But it might be used for stills too.
            # If we modify it here, the still save might see the overlay if it happens after?
            # In write_frame, video write happens before still save.
            # So we should copy if we are saving stills too?
            # Or just copy always to be safe.)
            frame_bgr = bgr_frame.copy()
            self._render_overlay(frame_bgr, overlay, overlay_cfg)
            writer.write(frame_bgr)
            return True

        try:
            success = await asyncio.to_thread(convert_and_write)
        except Exception as exc:  # pragma: no cover - defensive
            self._logger.warning("Video write error (frame %d): %s", overlay.frame_number, exc)
            return False

        if success:
            self._fps_tracker.record_software_frame()
        return success



    async def _release_video_writer(self) -> None:
        if self._video_writer is None:
            if self._picamera_encoder is None:
                self._fps_tracker.reset()
            return

        writer = self._video_writer
        video_path = self._video_path
        frame_count = self._fps_tracker.frame_count
        writer_codec = self._writer_codec

        def _release() -> None:
            try:
                writer.release()
            except Exception:
                pass

        await asyncio.to_thread(_release)
        self._video_writer = None
        self._writer_codec = None
        self._pending_video_frames.clear()
        self._pending_fps_warning_logged = False
        self._fps_tracker.reset()

        if video_path is not None:
            self._logger.info(
                "Video closed -> %s (%d frames, codec=%s)",
                video_path,
                frame_count,
                writer_codec or "unknown",
            )

    def _normalize_fps(self, fps_hint: float) -> float:
        if fps_hint and fps_hint > 0:
            return max(1.0, min(float(fps_hint), self.max_fps))
        return min(self.max_fps, 30.0)

    def _update_sensor_fps(self, payload: "FramePayload") -> Optional[float]:
        sensor_ts = payload.sensor_timestamp_ns
        if sensor_ts is None:
            self._sensor_timestamp_failures += 1
            if self._sensor_timestamp_failures >= self._sensor_timestamp_failure_limit:
                self._waiting_for_sensor_fps = False
            return None
        self._sensor_timestamp_failures = 0
        last_ts = self._sensor_last_timestamp_ns
        self._sensor_last_timestamp_ns = sensor_ts
        if last_ts is None or sensor_ts <= last_ts:
            return None
        frames_spanned = max(1, (payload.dropped_since_last or 0) + 1)
        delta_ns = sensor_ts - last_ts
        interval_ns = delta_ns / frames_spanned
        if interval_ns <= 0:
            return None
        fps = 1_000_000_000.0 / interval_ns
        if fps <= 0:
            return None
        if self._sensor_fps_estimate is None:
            self._sensor_fps_estimate = fps
        else:
            alpha = self._sensor_smoothing
            self._sensor_fps_estimate = (1 - alpha) * self._sensor_fps_estimate + alpha * fps
        self._sensor_fps_estimate = min(self._sensor_fps_estimate, self.max_fps)
        self._video_fps_hint = self._sensor_fps_estimate
        self._waiting_for_sensor_fps = False
        return self._sensor_fps_estimate

    @staticmethod
    def _coerce_slug(candidate: Optional[str], default: str) -> str:
        if not candidate:
            return default
        cleaned = ''.join(ch if (ch.isalnum() or ch in {'-', '_'}) else '_' for ch in candidate.strip())
        cleaned = cleaned.strip('._')
        return cleaned or default



    def _render_overlay(self, frame: np.ndarray, overlay: OverlayRenderInfo, overlay_cfg: dict) -> None:
        if not overlay_cfg.get('show_frame_number', True):
            return

        font_scale = overlay_cfg.get('font_scale_base', 0.6)
        thickness = overlay_cfg.get('thickness_base', 1)
        text_color = (
            overlay_cfg.get('text_color_r', 0),
            overlay_cfg.get('text_color_g', 0),
            overlay_cfg.get('text_color_b', 0),
        )

        margin_left = overlay_cfg.get('margin_left', 10)
        line_start_y = overlay_cfg.get('line_start_y', 30)

        border_thickness = max(1, thickness * 3)
        border_color = (0, 0, 0)

        components = [f"{overlay.frame_number}"]
        if overlay_cfg.get('show_recording_timestamp', True):
            components.append(overlay.timestamp_text)
        if overlay_cfg.get('show_sensor_timestamp', True):
            sensor_text = overlay.sensor_text
            if sensor_text:
                components.append(sensor_text)
        text = " | ".join(components)

        cv2.putText(
            frame,
            text,
            (margin_left, line_start_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            border_color,
            border_thickness,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            text,
            (margin_left, line_start_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            text_color,
            thickness,
            cv2.LINE_AA,
        )

    def _install_overlay_callback(self) -> None:
        if (
            not self.camera
            or not hasattr(self.camera, "post_callback")
            or not self.main_size
            or not self.overlay_config.get("show_frame_number", True)
        ):
            return
        if MappedArray is None:
            return

        previous = getattr(self.camera, "post_callback", None)
        self._overlay_frame_counter = 0

        def callback(request) -> None:
            if previous:
                previous(request)
            metadata = self._next_overlay_metadata()
            if metadata is None:
                self._overlay_frame_counter += 1
                metadata = OverlayRenderInfo(
                    frame_number=self._overlay_frame_counter,
                    timestamp_unix=time.time(),
                    sensor_timestamp_ns=None,
                )
            else:
                self._overlay_frame_counter = metadata.frame_number
            self._apply_overlay_to_request(request, metadata)

        self._overlay_previous_callback = previous
        self._overlay_callback = callback
        self.camera.post_callback = callback
        self._fps_tracker.start_hardware_tracking()

    def _remove_overlay_callback(self) -> None:
        if not self.camera or not hasattr(self.camera, "post_callback"):
            return
        if self._overlay_callback is None:
            return
        self.camera.post_callback = self._overlay_previous_callback
        self._overlay_previous_callback = None
        self._overlay_callback = None
        self._fps_tracker.stop_hardware_tracking()

    def _apply_overlay_to_request(self, request, overlay: OverlayRenderInfo) -> None:
        if MappedArray is None or not self.main_size:
            return
        width, height = self.main_size
        expected_rows = height * 3 // 2
        try:
            with MappedArray(request, "main", write=True) as mapped:
                array = mapped.array
                if array is None or array.shape[0] < expected_rows:
                    return
                stride = array.shape[1]
                active_width = min(width, stride)
                window = array[:expected_rows, :active_width]
                yuv = np.ascontiguousarray(window)
                bgr = cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_I420)
                self._render_overlay(bgr, overlay, dict(self.overlay_config))
                updated = cv2.cvtColor(bgr, cv2.COLOR_BGR2YUV_I420)
                window[:, :] = updated
        except Exception as exc:  # pragma: no cover - defensive
            self._logger.debug("Overlay application failed: %s", exc)
        finally:
            self._fps_tracker.record_hardware_frame()

    def set_trial_context(self, trial_number: Optional[int], trial_label: Optional[str] = None) -> None:
        try:
            if trial_number is None:
                raise ValueError
            numeric = int(trial_number)
            if numeric <= 0:
                raise ValueError
            self.trial_number = numeric
        except (TypeError, ValueError):
            self.trial_number = 1
        self.trial_label = (trial_label or "").strip()
        self._logger.debug(
            "Trial context updated -> trial=%s label=%s",
            self.trial_number,
            self.trial_label or "<none>",
        )

    @property
    def _trial_suffix(self) -> str:
        suffix_number = self.trial_number if self.trial_number > 0 else 1
        return f"_{suffix_number}"

__all__ = ["CameraStoragePipeline", "StorageWriteResult"]
