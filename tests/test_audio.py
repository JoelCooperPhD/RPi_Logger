from __future__ import annotations

import asyncio
import json
import logging
import math
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if "vmc" not in sys.modules:
    import types

    class _StubRuntimeContext:
        def __init__(self, *args, **kwargs) -> None:  # pragma: no cover - test shim
            pass

    class _StubModuleRuntime:
        async def start(self):  # pragma: no cover - test shim
            raise NotImplementedError

    class _StubBackgroundTaskManager:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def create(self, coro, name=None):
            return asyncio.create_task(coro)

        def add(self, task):
            return task

        async def shutdown(self, **_):
            return True

    class _StubShutdownGuard:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def start(self):
            return None

        async def cancel(self):
            return None

    vmc_module = types.ModuleType("vmc")
    vmc_runtime = types.ModuleType("vmc.runtime")
    vmc_runtime.RuntimeContext = _StubRuntimeContext
    vmc_helpers = types.ModuleType("vmc.runtime_helpers")
    vmc_helpers.BackgroundTaskManager = _StubBackgroundTaskManager
    vmc_helpers.ShutdownGuard = _StubShutdownGuard
    vmc_module.ModuleRuntime = _StubModuleRuntime
    vmc_module.RuntimeContext = _StubRuntimeContext
    vmc_module.runtime = vmc_runtime
    vmc_module.runtime_helpers = vmc_helpers
    sys.modules["vmc"] = vmc_module
    sys.modules["vmc.runtime"] = vmc_runtime
    sys.modules["vmc.runtime_helpers"] = vmc_helpers

from modules.audio.config import AudioSettings
from modules.audio.level_meter import LevelMeter
from modules.audio.services.recorder import RecorderService
from modules.audio.startup import PersistedSelection
from modules.audio.state import AudioDeviceInfo, AudioState
from modules.audio.app import RecordingManager


MODULE_DIR = PROJECT_ROOT / "Modules" / "Audio"


class _Args:
    def __init__(self) -> None:
        self.mode = "gui"
        self.output_dir = MODULE_DIR / "data"
        self.session_prefix = "demo"
        self.log_level = "info"
        self.log_file = None
        self.enable_commands = True
        self.window_geometry = "800x600"
        self.sample_rate = 44100
        self.discovery_timeout = 2.5
        self.discovery_retry = 1.5
        self.auto_select_new = True
        self.auto_start_recording = True
        self.console_output = True
        self.meter_refresh_interval = 0.1
        self.device_scan_interval = 4.0
        self.recorder_start_timeout = 2.0
        self.recorder_stop_timeout = 2.0
        self.shutdown_timeout = 10.0


def test_audio_settings_normalize_paths() -> None:
    cfg = AudioSettings.from_args(_Args())
    assert cfg.output_dir == MODULE_DIR / "data"
    assert cfg.session_prefix == "demo"
    assert cfg.sample_rate == 44100
    assert cfg.auto_select_new is True
    assert cfg.auto_start_recording is True
    assert cfg.recorder_start_timeout == 2.0
    assert math.isclose(cfg.discovery_retry, 1.5)


def test_audio_state_tracks_selection_and_status() -> None:
    state = AudioState()
    device = AudioDeviceInfo(device_id=1, name="Mic", channels=2, sample_rate=48_000)

    state.set_devices({1: device})
    state.select_device(device)
    payload = state.status_payload()
    assert payload["devices_selected"] == 1
    assert "device" in str(payload["status_message"]).lower()

    state.set_recording(True, 3)
    payload = state.status_payload()
    assert payload["recording"] is True
    assert "trial 3" in str(payload["status_message"]).lower()


def test_level_meter_tracks_peak_levels() -> None:
    meter = LevelMeter()
    meter.add_samples([0.0, 0.5, 1.0], timestamp=0.0)
    rms_db, peak_db = meter.get_db_levels()
    assert peak_db <= 0.0
    assert rms_db <= peak_db
    meter.clear_dirty()
    assert meter.dirty is False


def test_persisted_selection_parses_json_payload() -> None:
    payload = '[{"id":2,"name":"USB Mic"},{"name":"Line In"}]'
    selection = PersistedSelection.from_raw(payload)
    assert selection.device_ids == (2,)
    assert "Line In" in selection.device_names
    assert json.loads(selection.serialized)[0]["id"] == 2


def test_persisted_selection_parses_delimited_string() -> None:
    selection = PersistedSelection.from_raw("4, Desk Mic")
    assert selection.device_ids == (4,)
    assert selection.device_names == ("Desk Mic",)


def test_recorder_service_prefers_device_sample_rate() -> None:
    service = RecorderService(logging.getLogger("test"), sample_rate=48000, start_timeout=1.0, stop_timeout=1.0)
    device = AudioDeviceInfo(device_id=1, name="Mic", channels=1, sample_rate=44100.0)
    assert service._resolve_sample_rate(device) == 44100


def test_recorder_service_falls_back_to_default_rate() -> None:
    service = RecorderService(logging.getLogger("test"), sample_rate=32000, start_timeout=1.0, stop_timeout=1.0)
    device = AudioDeviceInfo(device_id=2, name="Line", channels=1, sample_rate=0)
    assert service._resolve_sample_rate(device) == 32000


class _DummyRecorderService:
    def __init__(self) -> None:
        self.calls: int = 0

    async def begin_recording(self, device_ids, session_dir, trial_number):
        self.calls += 1
        await asyncio.sleep(0.01)
        return len(device_ids)

    async def finish_recording(self):
        return []


class _DummySessionService:
    def __init__(self, path: Path) -> None:
        self.path = path

    async def ensure_session_dir(self, current):
        return self.path


class _DummyBridge:
    def set_session_dir(self, path):
        return None

    def set_recording(self, active, trial):
        return None


def test_recording_manager_prevents_duplicate_start(tmp_path: Path) -> None:
    async def _exercise() -> None:
        state = AudioState()
        recorder_service = _DummyRecorderService()
        session_service = _DummySessionService(tmp_path)
        bridge = _DummyBridge()
        logger = logging.getLogger("test.recording_manager")

        manager = RecordingManager(
            state,
            recorder_service,
            session_service,
            bridge,
            logger,
            lambda *_: None,
        )

        async def _start():
            return await manager.start([1], trial_number=1)

        results = await asyncio.gather(_start(), _start())
        assert results.count(True) == 1
        assert recorder_service.calls == 1

    asyncio.run(_exercise())
