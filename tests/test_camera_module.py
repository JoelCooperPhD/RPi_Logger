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
from Modules.Cameras.camera_core.camera_processor import CameraProcessor
from Modules.Cameras.camera_core.camera_utils import FrameTimingMetadata
from Modules.Cameras.camera_core.handler.cleanup import HandlerCleanupRunner
from Modules.Cameras.camera_core.runtime import FrameTimingCalculator


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

    async def test_cleanup_dispatches_all_steps(self):
        stop_calls = []
        close_calls = []

        class DummyLoop:
            def __init__(self):
                self.request_stop_called = False
                self.join = AsyncMock(return_value=None)

            def request_stop(self):
                self.request_stop_called = True

        capture_loop = DummyLoop()
        processor_loop = DummyLoop()
        loop_bundle = SimpleNamespace(
            mark_stopped=lambda: None,
            await_start_tasks=AsyncMock(return_value=None),
        )

        handler = SimpleNamespace(
            cam_num=1,
            logger=logging.getLogger("CameraHandlerCleanupTests"),
            recording=False,
            recording_manager=SimpleNamespace(cleanup=AsyncMock(return_value=None)),
            capture_loop=capture_loop,
            processor=processor_loop,
            picam2=SimpleNamespace(
                stop=lambda: stop_calls.append("stop"),
                close=lambda: close_calls.append("close"),
            ),
            loop_bundle=loop_bundle,
            stop_recording=AsyncMock(return_value=None),
            active=True,
        )

        runner = HandlerCleanupRunner(handler)
        report = await runner.run()

        handler.recording_manager.cleanup.assert_awaited_once()
        self.assertTrue(capture_loop.request_stop_called)
        self.assertTrue(processor_loop.request_stop_called)
        self.assertEqual(stop_calls, ["stop"])
        self.assertEqual(close_calls, ["close"])
        self.assertFalse(handler.active)
        self.assertTrue(report.get("success"))

    async def test_cleanup_stops_active_recording(self):
        capture_loop = SimpleNamespace(request_stop=lambda: None, join=AsyncMock(return_value=None))
        processor_loop = SimpleNamespace(request_stop=lambda: None, join=AsyncMock(return_value=None))
        loop_bundle = SimpleNamespace(mark_stopped=lambda: None, await_start_tasks=AsyncMock(return_value=None))

        handler = SimpleNamespace(
            cam_num=2,
            logger=logging.getLogger("CameraHandlerCleanupActive"),
            recording=True,
            recording_manager=SimpleNamespace(cleanup=AsyncMock(return_value=None)),
            capture_loop=capture_loop,
            processor=processor_loop,
            picam2=SimpleNamespace(stop=lambda: None, close=lambda: None),
            loop_bundle=loop_bundle,
            stop_recording=AsyncMock(return_value=None),
            active=True,
        )

        runner = HandlerCleanupRunner(handler)
        await runner.run()

        handler.stop_recording.assert_awaited_once()


class FrameTimingCalculatorTests(unittest.TestCase):

    def test_detects_dropped_frames(self):
        calculator = FrameTimingCalculator()
        logger = logging.getLogger("FrameTimingCalculatorTests")

        meta1 = {'FrameDuration': 33333, 'SensorTimestamp': 1_000_000_000}
        update1 = calculator.update(meta1, captured_frames=0, logger=logger, log_first_n=0)
        self.assertEqual(update1.hardware_frame_number, 0)
        self.assertEqual(update1.dropped_since_last, 0)

        meta2 = {'FrameDuration': 33333, 'SensorTimestamp': 1_000_000_000 + 33_333_000 * 2}
        update2 = calculator.update(meta2, captured_frames=1, logger=logger, log_first_n=0)
        self.assertEqual(update2.hardware_frame_number, 2)
        self.assertEqual(update2.dropped_since_last, 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
