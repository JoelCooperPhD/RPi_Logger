import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STUB_ROOT = PROJECT_ROOT / "Modules" / "stub (codex)"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if STUB_ROOT.exists() and str(STUB_ROOT) not in sys.path:
    sys.path.insert(0, str(STUB_ROOT))


def _ensure_cv2_stub() -> None:
    """Provide a minimal cv2 module for environments without OpenCV."""
    if "cv2" in sys.modules:
        return
    cv2_stub = ModuleType("cv2")
    cv2_stub.COLOR_BGR2RGB = 0
    cv2_stub.LINE_AA = 0
    cv2_stub.FONT_HERSHEY_SIMPLEX = 0
    cv2_stub.cvtColor = lambda frame, flag=0: frame  # pragma: no cover - helper stub
    sys.modules["cv2"] = cv2_stub


_ensure_cv2_stub()

if "async_tkinter_loop" not in sys.modules:
    async_tk_stub = ModuleType("async_tkinter_loop")

    def _passthrough(handler):  # pragma: no cover - helper stub
        return handler

    async_tk_stub.async_handler = _passthrough
    sys.modules["async_tkinter_loop"] = async_tk_stub

from Modules.CamerasStub.controller.runtime import CameraStubController


class SensorIntervalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = CameraStubController.__new__(CameraStubController)
        self.runtime._state = SimpleNamespace(
            save_frame_interval=0.0,
            preview_frame_interval=1.0 / 15.0,
        )

    def test_current_sensor_interval_prefers_recording_limit(self) -> None:
        self.runtime.save_frame_interval = 1.0 / 30.0
        self.runtime.preview_frame_interval = 1.0 / 15.0
        self.assertAlmostEqual(self.runtime._current_sensor_interval(), 1.0 / 30.0)

    def test_unlimited_recording_leaves_sensor_unclamped(self) -> None:
        self.runtime.save_frame_interval = 0.0
        self.runtime.preview_frame_interval = 1.0 / 15.0
        self.assertIsNone(self.runtime._current_sensor_interval())


if __name__ == "__main__":  # pragma: no cover - manual test hook
    unittest.main()
