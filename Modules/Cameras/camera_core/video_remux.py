#!/usr/bin/env python3
"""
Video remuxing utility to correct FPS based on actual frame timing data.

This module provides functions to:
1. Calculate actual FPS from frame timing CSV files
2. Remux video files with corrected FPS metadata
3. Ensure playback matches actual recording speed
"""

import csv
import logging
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger("VideoRemux")


def calculate_actual_fps(csv_path: Path) -> Optional[float]:
    """
    Calculate actual FPS from frame timing CSV.

    Args:
        csv_path: Path to frame_timing.csv file

    Returns:
        Actual FPS as float, or None if calculation fails
    """
    try:
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if len(rows) < 2:
            logger.warning(f"Not enough frames in {csv_path} to calculate FPS")
            return None

        # Get first and last frame timestamps
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


def remux_video_with_fps(
    video_path: Path,
    csv_path: Path,
    output_path: Optional[Path] = None,
    replace_original: bool = False
) -> Optional[Path]:
    """
    Remux video file with corrected FPS from timing CSV.

    Args:
        video_path: Path to original video file
        csv_path: Path to frame_timing.csv with actual timestamps
        output_path: Optional output path (default: video_path with _corrected suffix)
        replace_original: If True, replace original file with corrected one

    Returns:
        Path to remuxed video, or None if remuxing fails
    """
    if not video_path.exists():
        logger.error(f"Video file not found: {video_path}")
        return None

    if not csv_path.exists():
        logger.error(f"CSV file not found: {csv_path}")
        return None

    # Calculate actual FPS
    actual_fps = calculate_actual_fps(csv_path)
    if actual_fps is None:
        return None

    # Determine output path
    if output_path is None:
        output_path = video_path.parent / f"{video_path.stem}_corrected{video_path.suffix}"

    # Build ffmpeg remux command (copy codec, no re-encoding)
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

        result = subprocess.run(
            ffmpeg_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            check=True
        )

        logger.info(f"Remuxed video saved: {output_path}")

        # Replace original if requested
        if replace_original:
            video_path.unlink()  # Remove original
            output_path.rename(video_path)  # Rename corrected to original name
            logger.info(f"Replaced original with corrected video: {video_path}")
            return video_path

        return output_path

    except subprocess.CalledProcessError as e:
        logger.error(f"ffmpeg remux failed: {e.stderr.decode()}")
        return None
    except subprocess.TimeoutExpired:
        logger.error(f"ffmpeg remux timed out for {video_path}")
        return None
    except Exception as e:
        logger.error(f"Failed to remux {video_path}: {e}")
        return None


def auto_remux_recording(video_path: Path, replace_original: bool = True) -> Optional[Path]:
    """
    Automatically remux a recording by finding its paired CSV file.

    Args:
        video_path: Path to video file
        replace_original: If True, replace original with corrected version

    Returns:
        Path to remuxed video, or None if remuxing fails
    """
    # Look for matching CSV file
    csv_path = video_path.parent / f"{video_path.stem}_frame_timing.csv"

    if not csv_path.exists():
        logger.warning(f"No timing CSV found for {video_path.name}, skipping remux")
        return None

    return remux_video_with_fps(video_path, csv_path, replace_original=replace_original)
