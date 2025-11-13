import logging
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STUB_ROOT = PROJECT_ROOT / "Modules" / "stub (codex)"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if STUB_ROOT.exists() and str(STUB_ROOT) not in sys.path:
    sys.path.insert(0, str(STUB_ROOT))


def _ensure_cv2_stub() -> None:
    """Provide a minimal cv2 stub so tests do not depend on OpenCV."""

    cv2_module = sys.modules.get("cv2")

    if cv2_module is None:
        cv2_module = ModuleType("cv2")

        class _VideoWriter:  # pragma: no cover - helper stub
            def __init__(self, *args, **kwargs):
                self._opened = True

            def isOpened(self):
                return self._opened

            def write(self, frame):
                return None

            def release(self):
                self._opened = False

        cv2_module.VideoWriter = _VideoWriter
        cv2_module.VideoWriter_fourcc = staticmethod(lambda *args: 0)
        cv2_module.putText = lambda *args, **kwargs: None  # pragma: no cover - helper stub
        cv2_module.cvtColor = lambda frame, flag=0: frame  # pragma: no cover - helper stub
        sys.modules["cv2"] = cv2_module

    fallbacks = {
        "FONT_HERSHEY_SIMPLEX": 0,
        "LINE_AA": 0,
        "COLOR_RGB2BGR": 0,
        "COLOR_BGR2RGB": 0,
        "COLOR_YUV2RGB_I420": 0,
    }

    for attr, default in fallbacks.items():
        if not hasattr(cv2_module, attr):
            setattr(cv2_module, attr, default)


_ensure_cv2_stub()

if "async_tkinter_loop" not in sys.modules:
    async_tk_stub = ModuleType("async_tkinter_loop")

    def _passthrough(handler):  # pragma: no cover - helper stub
        return handler

    async_tk_stub.async_handler = _passthrough
    sys.modules["async_tkinter_loop"] = async_tk_stub

from Modules.Cameras.csv_logger import CameraCSVLogger
from Modules.Cameras.storage.pipeline import CameraStoragePipeline


class PrepareImageOverlayTests(unittest.TestCase):
    def test_prepare_image_with_overlay_invokes_burner(self) -> None:
        pipeline = CameraStoragePipeline.__new__(CameraStoragePipeline)
        pipeline.camera_index = 0
        calls = {}

        def fake_burn(frame, frame_number, cfg):
            calls["frame_number"] = frame_number
            calls["cfg"] = cfg
            calls["shape"] = getattr(frame, "shape", None)

        pipeline._burn_frame_number = fake_burn  # type: ignore[attr-defined]

        image = Image.new("RGB", (12, 8), color=(10, 20, 30))
        overlay_cfg = {"text_color_r": 255, "text_color_g": 255, "text_color_b": 255}

        result = pipeline._prepare_image_with_overlay(image, 42, overlay_cfg)

        self.assertEqual(result.size, (12, 8))
        self.assertEqual(result.mode, "RGB")
        self.assertEqual(calls["frame_number"], 42)
        self.assertEqual(calls["cfg"], overlay_cfg)
        self.assertIsNotNone(calls["shape"])


class SaveImageOverlayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addAsyncCleanup(self._tmp.cleanup)
        self.save_dir = Path(self._tmp.name)

    async def test_save_image_applies_overlay_before_writing(self):
        pipeline = CameraStoragePipeline.__new__(CameraStoragePipeline)
        pipeline.camera_index = 0
        pipeline.save_dir = self.save_dir
        pipeline.save_format = "jpeg"
        pipeline.save_quality = 85
        pipeline.overlay_config = {"text_color_r": 255, "text_color_g": 255, "text_color_b": 255}
        pipeline._logger = logging.getLogger("CameraStoragePipelineTests")
        pipeline.camera_slug = "cam0"

        calls = []

        def fake_prepare(image, frame_number, cfg):
            calls.append((frame_number, cfg))
            return image

        pipeline._prepare_image_with_overlay = fake_prepare  # type: ignore[attr-defined]

        image = Image.new("RGB", (6, 6), color=(0, 0, 0))
        timestamp = 1_700_000_000.0

        result = await pipeline._save_image(image, 7, timestamp)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], 7)
        self.assertEqual(calls[0][1], pipeline.overlay_config)
        self.assertIsNotNone(result)
        self.assertTrue(result.exists())


class CSVLoggerTimestampTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addAsyncCleanup(self._tmp.cleanup)
        self.csv_path = Path(self._tmp.name) / "cam0_frame_timing.csv"

    async def test_log_frame_uses_capture_timestamp(self):
        logger = CameraCSVLogger(camera_id=0, csv_path=self.csv_path)
        await logger.start()

        capture_ts = 1_700_000_000.123456
        logger.log_frame(
            5,
            frame_time_unix=capture_ts,
            sensor_timestamp_ns=123456789,
            dropped_since_last=0,
        )

        await logger.stop()

        lines = self.csv_path.read_text().strip().splitlines()
        self.assertGreaterEqual(len(lines), 2)
        fields = lines[1].split(',')
        self.assertEqual(int(fields[1]), 5)
        self.assertAlmostEqual(float(fields[2]), capture_ts, places=6)


class CameraStorageFilenameTests(unittest.TestCase):
    def test_image_filename_prefers_provided_slug(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = CameraStoragePipeline(
                camera_index=1,
                save_dir=Path(tmp),
                camera_slug="right_cam",
            )

            name = pipeline._image_filename(3, 1_700_000_000.0)

            self.assertTrue(name.startswith("right_cam_frame000003_"))

    def test_slug_falls_back_to_camera_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = CameraStoragePipeline(
                camera_index=2,
                save_dir=Path(tmp),
            )

            name = pipeline._image_filename(5, 1_700_000_000.0)

            self.assertTrue(name.startswith("cam2_frame000005_"))


if __name__ == "__main__":  # pragma: no cover - convenience hook
    unittest.main()
