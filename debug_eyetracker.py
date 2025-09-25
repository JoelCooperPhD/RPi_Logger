#!/usr/bin/env python3
"""Async debug utility for the Pupil Labs eye tracker."""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from typing import Optional

from pupil_labs.realtime_api.device import Device
from pupil_labs.realtime_api.discovery import discover_devices
from pupil_labs.realtime_api.streaming.gaze import receive_gaze_data
from pupil_labs.realtime_api.streaming.video import receive_video_frames

LOGGER = logging.getLogger("debug.eye")


async def discover_device(timeout: float) -> Optional[Device]:
    """Return the first discovered device within the timeout window."""
    LOGGER.info("Scanning for devices (timeout %.1fs)...", timeout)
    async for device_info in discover_devices(timeout_seconds=timeout):
        LOGGER.info(
            "Found device '%s' at %s:%s",
            device_info.name,
            device_info.addresses[0],
            device_info.port,
        )
        return Device.from_discovered_device(device_info)
    LOGGER.error("No device discovered")
    return None


async def sample_gaze(device: Device, duration: float) -> int:
    """Receive gaze samples for the specified duration."""
    assert device.address is not None
    gaze_url = f"rtsp://{device.address}:8086/?camera=gaze"
    LOGGER.info("Sampling gaze from %s", gaze_url)

    count = 0
    end_time = time.time() + duration
    async for datum in receive_gaze_data(gaze_url):
        LOGGER.debug(
            "Gaze: worn=%s x=%.3f y=%.3f t=%.3f",
            datum.worn,
            datum.x,
            datum.y,
            datum.timestamp_unix_seconds,
        )
        count += 1
        if time.time() >= end_time:
            break
    LOGGER.info("Received %d gaze samples", count)
    return count


async def sample_video(device: Device, frame_limit: int) -> int:
    """Fetch a limited number of video frames and report basic metadata."""
    assert device.address is not None
    video_url = f"rtsp://{device.address}:8086/?camera=world"
    LOGGER.info("Sampling video from %s", video_url)

    count = 0
    async for frame in receive_video_frames(video_url):
        array = frame.to_ndarray(format="bgr24")
        LOGGER.debug(
            "Frame %d: shape=%s ts=%.3f",
            count + 1,
            array.shape,
            frame.timestamp_unix_seconds,
        )
        count += 1
        if count >= frame_limit:
            break
    LOGGER.info("Received %d video frames", count)
    return count


async def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    timeout = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
    device = await discover_device(timeout)
    if device is None:
        return 1

    try:
        await asyncio.gather(
            sample_gaze(device, duration=5.0),
            sample_video(device, frame_limit=30),
        )
    finally:
        await device.close()

    LOGGER.info("Debug session complete")
    return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
    except KeyboardInterrupt:
        exit_code = 130
    sys.exit(exit_code)
