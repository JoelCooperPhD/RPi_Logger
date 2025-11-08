from __future__ import annotations

import math
import sys
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parents[1] / "Modules" / "Audio (stub)"
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from audio_mvc.config import AudioStubConfig
from audio_mvc.level_meter import LevelMeter
from audio_mvc.model import AudioDevice, AudioStubModel


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


def test_audio_stub_config_normalizes_args() -> None:
    cfg = AudioStubConfig.from_args(_Args())
    assert cfg.output_dir == MODULE_DIR / "data"
    assert cfg.session_prefix == "demo"
    assert cfg.sample_rate == 44100
    assert cfg.auto_select_new is True
    assert cfg.auto_start_recording is True
    assert math.isclose(cfg.discovery_retry, 1.5)


def test_audio_model_updates_status_and_selection() -> None:
    model = AudioStubModel()
    device = AudioDevice(device_id=1, name="Mic", channels=2, sample_rate=48_000)

    model.set_devices({1: device})
    model.select_device(device)
    payload = model.status_payload()
    assert payload["devices_selected"] == 1
    assert "device" in str(payload["status_message"]).lower()

    model.set_recording(True, 3)
    payload = model.status_payload()
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
