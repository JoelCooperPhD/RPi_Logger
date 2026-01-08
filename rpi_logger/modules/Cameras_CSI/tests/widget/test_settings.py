import pytest
import tkinter as tk

from core import CameraSettings, CameraCapabilities
from ui.widgets.settings_window import SettingsWindow


@pytest.fixture
def tk_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    try:
        root.destroy()
    except tk.TclError:
        pass


@pytest.fixture
def default_settings():
    return CameraSettings()


@pytest.fixture
def capabilities():
    return CameraCapabilities(camera_id="imx708")


class TestSettingsWindowCreation:
    def test_creates_window(self, tk_root, default_settings, capabilities):
        applied = []
        window = SettingsWindow(tk_root, default_settings, capabilities, applied.append)

        assert window.winfo_exists()
        window.destroy()

    def test_displays_current_settings(self, tk_root, default_settings, capabilities):
        applied = []
        window = SettingsWindow(tk_root, default_settings, capabilities, applied.append)

        # Default: preview_scale=0.25 (1/4), preview_fps=10, record_fps=5
        assert window.preview_scale_var.get() == "1/4"
        assert window.preview_fps_var.get() == "10"
        assert window.record_fps_var.get() == "5"
        window.destroy()

    def test_displays_custom_settings(self, tk_root, capabilities):
        custom = CameraSettings(
            resolution=(1280, 720),
            capture_fps=60,
            preview_fps=5,
            preview_scale=0.5,
            record_fps=15,
        )
        applied = []
        window = SettingsWindow(tk_root, custom, capabilities, applied.append)

        assert window.preview_scale_var.get() == "1/2"
        assert window.preview_fps_var.get() == "5"
        assert window.record_fps_var.get() == "15"
        window.destroy()

    def test_displays_eighth_scale(self, tk_root, capabilities):
        custom = CameraSettings(preview_scale=0.125)
        applied = []
        window = SettingsWindow(tk_root, custom, capabilities, applied.append)

        assert window.preview_scale_var.get() == "1/8"
        window.destroy()


class TestSettingsWindowInteraction:
    def test_apply_button_calls_callback(self, tk_root, default_settings, capabilities):
        applied = []
        window = SettingsWindow(tk_root, default_settings, capabilities, applied.append)

        window.apply_button.invoke()

        assert len(applied) == 1
        assert isinstance(applied[0], CameraSettings)

    def test_apply_returns_modified_settings(self, tk_root, default_settings, capabilities):
        applied = []
        window = SettingsWindow(tk_root, default_settings, capabilities, applied.append)

        window.preview_scale_var.set("1/2")
        window.preview_fps_var.set("5")
        window.record_fps_var.set("15")

        window.apply_button.invoke()

        assert len(applied) == 1
        settings = applied[0]
        assert settings.preview_scale == 0.5
        assert settings.preview_fps == 5
        assert settings.record_fps == 15
        # Resolution and capture_fps should be unchanged
        assert settings.resolution == default_settings.resolution
        assert settings.capture_fps == default_settings.capture_fps

    def test_cancel_button_closes_window(self, tk_root, default_settings, capabilities):
        applied = []
        window = SettingsWindow(tk_root, default_settings, capabilities, applied.append)

        window.cancel_button.invoke()

        assert len(applied) == 0

    def test_apply_closes_window(self, tk_root, default_settings, capabilities):
        applied = []
        window = SettingsWindow(tk_root, default_settings, capabilities, applied.append)

        window.apply_button.invoke()
        tk_root.update()

        assert len(applied) == 1


class TestSettingsWindowWithoutCapabilities:
    def test_works_without_capabilities(self, tk_root, default_settings):
        applied = []
        window = SettingsWindow(tk_root, default_settings, None, applied.append)

        assert window.winfo_exists()
        window.apply_button.invoke()

        assert len(applied) == 1
        window.destroy()
