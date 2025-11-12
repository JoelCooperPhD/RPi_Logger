import builtins
import importlib
import sys
from pathlib import Path

import pytest


def _reload_config_manager(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    monkeypatch.setenv("RPI_LOGGER_STATE_DIR", str(state_dir))

    import logger_core.paths as paths_module
    paths_module = importlib.reload(paths_module)
    sys.modules['logger_core.paths'] = paths_module

    import logger_core.config_manager as config_module
    config_module = importlib.reload(config_module)
    sys.modules['logger_core.config_manager'] = config_module
    return config_module


@pytest.fixture()
def config_env(tmp_path, monkeypatch):
    module = _reload_config_manager(tmp_path, monkeypatch)
    manager = module.ConfigManager()
    return manager


def _force_permission_error(config_path: Path, monkeypatch):
    original_open = builtins.open

    def fake_open(path, mode='r', *args, **kwargs):
        if Path(path) == config_path and 'w' in mode and 'r' not in mode:
            raise PermissionError("mock permission denied")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr('builtins.open', fake_open)
    return original_open


def test_write_config_falls_back_to_override(tmp_path, monkeypatch, config_env):
    config_path = tmp_path / "module_config.txt"
    config_path.write_text("enabled = true\n", encoding='utf-8')

    original_open = _force_permission_error(config_path, monkeypatch)

    result = config_env.write_config(config_path, {'enabled': False, 'window_x': 320})
    assert result is True

    override_path = config_env._resolve_override_path(config_path)
    assert override_path.exists()

    # Base file remains unchanged because write was redirected to override
    assert "enabled = true" in config_path.read_text(encoding='utf-8')

    # Reading config merges overrides
    merged = config_env.read_config(config_path)
    assert merged['enabled'] == 'false'
    assert merged['window_x'] == '320'

    # Restore builtins.open for subsequent tests
    monkeypatch.setattr('builtins.open', original_open, raising=False)


def test_read_config_includes_override_values(tmp_path, monkeypatch, config_env):
    config_path = tmp_path / "module_config.txt"
    config_path.write_text("enabled = true\nwindow_x = 10\n", encoding='utf-8')

    override_path = config_env._resolve_override_path(config_path)
    override_path.parent.mkdir(parents=True, exist_ok=True)
    override_path.write_text("enabled = false\nwindow_x = 99\nextra = custom\n", encoding='utf-8')

    merged = config_env.read_config(config_path)
    assert merged['enabled'] == 'false'
    assert merged['window_x'] == '99'
    assert merged['extra'] == 'custom'


def test_successful_write_removes_override(tmp_path, monkeypatch, config_env):
    config_path = tmp_path / "module_config.txt"
    config_path.write_text("enabled = true\n", encoding='utf-8')

    original_open = _force_permission_error(config_path, monkeypatch)
    assert config_env.write_config(config_path, {'enabled': False}) is True

    override_path = config_env._resolve_override_path(config_path)
    assert override_path.exists()

    # Allow writes again and ensure override is removed after sync write
    monkeypatch.setattr('builtins.open', original_open, raising=False)
    assert config_env.write_config(config_path, {'enabled': True}) is True
    assert not override_path.exists()
