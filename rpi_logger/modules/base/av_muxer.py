
import asyncio
import logging
from pathlib import Path
from typing import Optional, Dict, Any

from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger(__name__)


class AVMuxer:

    def __init__(self, timeout_seconds: int = 60, delete_sources: bool = False):
        """
        Audio-Video muxer using ffmpeg.

        Args:
            timeout_seconds: Maximum time to wait for ffmpeg (default 60s)
            delete_sources: Whether to delete source files after successful mux
        """
        self.timeout_seconds = timeout_seconds
        self.delete_sources = delete_sources

    @staticmethod
    def calculate_audio_offset(sync_metadata: Dict[str, Any]) -> Optional[float]:
        """
        Calculate audio offset relative to video from sync metadata.

        Args:
            sync_metadata: Sync metadata dict from SyncMetadataWriter

        Returns:
            Audio offset in seconds (positive if audio started after video),
            or None if insufficient data
        """
        modules = sync_metadata.get("modules", {})

        audio_start = None
        video_start = None

        for module_name, module_data in modules.items():
            if "audio" in module_name.lower() or "mic" in module_name.lower():
                audio_start = module_data.get("start_time_unix")
            elif "camera" in module_name.lower() or "cam" in module_name.lower():
                video_start = module_data.get("start_time_unix")

        if audio_start is None or video_start is None:
            logger.warning("Cannot calculate audio offset: missing start times")
            return None

        offset = audio_start - video_start
        logger.debug("Calculated audio offset: %.3f seconds (audio_start=%.6f, video_start=%.6f)",
                    offset, audio_start, video_start)
        return offset

    async def mux_audio_video(
        self,
        video_path: Path,
        audio_path: Path,
        output_path: Path,
        audio_offset: float = 0.0
    ) -> bool:
        """
        Mux audio and video files using ffmpeg.

        Args:
            video_path: Path to video file (.mp4 or .h264)
            audio_path: Path to audio file (.wav)
            output_path: Path for output muxed file (.mp4)
            audio_offset: Audio offset in seconds (use calculate_audio_offset)

        Returns:
            True if successful, False otherwise
        """
        if not video_path.exists():
            logger.error("Video file not found: %s", video_path)
            return False

        if not audio_path.exists():
            logger.error("Audio file not found: %s", audio_path)
            return False

        video_str = str(video_path.resolve())
        audio_str = str(audio_path.resolve())
        output_str = str(output_path.resolve())

        if audio_offset >= 0:
            cmd = [
                'ffmpeg', '-y',
                '-i', video_str,
                '-itsoffset', f'{audio_offset:.6f}',
                '-i', audio_str,
                '-c:v', 'copy',
                '-c:a', 'aac',
                '-b:a', '192k',
                '-shortest',
                output_str
            ]
        else:
            cmd = [
                'ffmpeg', '-y',
                '-itsoffset', f'{abs(audio_offset):.6f}',
                '-i', video_str,
                '-i', audio_str,
                '-c:v', 'copy',
                '-c:a', 'aac',
                '-b:a', '192k',
                '-shortest',
                output_str
            ]

        try:
            logger.info("Starting A/V mux: video=%s, audio=%s, offset=%.3fs",
                       video_path.name, audio_path.name, audio_offset)

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout_seconds
                )
            except asyncio.TimeoutError:
                logger.error("ffmpeg mux timed out after %d seconds", self.timeout_seconds)
                process.kill()
                await process.wait()
                return False

            if process.returncode != 0:
                stderr_str = stderr.decode('utf-8', errors='ignore')
                logger.error("ffmpeg mux failed (exit code %d): %s",
                           process.returncode, stderr_str[:500])
                return False

            if not output_path.exists():
                logger.error("ffmpeg completed but output file not found: %s", output_path)
                return False

            logger.info("A/V mux successful: %s", output_path.name)

            if self.delete_sources:
                try:
                    video_path.unlink()
                    audio_path.unlink()
                    logger.debug("Deleted source files after muxing")
                except Exception as e:
                    logger.warning("Failed to delete source files: %s", e)

            return True

        except Exception as e:
            logger.error("Failed to mux audio/video: %s", e)
            return False

    async def mux_from_sync_metadata(
        self,
        sync_metadata: Dict[str, Any],
        output_path: Path
    ) -> bool:
        """
        Convenience method to mux using sync metadata.

        Args:
            sync_metadata: Sync metadata dict from SyncMetadataWriter
            output_path: Path for output muxed file (.mp4)

        Returns:
            True if successful, False otherwise
        """
        modules = sync_metadata.get("modules", {})

        video_file = None
        audio_file = None

        for module_name, module_data in modules.items():
            if "camera" in module_name.lower() or "cam" in module_name.lower():
                video_file = module_data.get("video_file")
            elif "audio" in module_name.lower() or "mic" in module_name.lower():
                audio_file = module_data.get("audio_file")

        if not video_file or not audio_file:
            logger.warning("Cannot mux: missing video or audio file in sync metadata")
            return False

        audio_offset = self.calculate_audio_offset(sync_metadata) or 0.0

        return await self.mux_audio_video(
            video_path=Path(video_file),
            audio_path=Path(audio_file),
            output_path=output_path,
            audio_offset=audio_offset
        )
