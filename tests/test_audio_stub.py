from __future__ import annotations

import json
import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.audio_stub.config import AudioStubSettings
from modules.audio_stub.level_meter import LevelMeter
from modules.audio_stub.startup import PersistedSelection
from modules.audio_stub.state import AudioDeviceInfo, AudioState


MODULE_DIR = PROJECT_ROOT / "Modules" / "Audio (stub)"


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


def test_audio_stub_settings_normalize_paths() -> None:
    cfg = AudioStubSettings.from_args(_Args())
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
