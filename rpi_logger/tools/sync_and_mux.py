#!/usr/bin/env python3
"""
Synchronization and Muxing Utility

This script processes recorded sessions to:
1. Generate SYNC.json files with timing metadata
2. Automatically mux audio and video files with proper synchronization

Usage:
    python -m rpi_logger.tools.sync_and_mux <session_directory>
    python -m rpi_logger.tools.sync_and_mux <session_directory> --trial 1
    python -m rpi_logger.tools.sync_and_mux <session_directory> --all-trials
"""

import asyncio
import argparse
import re
import sys
from pathlib import Path
from typing import Iterable, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rpi_logger.modules.base.sync_metadata import SyncMetadataWriter
from rpi_logger.modules.base.av_muxer import AVMuxer
from rpi_logger.modules.base.constants import AV_MUXING_TIMEOUT_SECONDS, AV_DELETE_SOURCE_FILES
from rpi_logger.core.logging_config import configure_logging
from rpi_logger.core.logging_utils import get_module_logger

configure_logging()
logger = get_module_logger(__name__)


async def find_trial_files(session_dir: Path, trial_number: int) -> dict:
    """
    Find audio and video files for a specific trial.

    Returns:
        Dict with 'audio', 'videos' (list), 'audio_csv', 'video_csvs' (dict)
    """
    files = {
        'audio': None,
        'videos': [],
        'audio_csv': None,
        'video_csvs': {},
        'session_timestamp': None
    }

    pattern_trial = f"*trial{trial_number:03d}*"

    audio_files = list(session_dir.glob(f"{pattern_trial}*.wav"))
    if audio_files:
        files['audio'] = audio_files[0]

    video_files = [
        path for path in session_dir.glob(f"{pattern_trial}*.mp4")
        if "_AV_" not in path.name
    ]
    if not video_files:
        h264_files = list(session_dir.glob(f"{pattern_trial}*.h264"))
        if h264_files:
            logger.info("Waiting for mp4 conversion (%d files)...", len(h264_files))

            timeout_seconds = 60
            start_time = asyncio.get_event_loop().time()
            stable_count = 0
            last_file_sizes = {}

            while asyncio.get_event_loop().time() - start_time < timeout_seconds:
                await asyncio.sleep(0.5)
                video_files = [
                    path for path in session_dir.glob(f"{pattern_trial}*.mp4")
                    if "_AV_" not in path.name
                ]

                if len(video_files) >= len(h264_files):
                    current_sizes = {f: f.stat().st_size for f in video_files if f.exists()}

                    if current_sizes == last_file_sizes:
                        stable_count += 1
                        if stable_count >= 3:
                            elapsed = asyncio.get_event_loop().time() - start_time
                            logger.info("MP4 conversion complete (%.1fs, %d files)", elapsed, len(video_files))
                            break
                    else:
                        stable_count = 0
                        last_file_sizes = current_sizes

            if not video_files or len(video_files) < len(h264_files):
                logger.warning("MP4 conversion incomplete after %d seconds, converting h264 sources locally", timeout_seconds)
                converted: list[tuple[int, Path]] = []
                for h264_file in h264_files:
                    match = re.search(r'CAM(\d+)', h264_file.name)
                    if not match:
                        continue
                    cam_id = int(match.group(1))
                    mp4_path = await _remux_h264_to_mp4(h264_file)
                    if mp4_path is None:
                        logger.warning(
                            "Falling back to raw H264 for CAM%d; resulting mux may have unsynchronised audio",
                            cam_id,
                        )
                        converted.append((cam_id, h264_file))
                    else:
                        converted.append((cam_id, mp4_path))
                files['videos'].extend(converted)

    if not files['videos']:
        for video_file in video_files:
            match = re.search(r'CAM(\d+)', video_file.name)
            if not match:
                continue
            cam_id = int(match.group(1))
            if video_file.suffix.lower() == '.h264':
                mp4_path = await _remux_h264_to_mp4(video_file)
                if mp4_path is not None:
                    files['videos'].append((cam_id, mp4_path))
                else:
                    logger.warning(
                        "Unable to convert %s; using raw H264 for CAM%d",
                        video_file.name,
                        cam_id,
                    )
                    files['videos'].append((cam_id, video_file))
            else:
                files['videos'].append((cam_id, video_file))

    files['videos'].sort(key=lambda x: x[0])

    audio_timing_files = list(session_dir.glob(f"*AUDIOTIMING*trial{trial_number:03d}*.csv"))
    if audio_timing_files:
        files['audio_csv'] = audio_timing_files[0]

    video_timing_files = list(session_dir.glob(f"*CAMTIMING*trial{trial_number:03d}*.csv"))
    for timing_file in video_timing_files:
        match = re.search(r'CAM(\d+)', timing_file.name)
        if match:
            cam_id = int(match.group(1))
            files['video_csvs'][cam_id] = timing_file

    session_name = session_dir.name
    if "_" in session_name:
        files['session_timestamp'] = session_name.split("_", 1)[1]

    return files


