import asyncio
from pathlib import Path

import pytest

from rpi_logger.modules.Cameras2.runtime import (
    CameraCapabilities,
    CameraDescriptor,
    CameraId,
    CameraRuntimeState,
)
from rpi_logger.modules.Cameras2.runtime.discovery.capabilities import build_capabilities
from rpi_logger.modules.Cameras2.runtime.registry import Registry
from rpi_logger.modules.Cameras2.storage import KnownCamerasCache


@pytest.mark.asyncio
async def test_known_cameras_round_trip(tmp_path: Path):
    cache = KnownCamerasCache(tmp_path / "known.json")
    cam_id = CameraId(backend="usb", stable_id="dev0")
    state = CameraRuntimeState(descriptor=CameraDescriptor(camera_id=cam_id))

    await cache.update(state)
    loaded = await cache.get(cam_id)

    assert loaded is not None
    assert loaded.descriptor.camera_id.stable_id == "dev0"


@pytest.mark.asyncio
async def test_registry_apply_discovery_add_remove():
    registry = Registry()
    desc = CameraDescriptor(camera_id=CameraId(backend="usb", stable_id="dev0"))

    await registry.apply_discovery([desc])
    assert "usb:dev0" in registry.snapshot()

    await registry.apply_discovery([])
    assert "usb:dev0" not in registry.snapshot()


def test_build_capabilities_defaults():
    caps = build_capabilities([{"size": (640, 480), "fps": 30, "pixel_format": "RGB"}])
    assert isinstance(caps, CameraCapabilities)
    assert caps.default_preview_mode is not None
    assert caps.default_record_mode is not None
