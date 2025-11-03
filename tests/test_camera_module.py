import logging
import threading
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import sys


def _install_cv2_stub() -> None:
    if "cv2" in sys.modules:
        return

    cv2_stub = ModuleType("cv2")
    cv2_stub.FONT_HERSHEY_SIMPLEX = 0
    cv2_stub.LINE_AA = 0
    cv2_stub.COLOR_BGR2RGB = 0

    def _noop(*args, **kwargs):  # pragma: no cover - stubbed for tests
        return None

    cv2_stub.putText = _noop
    cv2_stub.circle = _noop
    cv2_stub.cvtColor = lambda frame, flag: frame
    cv2_stub.imwrite = lambda *args, **kwargs: True

    sys.modules["cv2"] = cv2_stub


_install_cv2_stub()

from Modules.Cameras.camera_core.camera_system import CameraSystem
from Modules.Cameras.camera_core.camera_handler import CameraHandler
from Modules.Cameras.camera_core.camera_processor import CameraProcessor
from Modules.Cameras.camera_core.camera_utils import FrameTimingMetadata


class CameraSystemAsyncTests(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.addAsyncCleanup(lambda: self._tmp_dir.cleanup())

        self.session_dir = Path(self._tmp_dir.name)
        args = SimpleNamespace(
            mode="headless",
            enable_commands=False,
            session_dir=self.session_dir,
            output_dir=str(self.session_dir),
            show_preview=True,
            auto_start_recording=False,
        )
        self.system = CameraSystem(args)
        self.system.initialized = True

    async def test_start_recording_awaits_handlers(self):
        camera = SimpleNamespace(
            start_recording=AsyncMock(return_value=None),
            stop_recording=AsyncMock(return_value=None),
        )
        self.system.cameras = [camera]

        success = await self.system.start_recording()

        self.assertTrue(success)
        camera.start_recording.assert_awaited_once()
        called_args, _ = camera.start_recording.await_args
        self.assertEqual(called_args[0], self.session_dir)
        self.assertEqual(called_args[1], 1)
        self.assertTrue(self.system.recording)
        self.assertEqual(self.system.recording_count, 1)

    async def test_stop_recording_awaits_handlers(self):
        camera = SimpleNamespace(
            start_recording=AsyncMock(return_value=None),
            stop_recording=AsyncMock(return_value=None),
        )
        self.system.cameras = [camera]

        await self.system.start_recording()
        stop_success = await self.system.stop_recording()

        self.assertTrue(stop_success)
        camera.stop_recording.assert_awaited_once()
        self.assertFalse(self.system.recording)

    async def test_start_recording_failure_rolls_back(self):
        camera = SimpleNamespace(
            start_recording=AsyncMock(side_effect=RuntimeError("boom")),
            stop_recording=AsyncMock(return_value=None),
        )
        self.system.cameras = [camera]

        success = await self.system.start_recording()

        self.assertFalse(success)
        camera.stop_recording.assert_awaited()
        self.assertFalse(self.system.recording)

    def test_ensure_session_dir_requires_path(self):
        self.system.session_dir = None
        with self.assertRaises(RuntimeError):
            self.system._ensure_session_dir()


class CameraProcessorTests(unittest.IsolatedAsyncioTestCase):

    async def test_write_frame_metadata_runs_on_event_loop_thread(self):
        processor = CameraProcessor.__new__(CameraProcessor)
        processor.logger = logging.getLogger("CameraProcessorTests")

        called_thread = {
            "ident": None
        }

        def write_frame(frame, metadata):
            called_thread["ident"] = threading.get_ident()

        processor.recording_manager = SimpleNamespace(write_frame=write_frame)

        await processor._write_frame_metadata_async(None, FrameTimingMetadata())

        self.assertEqual(called_thread["ident"], threading.get_ident())


class CameraHandlerCleanupTests(unittest.IsolatedAsyncioTestCase):

    async def test_cleanup_stops_loops_and_hardware(self):
        handler = CameraHandler.__new__(CameraHandler)
        handler.logger = logging.getLogger("CameraHandlerCleanupTests")
        handler.recording = False
        handler.recording_manager = SimpleNamespace(cleanup=AsyncMock(return_value=None))
        handler.capture_loop = SimpleNamespace(stop=AsyncMock(return_value=None))
        handler.processor = SimpleNamespace(stop=AsyncMock(return_value=None))
        handler._background_camera_cleanup = AsyncMock(return_value=None)
        handler.stop_recording = AsyncMock(return_value=None)
        handler._capture_task = None
        handler._processor_task = None

        await handler.cleanup()

        handler.recording_manager.cleanup.assert_awaited_once()
        handler.capture_loop.stop.assert_awaited_once()
        handler.processor.stop.assert_awaited_once()
        handler._background_camera_cleanup.assert_awaited_once()

    async def test_cleanup_stops_active_recording(self):
        handler = CameraHandler.__new__(CameraHandler)
        handler.logger = logging.getLogger("CameraHandlerCleanupActive")
        handler.recording = True
        handler.recording_manager = SimpleNamespace(cleanup=AsyncMock(return_value=None))
        handler.capture_loop = SimpleNamespace(stop=AsyncMock(return_value=None))
        handler.processor = SimpleNamespace(stop=AsyncMock(return_value=None))
        handler._background_camera_cleanup = AsyncMock(return_value=None)
        handler.stop_recording = AsyncMock(return_value=None)
        handler._capture_task = None
        handler._processor_task = None

        await handler.cleanup()

        handler.stop_recording.assert_awaited_once()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
