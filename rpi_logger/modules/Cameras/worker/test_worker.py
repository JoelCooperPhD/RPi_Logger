#!/usr/bin/env python3
"""
Test script for camera worker architecture.

Run with: python -m rpi_logger.modules.Cameras.worker.test_worker

This spawns a worker for the first available camera, starts preview,
records for a few seconds, then shuts down.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import tempfile
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def test_worker():
    from rpi_logger.modules.Cameras.runtime.coordinator.manager import WorkerManager
    from rpi_logger.modules.Cameras.worker.protocol import (
        RespPreviewFrame,
        RespStateUpdate,
        RespRecordingStarted,
        RespRecordingComplete,
        RespReady,
        RespError,
    )

    # Track state
    preview_count = 0
    state_updates = []
    worker_ready = asyncio.Event()

    def on_preview(key: str, msg: RespPreviewFrame):
        nonlocal preview_count
        preview_count += 1
        if preview_count % 10 == 1:
            logger.info("Preview frame %d: %dx%d, %d bytes",
                       preview_count, msg.width, msg.height, len(msg.frame_data))

    def on_state(key: str, msg: RespStateUpdate):
        state_updates.append(msg)
        logger.info("State: %s recording=%s preview=%s fps_cap=%.1f fps_enc=%.1f",
                   msg.state.name, msg.is_recording, msg.is_previewing,
                   msg.fps_capture, msg.fps_encode)

    def on_ready(key: str, msg: RespReady):
        logger.info("Worker ready: %s/%s caps=%s", msg.camera_type, msg.camera_id, msg.capabilities)
        worker_ready.set()

    def on_recording_started(key: str, msg: RespRecordingStarted):
        logger.info("Recording started: %s", msg.video_path)

    def on_recording_complete(key: str, msg: RespRecordingComplete):
        logger.info("Recording complete: %s (%d frames, %.1fs)",
                   msg.video_path, msg.frames_total, msg.duration_sec)

    def on_error(key: str, msg: RespError):
        logger.error("Worker error: %s (fatal=%s)", msg.message, msg.fatal)

    # Create manager
    manager = WorkerManager(
        on_preview_frame=on_preview,
        on_state_update=on_state,
        on_worker_ready=on_ready,
        on_recording_started=on_recording_started,
        on_recording_complete=on_recording_complete,
        on_error=on_error,
    )

    # Detect camera type - prefer USB for faster testing
    camera_type = "usb"
    camera_id = "/dev/video8"  # Default USB camera path

    # Check what cameras are available
    import os
    import subprocess

    # Try to find USB cameras via v4l2-ctl
    try:
        result = subprocess.run(["v4l2-ctl", "--list-devices"], capture_output=True, text=True)
        if "UVC" in result.stdout or "USB" in result.stdout:
            # Parse to find a USB camera device
            lines = result.stdout.split('\n')
            for i, line in enumerate(lines):
                if "UVC" in line or "USB Camera" in line:
                    # Next indented line is the device path
                    for j in range(i+1, len(lines)):
                        if lines[j].strip().startswith("/dev/video"):
                            camera_id = lines[j].strip()
                            logger.info("Found USB camera: %s", camera_id)
                            break
                    break
    except Exception:
        pass

    if not os.path.exists(camera_id):
        # Fallback to Pi camera
        try:
            from picamera2 import Picamera2
            cams = Picamera2.global_camera_info()
            if cams:
                camera_type = "picam"
                camera_id = "0"
                logger.info("Using Pi camera (no USB camera)")
            else:
                logger.error("No camera found!")
                return
        except Exception:
            logger.error("No camera found!")
            return

    try:
        # Spawn worker
        logger.info("Spawning worker for %s:%s", camera_type, camera_id)
        handle = await manager.spawn_worker(
            camera_type=camera_type,
            camera_id=camera_id,
            resolution=(640, 480),
            fps=15.0,
        )

        # Wait for ready
        logger.info("Waiting for worker to be ready...")
        try:
            await asyncio.wait_for(worker_ready.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.error("Worker did not become ready in time")
            return

        # Start preview
        logger.info("Starting preview...")
        await manager.start_preview(
            handle.camera_type + ":" + handle.camera_id,
            preview_size=(320, 180),
            target_fps=10.0,
        )

        # Let preview run for a bit
        logger.info("Preview running for 3 seconds...")
        await asyncio.sleep(3.0)
        logger.info("Received %d preview frames", preview_count)

        # Start recording
        with tempfile.TemporaryDirectory() as tmpdir:
            logger.info("Starting recording to %s", tmpdir)
            await manager.start_recording(
                handle.camera_type + ":" + handle.camera_id,
                output_dir=tmpdir,
                filename="test_recording.avi",
                resolution=(640, 480),
                fps=15.0,
                overlay_enabled=True,
            )

            # Record for 5 seconds
            logger.info("Recording for 5 seconds...")
            await asyncio.sleep(5.0)

            # Stop recording
            logger.info("Stopping recording...")
            await manager.stop_recording(handle.camera_type + ":" + handle.camera_id)

            # Wait a bit for completion
            await asyncio.sleep(1.0)

            # Check if video file exists
            video_path = Path(tmpdir) / "test_recording.avi"
            if video_path.exists():
                size_kb = video_path.stat().st_size / 1024
                logger.info("Video file created: %s (%.1f KB)", video_path, size_kb)
            else:
                logger.warning("Video file not found!")

        # Stop preview
        logger.info("Stopping preview...")
        await manager.stop_preview(handle.camera_type + ":" + handle.camera_id)

        # Final stats
        logger.info("Final preview count: %d", preview_count)
        logger.info("State updates received: %d", len(state_updates))

    finally:
        # Shutdown
        logger.info("Shutting down worker...")
        await manager.shutdown_all()
        logger.info("Test complete!")


def main():
    asyncio.run(test_worker())


if __name__ == "__main__":
    main()