def _extract_fps_from_name(video_path: Path) -> Optional[float]:
    match = re.search(r'(\d+(?:\.\d+)?)fps', video_path.stem)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


async def _remux_h264_to_mp4(h264_path: Path) -> Optional[Path]:
    if h264_path.suffix.lower() != '.h264':
        return h264_path

    mp4_path = h264_path.with_suffix('.mp4')

    if await asyncio.to_thread(mp4_path.exists):
        return mp4_path

    fps = _extract_fps_from_name(h264_path) or 30.0

    cmd = [
        'ffmpeg', '-y',
        '-r', f'{fps:.6f}',
        '-i', str(h264_path),
        '-c:v', 'copy',
        str(mp4_path)
    ]

    logger.info("Converting %s to MP4 for muxing", h264_path.name)

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        try:
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=60)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            logger.error("ffmpeg remux timed out for %s", h264_path.name)
            return None

        if process.returncode != 0:
            logger.error(
                "ffmpeg remux failed for %s: %s",
                h264_path.name,
                stderr.decode('utf-8', errors='ignore')[:500]
            )
            return None

        if not await asyncio.to_thread(mp4_path.exists):
            logger.error(
                "ffmpeg reported success but MP4 not found for %s",
                h264_path.name
            )
            return None

        logger.info("Created MP4 for muxing: %s", mp4_path.name)
        return mp4_path

    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Failed to convert %s to MP4: %s", h264_path.name, exc)
        return None


async def extract_timing_from_csv(csv_path: Path, module_type: str) -> dict:
    """
    Extract timing information from CSV file.

    Returns:
        Dict with start_time_unix and other metadata
    """
    def read_csv_first_line():
        with open(csv_path, 'r') as f:
            header = f.readline()
            first_data = f.readline()
            return first_data.strip().split(',')

    try:
        first_row = await asyncio.to_thread(read_csv_first_line)

        if module_type == 'audio':
            trial, chunk_num, write_time_unix, frames_in_chunk, total_frames = first_row
            return {
                'start_time_unix': float(write_time_unix),
                'first_chunk_frames': int(frames_in_chunk)
            }
        elif module_type == 'camera':
            trial, frame_num, write_time_unix, sensor_timestamp_ns, dropped, total_drops = first_row
            return {
                'start_time_unix': float(write_time_unix),
                'sensor_timestamp_ns': int(sensor_timestamp_ns) if sensor_timestamp_ns else None
            }
    except Exception as e:
        logger.error("Failed to read timing from %s: %s", csv_path, e)
        return {}


async def generate_sync_metadata(session_dir: Path, trial_number: int) -> dict:
    """
    Generate sync metadata from trial files.

    Returns:
        Sync metadata dict
    """
    files = await find_trial_files(session_dir, trial_number)

    if not files['audio'] and not files['videos']:
        logger.error("No audio or video files found for trial %d", trial_number)
        return {}

    modules_data = {}

    if files['audio']:
        audio_data = {
            'device_id': 0,
            'audio_file': str(files['audio']),
        }
        if files['audio_csv']:
            audio_timing = await extract_timing_from_csv(files['audio_csv'], 'audio')
            audio_data['timing_csv'] = str(files['audio_csv'])
            audio_data.update(audio_timing)
        else:
            logger.warning("Audio timing CSV not found for trial %d, sync metadata will be incomplete", trial_number)
        modules_data['AudioRecorder_0'] = audio_data

    for cam_id, video_file in files['videos']:
        video_data = {
            'camera_id': cam_id,
            'video_file': str(video_file),
        }
        if cam_id in files['video_csvs']:
            video_timing = await extract_timing_from_csv(files['video_csvs'][cam_id], 'camera')
            video_data['timing_csv'] = str(files['video_csvs'][cam_id])
            video_data.update(video_timing)
        else:
            logger.warning("Camera timing CSV not found for CAM%d trial %d, sync metadata will be incomplete", cam_id, trial_number)
        modules_data[f'Camera_{cam_id}'] = video_data

    return {
        'trial_number': trial_number,
        'modules': modules_data,
        'session_timestamp': files['session_timestamp']
    }


