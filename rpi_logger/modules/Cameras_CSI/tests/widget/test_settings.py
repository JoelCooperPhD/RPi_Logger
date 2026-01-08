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

        # Default: preview_scale=0.25 (1/4), frame_rate=30, preview_divisor=4 (1/4)
        assert window.preview_scale_var.get() == "1/4"
        assert window.frame_rate_var.get() == "30"
        assert window.preview_divisor_var.get() == "1/4"
        window.destroy()

    def test_displays_custom_settings(self, tk_root, capabilities):
        custom = CameraSettings(
            resolution=(1280, 720),
            frame_rate=15,
            preview_divisor=2,
            preview_scale=0.5,
        )
        applied = []
        window = SettingsWindow(tk_root, custom, capabilities, applied.append)

        assert window.preview_scale_var.get() == "1/2"
        assert window.frame_rate_var.get() == "15"
        assert window.preview_divisor_var.get() == "1/2"
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
        window.frame_rate_var.set("15")
        window.preview_divisor_var.set("1/2")

        window.apply_button.invoke()

        assert len(applied) == 1
        settings = applied[0]
        assert settings.preview_scale == 0.5
        assert settings.frame_rate == 15
        assert settings.preview_divisor == 2
        # Resolution should be unchanged
        assert settings.resolution == default_settings.resolution

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
