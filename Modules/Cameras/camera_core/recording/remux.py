
import asyncio
import csv
import io
import logging
import subprocess
from pathlib import Path
from typing import Optional

import aiofiles

logger = logging.getLogger(__name__)


async def calculate_actual_fps(csv_path: Path) -> Optional[float]:
    try:
        # Use aiofiles for async file read
        async with aiofiles.open(csv_path, 'r') as f:
            content = await f.read()
            reader = csv.DictReader(io.StringIO(content))
            rows = list(reader)

        if len(rows) < 2:
            logger.warning(f"Not enough frames in {csv_path} to calculate FPS")
            return None

        first_time = float(rows[0]['write_time_unix'])
        last_time = float(rows[-1]['write_time_unix'])

        total_frames = len(rows)
        duration = last_time - first_time

        if duration <= 0:
            logger.warning(f"Invalid duration in {csv_path}: {duration}")
            return None

        actual_fps = total_frames / duration

        logger.info(
            f"Calculated FPS from {csv_path.name}: "
            f"{actual_fps:.2f} fps ({total_frames} frames / {duration:.2f}s)"
        )

        return actual_fps

    except Exception as e:
        logger.error(f"Failed to calculate FPS from {csv_path}: {e}")
        return None


async def remux_video_with_fps(
    video_path: Path,
    csv_path: Path,
    output_path: Optional[Path] = None,
    replace_original: bool = False
) -> Optional[Path]:
    # Use asyncio.to_thread for blocking file existence checks
    if not await asyncio.to_thread(video_path.exists):
        logger.error(f"Video file not found: {video_path}")
        return None

    if not await asyncio.to_thread(csv_path.exists):
        logger.error(f"CSV file not found: {csv_path}")
        return None

    actual_fps = await calculate_actual_fps(csv_path)
    if actual_fps is None:
        return None

    if output_path is None:
        output_path = video_path.parent / f"{video_path.stem}_corrected{video_path.suffix}"

    ffmpeg_cmd = [
        'ffmpeg',
        '-y',  # Overwrite output
        '-i', str(video_path),
        '-c:v', 'copy',  # Copy video codec (no re-encode)
        '-r', str(actual_fps),  # Set correct FPS
        str(output_path)
    ]

    try:
        logger.info(f"Remuxing {video_path.name} with FPS={actual_fps:.2f}")

        # Use asyncio subprocess instead of blocking subprocess.run
        process = await asyncio.create_subprocess_exec(
            *ffmpeg_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60)

            if process.returncode != 0:
                logger.error(f"ffmpeg remux failed: {stderr.decode()}")
                return None

        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            logger.error(f"ffmpeg remux timed out for {video_path}")
            return None

        logger.info(f"Remuxed video saved: {output_path}")

        if replace_original:
            await asyncio.to_thread(video_path.unlink)  # Remove original
            await asyncio.to_thread(output_path.rename, video_path)  # Rename corrected to original name
            logger.info(f"Replaced original with corrected video: {video_path}")
            return video_path

        return output_path

    except Exception as e:
        logger.error(f"Failed to remux {video_path}: {e}")
        return None


async def auto_remux_recording(video_path: Path, replace_original: bool = True) -> Optional[Path]:
    csv_path = video_path.parent / f"{video_path.stem}_frame_timing.csv"

    if not await asyncio.to_thread(csv_path.exists):
        logger.warning(f"No timing CSV found for {video_path.name}, skipping remux")
        return None

    return await remux_video_with_fps(video_path, csv_path, replace_original=replace_original)
