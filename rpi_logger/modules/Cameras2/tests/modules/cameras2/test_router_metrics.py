import asyncio
import types

import pytest

from rpi_logger.modules.Cameras2.runtime import CameraId, ModeSelection, CapabilityMode, SelectedConfigs
from rpi_logger.modules.Cameras2.runtime.router import Router


class BurstHandle:
    def __init__(self, frames):
        self._frames = frames

    async def frames(self):
        for frame in self._frames:
            yield frame


@pytest.mark.asyncio
async def test_router_tracks_drops_and_backpressure():
    router = Router()
    cam_id = CameraId(backend="usb", stable_id="dev0")
    mode = CapabilityMode(size=(640, 480), fps=30, pixel_format="RGB")
    configs = SelectedConfigs(
        preview=ModeSelection(mode=mode),
        record=ModeSelection(mode=mode),
        storage_profile=None,
    )
    # Small queues to force drops/backpressure
    router.attach(cam_id, BurstHandle([1, 2, 3, 4, 5]), configs, preview_queue_size=1, record_queue_size=1)
    record_q = router.get_record_queue(cam_id)
    assert record_q is not None

    # Drain record queue slowly to trigger backpressure waits
    async def drain():
        while True:
            item = await record_q.get()
            if item is None:
                break
            await asyncio.sleep(0.05)
            record_q.task_done()

    drain_task = asyncio.create_task(drain())
    await asyncio.sleep(0.5)
    await router.stop(cam_id)
    await drain_task

    metrics = router.metrics_for(cam_id)
    assert metrics is not None
    assert metrics.preview_dropped > 0
    assert metrics.record_backpressure > 0
