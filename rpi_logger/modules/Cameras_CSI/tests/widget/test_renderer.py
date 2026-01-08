import pytest
import tkinter as tk
import asyncio

from core import (
    AppState, CameraStatus, RecordingStatus,
    CameraSettings, FrameMetrics, CameraCapabilities,
    Action, AssignCamera,
)
from ui.renderer import Renderer


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
def action_collector():
    actions = []
    async def dispatch(action: Action) -> None:
        actions.append(action)
    return actions, dispatch


class TestRendererCreation:
    def test_creates_renderer(self, tk_root, action_collector):
        actions, dispatch = action_collector
        renderer = Renderer(tk_root, dispatch)

        assert renderer.root == tk_root
        assert renderer.preview_canvas is not None

    def test_has_control_buttons(self, tk_root, action_collector):
        actions, dispatch = action_collector
        renderer = Renderer(tk_root, dispatch)

        assert renderer.assign_btn is not None
        assert renderer.record_btn is not None
        assert renderer.settings_btn is not None


class TestRendererStateRendering:
    def test_renders_idle_state(self, tk_root, action_collector):
        actions, dispatch = action_collector
        renderer = Renderer(tk_root, dispatch)

        state = AppState()
        renderer.render(state)

        assert "IDLE" in renderer.status_var.get()
        assert renderer.assign_btn["text"] == "Assign Camera"
        assert renderer.record_btn["state"] == tk.DISABLED

    def test_renders_streaming_state(self, tk_root, action_collector):
        actions, dispatch = action_collector
        renderer = Renderer(tk_root, dispatch)

        state = AppState(
            camera_status=CameraStatus.STREAMING,
            camera_id="imx708",
        )
        renderer.render(state)

        assert "STREAMING" in renderer.status_var.get()
        assert "imx708" in renderer.status_var.get()
        assert renderer.assign_btn["text"] == "Unassign"
        assert renderer.record_btn["state"] == tk.NORMAL

    def test_renders_recording_state(self, tk_root, action_collector):
        actions, dispatch = action_collector
        renderer = Renderer(tk_root, dispatch)

        state = AppState(
            camera_status=CameraStatus.STREAMING,
            recording_status=RecordingStatus.RECORDING,
            camera_id="imx708",
        )
        renderer.render(state)

        assert "RECORDING" in renderer.status_var.get()
        assert renderer.record_btn["text"] == "Stop Recording"

    def test_renders_metrics(self, tk_root, action_collector):
        actions, dispatch = action_collector
        renderer = Renderer(tk_root, dispatch)

        metrics = FrameMetrics(
            frames_captured=100,
            frames_recorded=50,
            frames_previewed=25,
            capture_fps_actual=29.5,
        )
        state = AppState(
            camera_status=CameraStatus.STREAMING,
            metrics=metrics,
            settings=CameraSettings(frame_rate=30),
        )
        renderer.render(state)

        assert "29.5" in renderer.cap_var.get()


class TestRendererFPSColorCoding:
    def test_green_when_fps_healthy(self, tk_root, action_collector):
        actions, dispatch = action_collector
        renderer = Renderer(tk_root, dispatch)

        metrics = FrameMetrics(capture_fps_actual=29.0)
        state = AppState(
            camera_status=CameraStatus.STREAMING,
            metrics=metrics,
            settings=CameraSettings(frame_rate=30),
        )
        renderer.render(state)

        assert renderer.cap_label.cget("fg") == "#4caf50"

    def test_orange_when_fps_warning(self, tk_root, action_collector):
        actions, dispatch = action_collector
        renderer = Renderer(tk_root, dispatch)

        metrics = FrameMetrics(capture_fps_actual=25.0)
        state = AppState(
            camera_status=CameraStatus.STREAMING,
            metrics=metrics,
            settings=CameraSettings(frame_rate=30),
        )
        renderer.render(state)

        assert renderer.cap_label.cget("fg") == "#ff9800"

    def test_red_when_fps_low(self, tk_root, action_collector):
        actions, dispatch = action_collector
        renderer = Renderer(tk_root, dispatch)

        metrics = FrameMetrics(capture_fps_actual=20.0)
        state = AppState(
            camera_status=CameraStatus.STREAMING,
            metrics=metrics,
            settings=CameraSettings(frame_rate=30),
        )
        renderer.render(state)

        assert renderer.cap_label.cget("fg") == "#f44336"


class TestRendererButtonStates:
    def test_buttons_disabled_when_idle(self, tk_root, action_collector):
        actions, dispatch = action_collector
        renderer = Renderer(tk_root, dispatch)

        state = AppState(camera_status=CameraStatus.IDLE)
        renderer.render(state)

        assert renderer.record_btn["state"] == tk.DISABLED
        assert renderer.settings_btn["state"] == tk.DISABLED

    def test_buttons_enabled_when_streaming(self, tk_root, action_collector):
        actions, dispatch = action_collector
        renderer = Renderer(tk_root, dispatch)

        state = AppState(camera_status=CameraStatus.STREAMING)
        renderer.render(state)

        assert renderer.record_btn["state"] == tk.NORMAL
        assert renderer.settings_btn["state"] == tk.NORMAL
