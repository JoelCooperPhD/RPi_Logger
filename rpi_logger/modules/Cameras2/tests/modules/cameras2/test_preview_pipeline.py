import asyncio
import types

import pytest

from rpi_logger.modules.Cameras2.runtime import CameraId, CapabilityMode, ModeSelection
from rpi_logger.modules.Cameras2.runtime.preview.pipeline import PreviewPipeline


@pytest.mark.asyncio
async def test_preview_pipeline_respects_fps_cap():
    cam_id = CameraId(backend="usb", stable_id="cam0")
    selection = ModeSelection(mode=CapabilityMode(size=(640, 480), fps=30, pixel_format="RGB"), target_fps=1.0)
    queue: asyncio.Queue = asyncio.Queue()
    seen = 0

    def consumer(_):
        nonlocal seen
        seen += 1

    pipeline = PreviewPipeline()
    pipeline.start(cam_id, queue, consumer, selection)
    await queue.put(types.SimpleNamespace(frame_number=1))
    await queue.put(types.SimpleNamespace(frame_number=2))
    await asyncio.sleep(1.5)  # allow one frame to pass
    await queue.put(None)
    await asyncio.sleep(0.2)
    assert seen <= 2


@pytest.mark.asyncio
async def test_preview_pipeline_reports_drops():
    cam_id = CameraId(backend="usb", stable_id="cam1")
    selection = ModeSelection(mode=CapabilityMode(size=(640, 480), fps=30, pixel_format="RGB"), target_fps=1.0)
    queue: asyncio.Queue = asyncio.Queue()

    pipeline = PreviewPipeline()
    pipeline.start(cam_id, queue, lambda _: None, selection)
    for _ in range(4):
        await queue.put(types.SimpleNamespace(frame_number=1))
    await queue.put(None)
    await asyncio.sleep(0.2)
    metrics = pipeline.metrics(cam_id)
    assert metrics["preview_dropped"] > 0


@pytest.mark.asyncio
async def test_preview_pipeline_keep_every_ratio():
    cam_id = CameraId(backend="usb", stable_id="cam2")
    selection = ModeSelection(mode=CapabilityMode(size=(640, 480), fps=30, pixel_format="RGB"), keep_every=2)
    queue: asyncio.Queue = asyncio.Queue()
    seen = 0

    def consumer(_):
        nonlocal seen
        seen += 1

    pipeline = PreviewPipeline()
    pipeline.start(cam_id, queue, consumer, selection)
    for _ in range(6):
        await queue.put(types.SimpleNamespace(frame_number=_))
    await queue.put(None)
    await asyncio.sleep(0.2)
    # With keep_every=2 we should see roughly half (rounded up for first frame kept).
    assert seen == 3