def discover_trial_numbers(session_dir: Path) -> list[int]:
    """Return sorted trial numbers discovered within a session directory."""
    trial_files = list(session_dir.glob("*trial*"))
    trial_numbers: set[int] = set()

    for path in trial_files:
        match = re.search(r'trial(\d+)', path.name)
        if match:
            trial_numbers.add(int(match.group(1)))

    return sorted(trial_numbers)


async def process_trial(session_dir: Path, trial_number: int, mux: bool = True):
    """
    Process a single trial: generate sync file and optionally mux all cameras.
    """
    logger.info("Processing trial %d in %s", trial_number, session_dir)

    sync_metadata = await generate_sync_metadata(session_dir, trial_number)

    if not sync_metadata.get('modules'):
        logger.warning("No data found for trial %d, skipping", trial_number)
        return

    session_timestamp = sync_metadata.get('session_timestamp', 'session')

    sync_path = await SyncMetadataWriter.write_sync_file(
        session_dir,
        trial_number,
        session_timestamp,
        sync_metadata['modules']
    )

    if not sync_path:
        logger.error("Failed to write sync file for trial %d", trial_number)
        return

    logger.info("Created sync file: %s", sync_path)

    if not mux:
        return

    modules = sync_metadata['modules']
    audio_data = modules.get('AudioRecorder_0', {})
    audio_file = audio_data.get('audio_file')

    camera_modules = {k: v for k, v in modules.items() if k.startswith('Camera_')}

    if not camera_modules:
        logger.info("No camera files found for muxing")
        return

    if not audio_file:
        logger.info("No audio file found for muxing")
        return

    audio_has_timing = 'start_time_unix' in audio_data

    muxer = AVMuxer(
        timeout_seconds=AV_MUXING_TIMEOUT_SECONDS,
        delete_sources=AV_DELETE_SOURCE_FILES
    )

    success_count = 0
    for cam_key, cam_data in camera_modules.items():
        cam_id = cam_data.get('camera_id', 0)
        video_file = cam_data.get('video_file')

        if not video_file:
            logger.warning("No video file for %s", cam_key)
            continue

        video_has_timing = 'start_time_unix' in cam_data

        if not audio_has_timing or not video_has_timing:
            logger.warning("Missing timing data for CAM%d - muxing will proceed with zero offset (no sync)", cam_id)
            logger.warning("Audio timing: %s, Video timing: %s",
                          "present" if audio_has_timing else "MISSING",
                          "present" if video_has_timing else "MISSING")

        output_name = f"{session_timestamp}_AV_CAM{cam_id}_trial{trial_number:03d}.mp4"
        output_path = session_dir / output_name

        cam_sync_metadata = {
            'trial_number': trial_number,
            'modules': {
                'AudioRecorder_0': audio_data,
                cam_key: cam_data
            },
            'session_timestamp': session_timestamp
        }

        success = await muxer.mux_from_sync_metadata(cam_sync_metadata, output_path)

        if success:
            logger.info("Successfully muxed CAM%d A/V to: %s", cam_id, output_name)
            success_count += 1
        else:
            logger.error("Failed to mux A/V for CAM%d trial %d", cam_id, trial_number)

    logger.info("Muxed %d/%d cameras for trial %d", success_count, len(camera_modules), trial_number)


async def process_session(
    session_dir: Path,
    trial_numbers: Optional[Iterable[int]] = None,
    mux: bool = True,
) -> bool:
    """Process one or more trials within a session directory."""

    if not session_dir.exists():
        logger.error("Session directory not found: %s", session_dir)
        return False

    if not session_dir.is_dir():
        logger.error("Not a directory: %s", session_dir)
        return False

    numbers = list(dict.fromkeys(trial_numbers)) if trial_numbers else [1]

    if not numbers:
        logger.error("No trial numbers found in %s", session_dir)
        return False

    for trial_num in numbers:
        await process_trial(session_dir, trial_num, mux=mux)

    return True


async def main():
    parser = argparse.ArgumentParser(
        description="Generate sync metadata and mux audio/video files"
    )
    parser.add_argument('session_dir', type=Path, help='Session directory path')
    parser.add_argument('--trial', type=int, help='Process specific trial number')
    parser.add_argument('--all-trials', action='store_true', help='Process all trials in session')
    parser.add_argument('--no-mux', action='store_true', help='Skip A/V muxing, only generate sync files')

    args = parser.parse_args()

    mux = not args.no_mux

    trial_numbers: Optional[list[int]] = None

    if args.all_trials:
        trial_numbers = discover_trial_numbers(args.session_dir)
    elif args.trial:
        trial_numbers = [args.trial]

    success = await process_session(args.session_dir, trial_numbers, mux=mux)
    return 0 if success else 1


def cli() -> int:
    return asyncio.run(main())


if __name__ == '__main__':
    raise SystemExit(cli())
