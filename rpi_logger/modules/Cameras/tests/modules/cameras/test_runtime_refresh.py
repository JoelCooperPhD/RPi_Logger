import asyncio
import logging
import types

import pytest

from rpi_logger.modules.Cameras.bridge import CamerasRuntime
from rpi_logger.modules.Cameras.runtime import CameraDescriptor, CameraId, CapabilityMode
from rpi_logger.modules.Cameras.runtime.discovery.capabilities import build_capabilities


class DummyPrefs:
    def snapshot(self):
        return {}


def _make_context(tmp_path):
    return types.SimpleNamespace(
        args=types.SimpleNamespace(enable_commands=True),
        module_dir=tmp_path,
        logger=logging.getLogger("CamerasTest"),
        model=types.SimpleNamespace(preferences=DummyPrefs(), session_name="test_session"),
        controller=None,
        supervisor=None,
        view=None,
    )


@pytest.mark.asyncio
async def test_runtime_refreshes_and_attaches_multiple_cameras(monkeypatch, tmp_path):
    descriptors = [
        CameraDescriptor(camera_id=CameraId(backend="usb", stable_id="dev0", dev_path="/dev/video0")),
        CameraDescriptor(camera_id=CameraId(backend="usb", stable_id="dev1", dev_path="/dev/video1")),
    ]
    caps = build_capabilities([{"size": (640, 480), "fps": 30, "pixel_format": "RGB"}])

    monkeypatch.setattr(
        "rpi_logger.modules.Cameras.bridge.discover_usb_devices",
        lambda logger=None: descriptors,
    )
    monkeypatch.setattr("rpi_logger.modules.Cameras.bridge.discover_picam", lambda logger=None: [])

    async def fake_probe(self, descriptor):
        return caps

    async def fake_open(self, descriptor, mode):
        class Handle:
            async def frames(self):
                for i in range(3):
                    yield types.SimpleNamespace(data=None, frame_number=i)

            async def stop(self):
                return None

        return Handle()

    monkeypatch.setattr(CamerasRuntime, "_probe_capabilities", fake_probe, raising=False)
    monkeypatch.setattr(CamerasRuntime, "_open_backend", fake_open, raising=False)

    ctx = _make_context(tmp_path)
    runtime = CamerasRuntime(ctx)
    runtime.view.set_status = lambda *args, **kwargs: None
    runtime.view.add_camera = lambda *args, **kwargs: None
    runtime.view.remove_camera = lambda *args, **kwargs: None
    runtime.view.update_metrics = lambda *args, **kwargs: None

    await runtime.start()
    assert len(runtime._camera_runtime) == 2

    await asyncio.sleep(0.2)
    await runtime.refresh_cameras()
    assert len(runtime._camera_runtime) == 2

    await runtime.shutdown()


def test_percent_preview_fps_sets_keep_every(tmp_path):
    ctx = _make_context(tmp_path)
    runtime = CamerasRuntime(ctx)
    fallback_mode = CapabilityMode(size=(640, 480), fps=60, pixel_format="RGB")

    settings = {"preview_resolution": "640x480", "preview_fps": "10%"}
    result = runtime._settings_to_mode_request(
        settings,
        fallback_mode,
        prefix="preview",
    )
    assert result.keep_every == 10
    assert result.fps is None

    with pytest.raises(ValueError):
        runtime._settings_to_mode_request(
            {"preview_resolution": "640x480", "preview_fps": "0%"},
            fallback_mode,
            prefix="preview",
        )
