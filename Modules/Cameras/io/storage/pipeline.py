"""Shared storage pipeline for Cameras compatible modules."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import cv2
import numpy as np
from PIL import Image

try:
    from picamera2.request import MappedArray
except Exception:  # pragma: no cover - allows dev environments without Picamera2
    MappedArray = None  # type: ignore[arg-type]

from .csv_logger import CameraCSVLogger
from ...domain.model import FramePayload
from ...logging_utils import ensure_structured_logger


@dataclass(slots=True)
class StorageWriteResult:
    """Outcome of a storage pipeline write operation."""

    video_written: bool
    image_path: Optional[Path]
    video_fps: float
    writer_codec: Optional[str]


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
        save_stills: bool = False,
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
        self.save_stills = save_stills
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
        self._video_frame_count = 0
        self._writer_codec: Optional[str] = None
        self._writer_fps: float = 30.0
        self._video_start_monotonic: Optional[float] = None
        self._video_fps_hint: Optional[float] = None

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
        return self._video_frame_count

    async def start(self) -> None:
        """Prepare CSV logger and reset video writer state."""
        await asyncio.to_thread(self.save_dir.mkdir, parents=True, exist_ok=True)
        slug = self.camera_slug or f"cam{self.camera_index}"
        self._video_path = self.save_dir / f"{slug}_recording.mp4"
        self._csv_path = self.save_dir / f"{slug}_frame_timing.csv"
        csv_logger = CameraCSVLogger(self.camera_index, self._csv_path)
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
        rgb_frame: Optional[np.ndarray],
        payload: "FramePayload",
        *,
        fps_hint: float,
        pil_image: Optional[Image.Image] = None,
    ) -> StorageWriteResult:
        """Persist a frame to disk and optionally to the video writer."""
        if fps_hint > 0:
            self._video_fps_hint = fps_hint

        if self.uses_hardware_encoder and self._picamera_encoder is not None:
            image_path: Optional[Path] = None
            if self.save_stills and pil_image is not None:
                image_path = await self._save_image(pil_image, payload.capture_index, payload.timestamp)
            self._video_frame_count += 1
            return StorageWriteResult(
                video_written=True,
                image_path=image_path,
                video_fps=self.video_output_fps,
                writer_codec=self._writer_codec,
            )

        if rgb_frame is None:
            raise RuntimeError("RGB frame required for software encoding path")

        if self._video_writer is None:
            await self._ensure_video_writer((rgb_frame.shape[1], rgb_frame.shape[0]), fps_hint)

        video_written = False
        if self._video_writer is not None:
            video_written = await self._write_video_frame(rgb_frame, payload.capture_index)

        image_path: Optional[Path] = None
        if self.save_stills:
            target_image = pil_image if pil_image is not None else Image.fromarray(rgb_frame)
            image_path = await self._save_image(target_image, payload.capture_index, payload.timestamp)

        return StorageWriteResult(
            video_written=video_written,
            image_path=image_path,
            video_fps=self.video_output_fps,
            writer_codec=self._writer_codec,
        )

    @property
    def video_output_fps(self) -> float:
        if self._video_frame_count == 0 or self._video_start_monotonic is None:
            return 0.0
        elapsed = max(time.monotonic() - self._video_start_monotonic, 1e-3)
        return self._video_frame_count / elapsed

    def log_frame(self, payload: "FramePayload", *, queue_drops: int = 0) -> None:
        """Record frame metadata to CSV if logging is active."""
        if self._csv_logger is None:
            return

        self._csv_logger.log_frame(
            payload.capture_index,
            frame_time_unix=payload.timestamp,
            sensor_timestamp_ns=payload.sensor_timestamp_ns,
            dropped_since_last=payload.dropped_since_last,
            storage_queue_drops=queue_drops,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    async def start_video_recording(self, fps_hint: Optional[float] = None) -> None:
        """Start Picamera2-based recording when a camera handle is available."""
        if not self.uses_hardware_encoder or self.camera is None or self._video_path is None:
            self.uses_hardware_encoder = False
            return
        if self._picamera_encoder is not None:
            return

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

        try:
            encoder = H264Encoder(framerate=fps, enable_sps_framerate=True)
        except TypeError:
            encoder = H264Encoder(framerate=fps)
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
        self._video_frame_count = 0
        self._writer_codec = "H264"
        self._video_start_monotonic = time.monotonic()
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
            self._video_frame_count,
        )
        self._picamera_encoder = None
        self._picamera_output = None

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
            self._video_frame_count = 0
            self._writer_codec = codec
            self._writer_fps = fps
            self._video_start_monotonic = None
            self._fourcc = fourcc
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

    async def _write_video_frame(self, rgb_frame: np.ndarray, frame_number: int) -> bool:
        if self._video_writer is None:
            return False

        writer = self._video_writer
        overlay_cfg = dict(self.overlay_config)

        def convert_and_write() -> bool:
            frame_rgb = np.ascontiguousarray(rgb_frame)
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
            self._burn_frame_number(frame_bgr, frame_number, overlay_cfg)
            writer.write(frame_bgr)
            return True

        try:
            success = await asyncio.to_thread(convert_and_write)
        except Exception as exc:  # pragma: no cover - defensive
            self._logger.warning("Video write error (frame %d): %s", frame_number, exc)
            return False

        if success:
            self._video_frame_count += 1
            if self._video_start_monotonic is None:
                self._video_start_monotonic = time.monotonic()
        return success

    async def _save_image(self, image: Image.Image, frame_number: int, timestamp: float) -> Optional[Path]:
        filename = self._image_filename(frame_number, timestamp)
        path = self.save_dir / filename
        format_name = "JPEG" if self.save_format in {"jpeg", "jpg"} else self.save_format.upper()
        save_kwargs: dict[str, object] = {}
        if format_name == "JPEG":
            save_kwargs["quality"] = self.save_quality

        try:
            overlay_cfg = dict(self.overlay_config)
            processed_image = await asyncio.to_thread(
                self._prepare_image_with_overlay,
                image,
                frame_number,
                overlay_cfg,
            )
            await asyncio.to_thread(processed_image.save, path, format=format_name, **save_kwargs)
            return path
        except Exception as exc:  # pragma: no cover - defensive
            self._logger.warning("Image save error (frame %d): %s", frame_number, exc)
            return None

    async def _release_video_writer(self) -> None:
        if self._video_writer is None:
            if self._picamera_encoder is None:
                self._video_frame_count = 0
            return

        writer = self._video_writer
        video_path = self._video_path
        frame_count = self._video_frame_count
        writer_codec = self._writer_codec

        def _release() -> None:
            try:
                writer.release()
            except Exception:
                pass

        await asyncio.to_thread(_release)
        self._video_writer = None
        self._video_frame_count = 0
        self._writer_codec = None
        self._video_start_monotonic = None

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

    def _image_filename(self, frame_number: int, timestamp: float) -> str:
        from datetime import datetime

        dt = datetime.fromtimestamp(timestamp)
        base_name = dt.strftime("%Y%m%d_%H%M%S_%f")
        ext = "jpg" if self.save_format in {"jpeg", "jpg"} else self.save_format
        slug = self.camera_slug or f"cam{self.camera_index}"
        return f"{slug}_frame{frame_number:06d}_{base_name}.{ext}"

    @staticmethod
    def _coerce_slug(candidate: Optional[str], default: str) -> str:
        if not candidate:
            return default
        cleaned = ''.join(ch if (ch.isalnum() or ch in {'-', '_'}) else '_' for ch in candidate.strip())
        cleaned = cleaned.strip('._')
        return cleaned or default

    def _prepare_image_with_overlay(
        self,
        image: Image.Image,
        frame_number: int,
        overlay_cfg: dict,
    ) -> Image.Image:
        """Return a copy of ``image`` with the frame number burned in."""

        try:
            working = image.convert("RGB") if image.mode != "RGB" else image.copy()
        except Exception:
            return image

        frame_rgb = np.asarray(working)
        if frame_rgb.ndim != 3 or frame_rgb.shape[2] < 3:
            return working

        frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        self._burn_frame_number(frame_bgr, frame_number, overlay_cfg)
        frame_rgb_with_overlay = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        return Image.fromarray(frame_rgb_with_overlay)

    def _burn_frame_number(self, frame: np.ndarray, frame_number: int, overlay_cfg: dict) -> None:
        font_scale = overlay_cfg.get('font_scale_base', 0.6)
        thickness = overlay_cfg.get('thickness_base', 1)

        text_color_r = overlay_cfg.get('text_color_r', 0)
        text_color_g = overlay_cfg.get('text_color_g', 0)
        text_color_b = overlay_cfg.get('text_color_b', 0)
        text_color = (text_color_r, text_color_g, text_color_b)

        margin_left = overlay_cfg.get('margin_left', 10)
        line_start_y = overlay_cfg.get('line_start_y', 30)

        border_thickness = thickness * 3
        border_color = (0, 0, 0)
        text = f"{frame_number}"

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
            self._overlay_frame_counter += 1
            self._apply_overlay_to_request(request, self._overlay_frame_counter)

        self._overlay_previous_callback = previous
        self._overlay_callback = callback
        self.camera.post_callback = callback

    def _remove_overlay_callback(self) -> None:
        if not self.camera or not hasattr(self.camera, "post_callback"):
            return
        if self._overlay_callback is None:
            return
        self.camera.post_callback = self._overlay_previous_callback
        self._overlay_previous_callback = None
        self._overlay_callback = None

    def _apply_overlay_to_request(self, request, frame_number: int) -> None:
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
                self._burn_frame_number(bgr, frame_number, dict(self.overlay_config))
                updated = cv2.cvtColor(bgr, cv2.COLOR_BGR2YUV_I420)
                window[:, :] = updated
        except Exception as exc:  # pragma: no cover - defensive
            self._logger.debug("Overlay application failed: %s", exc)


__all__ = ["CameraStoragePipeline", "StorageWriteResult"]
