"""Comprehensive tests for CSICameraView GUI wiring.

Tests user interactions: menu clicks, settings changes, state rendering.
"""

import pytest
import asyncio
import tkinter as tk
from pathlib import Path

import sys
_module_dir = Path(__file__).resolve().parent.parent.parent
if str(_module_dir) not in sys.path:
    sys.path.insert(0, str(_module_dir))

from core import (
    AppState, CameraStatus, RecordingStatus,
    CameraSettings, CameraCapabilities, FrameMetrics,
    Action, ApplySettings,
)
from ui.view import CSICameraView


class MockStubView:
    """Mock stub_view that simulates StubCodexSupervisor's view interface."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.view_menu = tk.Menu(root)
        self._stub_frame = None
        self._io_frame = None

    def build_stub_content(self, builder):
        self._stub_frame = tk.Frame(self.root)
        self._stub_frame.pack(fill=tk.BOTH, expand=True)
        builder(self._stub_frame)

    def build_io_stub_content(self, builder):
        self._io_frame = tk.Frame(self.root)
        self._io_frame.pack(fill=tk.X)
        builder(self._io_frame)

    def finalize_view_menu(self):
        pass

    def finalize_file_menu(self):
        pass


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
def mock_stub_view(tk_root):
    return MockStubView(tk_root)


@pytest.fixture
def action_collector():
    actions = []
    async def dispatch(action: Action) -> None:
        actions.append(action)
    return actions, dispatch


@pytest.fixture
def view_with_dispatch(mock_stub_view, action_collector):
    actions, dispatch = action_collector
    view = CSICameraView(mock_stub_view)
    view.attach()
    view.bind_dispatch(dispatch)
    return view, actions


# =============================================================================
# VIEW ATTACHMENT TESTS
# =============================================================================

class TestViewAttachment:
    def test_attaches_to_stub_view(self, mock_stub_view):
        view = CSICameraView(mock_stub_view)
        view.attach()
        assert view._has_ui is True

    def test_creates_canvas_widget(self, mock_stub_view):
        view = CSICameraView(mock_stub_view)
        view.attach()
        assert view._canvas is not None
        assert view._canvas.winfo_class() == "Canvas"

    def test_creates_metrics_fields(self, mock_stub_view):
        view = CSICameraView(mock_stub_view)
        view.attach()
        assert "cap_tgt" in view._metrics_fields
        assert "rec_tgt" in view._metrics_fields
        assert "disp_tgt" in view._metrics_fields

    def test_adds_settings_to_view_menu(self, mock_stub_view):
        view = CSICameraView(mock_stub_view)
        view.attach()
        # Menu should have at least one item
        assert mock_stub_view.view_menu.index(tk.END) >= 0

    def test_attach_without_stub_view_does_not_crash(self):
        view = CSICameraView(None)
        view.attach()
        assert view._has_ui is False


# =============================================================================
# DISPATCH BINDING TESTS
# =============================================================================

class TestDispatchBinding:
    def test_bind_dispatch_stores_callable(self, view_with_dispatch):
        view, actions = view_with_dispatch
        assert view._dispatch is not None

    @pytest.mark.asyncio
    async def test_dispatch_is_called_on_settings_apply(self, view_with_dispatch, tk_root):
        view, actions = view_with_dispatch
        view._current_state = AppState(camera_status=CameraStatus.STREAMING)

        view._on_settings_click()
        view._settings_window.apply_button.invoke()
        tk_root.update()
        await asyncio.sleep(0.1)

        assert len(actions) == 1
        assert isinstance(actions[0], ApplySettings)


# =============================================================================
# SETTINGS WINDOW TESTS
# =============================================================================

class TestSettingsWindow:
    def test_opens_settings_window(self, view_with_dispatch):
        view, actions = view_with_dispatch
        view._current_state = AppState(camera_status=CameraStatus.STREAMING)

        view._on_settings_click()

        assert view._settings_window is not None
        view._settings_window.destroy()

    def test_settings_window_shows_current_preview_scale(self, view_with_dispatch):
        view, actions = view_with_dispatch
        view._current_state = AppState(
            settings=CameraSettings(preview_scale=0.5)
        )

        view._on_settings_click()

        assert view._settings_window.preview_scale_var.get() == "1/2"
        view._settings_window.destroy()

    def test_settings_window_shows_current_frame_rate(self, view_with_dispatch):
        view, actions = view_with_dispatch
        view._current_state = AppState(
            settings=CameraSettings(frame_rate=15)
        )

        view._on_settings_click()

        assert view._settings_window.frame_rate_var.get() == "15"
        view._settings_window.destroy()

    def test_settings_window_shows_current_preview_divisor(self, view_with_dispatch):
        view, actions = view_with_dispatch
        view._current_state = AppState(
            settings=CameraSettings(preview_divisor=2)
        )

        view._on_settings_click()

        assert view._settings_window.preview_divisor_var.get() == "1/2"
        view._settings_window.destroy()

    def test_settings_cancel_does_not_dispatch(self, view_with_dispatch, tk_root):
        view, actions = view_with_dispatch
        view._current_state = AppState()

        view._on_settings_click()
        view._settings_window.cancel_button.invoke()
        tk_root.update()

        assert len(actions) == 0

    def test_reopening_settings_lifts_existing(self, view_with_dispatch):
        view, actions = view_with_dispatch
        view._current_state = AppState()

        view._on_settings_click()
        first_window = view._settings_window

        view._on_settings_click()

        # Should be same window, not a new one
        assert view._settings_window is first_window
        view._settings_window.destroy()


class TestSettingsApply:
    @pytest.mark.asyncio
    async def test_apply_preview_scale_change(self, view_with_dispatch, tk_root):
        view, actions = view_with_dispatch
        view._current_state = AppState(settings=CameraSettings(preview_scale=0.25))

        view._on_settings_click()
        view._settings_window.preview_scale_var.set("1/2")
        view._settings_window.apply_button.invoke()
        tk_root.update()
        await asyncio.sleep(0.1)

        assert len(actions) == 1
        assert actions[0].settings.preview_scale == 0.5

    @pytest.mark.asyncio
    async def test_apply_frame_rate_change(self, view_with_dispatch, tk_root):
        view, actions = view_with_dispatch
        view._current_state = AppState(settings=CameraSettings(frame_rate=30))

        view._on_settings_click()
        view._settings_window.frame_rate_var.set("15")
        view._settings_window.apply_button.invoke()
        tk_root.update()
        await asyncio.sleep(0.1)

        assert len(actions) == 1
        assert actions[0].settings.frame_rate == 15

    @pytest.mark.asyncio
    async def test_apply_preview_divisor_change(self, view_with_dispatch, tk_root):
        view, actions = view_with_dispatch
        view._current_state = AppState(settings=CameraSettings(preview_divisor=4))

        view._on_settings_click()
        view._settings_window.preview_divisor_var.set("1/2")
        view._settings_window.apply_button.invoke()
        tk_root.update()
        await asyncio.sleep(0.1)

        assert len(actions) == 1
        assert actions[0].settings.preview_divisor == 2

    @pytest.mark.asyncio
    async def test_apply_all_settings_at_once(self, view_with_dispatch, tk_root):
        view, actions = view_with_dispatch
        view._current_state = AppState()

        view._on_settings_click()
        view._settings_window.preview_scale_var.set("1/8")
        view._settings_window.frame_rate_var.set("30")
        view._settings_window.preview_divisor_var.set("1/8")
        view._settings_window.apply_button.invoke()
        tk_root.update()
        await asyncio.sleep(0.1)

        assert len(actions) == 1
        s = actions[0].settings
        assert s.preview_scale == 0.125
        assert s.frame_rate == 30
        assert s.preview_divisor == 8
        # Resolution should be unchanged from defaults (IMX296 native)
        assert s.resolution == (1456, 1088)


# =============================================================================
# STATE RENDERING TESTS
# =============================================================================

class TestRenderMetrics:
    def test_render_stores_current_state(self, view_with_dispatch):
        view, actions = view_with_dispatch
        state = AppState()
        view.render(state)
        assert view._current_state is state

    def test_render_capture_fps(self, view_with_dispatch, tk_root):
        view, actions = view_with_dispatch
        state = AppState(
            camera_status=CameraStatus.STREAMING,
            metrics=FrameMetrics(capture_fps_actual=29.5),
            settings=CameraSettings(frame_rate=30),
        )
        view.render(state)
        tk_root.update()

        cap_text = view._metrics_fields["cap_tgt"].get()
        assert "29.5" in cap_text

    def test_render_recording_metrics_when_recording(self, view_with_dispatch, tk_root):
        view, actions = view_with_dispatch
        state = AppState(
            camera_status=CameraStatus.STREAMING,
            recording_status=RecordingStatus.RECORDING,
            metrics=FrameMetrics(capture_fps_actual=30.0),
            settings=CameraSettings(frame_rate=5),
        )
        view.render(state)
        tk_root.update()

        rec_text = view._metrics_fields["rec_tgt"].get()
        assert "--" not in rec_text  # Should show actual values

    def test_render_recording_metrics_when_stopped(self, view_with_dispatch, tk_root):
        view, actions = view_with_dispatch
        state = AppState(
            camera_status=CameraStatus.STREAMING,
            recording_status=RecordingStatus.STOPPED,
        )
        view.render(state)
        tk_root.update()

        rec_text = view._metrics_fields["rec_tgt"].get()
        assert "--" in rec_text

    def test_render_preview_fps(self, view_with_dispatch, tk_root):
        view, actions = view_with_dispatch
        state = AppState(
            camera_status=CameraStatus.STREAMING,
            metrics=FrameMetrics(capture_fps_actual=30.0),
            settings=CameraSettings(frame_rate=30, preview_divisor=4),  # preview_fps = 30/4 = 7
        )
        view.render(state)
        tk_root.update()

        disp_text = view._metrics_fields["disp_tgt"].get()
        assert "7" in disp_text  # Target should show 7 (30/4)


class TestRenderWithoutUI:
    def test_render_without_attachment(self):
        view = CSICameraView(None)
        state = AppState()
        # Should not raise
        view.render(state)

    def test_push_frame_without_attachment(self):
        view = CSICameraView(None)
        # Should not raise
        view.push_frame(b"test")


# =============================================================================
# FRAME RENDERING TESTS
# =============================================================================

class TestFrameRendering:
    def test_push_frame_increments_counter(self, view_with_dispatch):
        view, actions = view_with_dispatch
        initial = view._frame_count
        view.push_frame(None)
        assert view._frame_count == initial + 1

    def test_push_frame_with_valid_ppm(self, view_with_dispatch, tk_root):
        view, actions = view_with_dispatch
        # Minimal valid PPM: 2x2 RGB image
        ppm = b"P6\n2 2\n255\n" + b"\xff\x00\x00" * 4
        view.push_frame(ppm)
        tk_root.update()

        assert view._photo is not None

    def test_push_frame_creates_canvas_image(self, view_with_dispatch, tk_root):
        view, actions = view_with_dispatch
        ppm = b"P6\n2 2\n255\n" + b"\xff\x00\x00" * 4
        view.push_frame(ppm)
        tk_root.update()

        assert view._canvas_image_id is not None

    def test_push_multiple_frames(self, view_with_dispatch, tk_root):
        view, actions = view_with_dispatch
        ppm = b"P6\n2 2\n255\n" + b"\xff\x00\x00" * 4

        for i in range(5):
            view.push_frame(ppm)
            tk_root.update()

        assert view._frame_count == 5

    def test_push_frame_with_none_data(self, view_with_dispatch, tk_root):
        view, actions = view_with_dispatch
        # Should not crash
        view.push_frame(None)
        tk_root.update()


# =============================================================================
# END-TO-END WORKFLOW TESTS
# =============================================================================

class TestEndToEndWorkflows:
    @pytest.mark.asyncio
    async def test_settings_change_workflow(self, view_with_dispatch, tk_root):
        """User opens settings, changes values, applies - action is dispatched."""
        view, actions = view_with_dispatch

        # Initial state
        view._current_state = AppState(
            camera_status=CameraStatus.STREAMING,
            settings=CameraSettings(
                resolution=(1920, 1080),
                frame_rate=30,
                preview_divisor=4,
                preview_scale=0.25,
            ),
        )

        # User opens settings
        view._on_settings_click()
        assert view._settings_window is not None

        # User changes preview scale and frame rate
        view._settings_window.preview_scale_var.set("1/2")
        view._settings_window.frame_rate_var.set("15")

        # User clicks Apply
        view._settings_window.apply_button.invoke()
        tk_root.update()
        await asyncio.sleep(0.1)

        # Verify dispatch
        assert len(actions) == 1
        assert isinstance(actions[0], ApplySettings)
        assert actions[0].settings.preview_scale == 0.5
        assert actions[0].settings.frame_rate == 15
        # Resolution should be unchanged (not user-configurable)
        assert actions[0].settings.resolution == (1920, 1080)

        # Settings window should be closed
        assert view._settings_window is None

    def test_state_updates_metrics_display(self, view_with_dispatch, tk_root):
        """State change updates metrics display immediately."""
        view, actions = view_with_dispatch

        # Initial render
        view.render(AppState(
            camera_status=CameraStatus.STREAMING,
            metrics=FrameMetrics(capture_fps_actual=10.0),
        ))
        tk_root.update()
        initial_cap = view._metrics_fields["cap_tgt"].get()

        # State update
        view.render(AppState(
            camera_status=CameraStatus.STREAMING,
            metrics=FrameMetrics(capture_fps_actual=29.5),
        ))
        tk_root.update()
        updated_cap = view._metrics_fields["cap_tgt"].get()

        assert "10.0" in initial_cap
        assert "29.5" in updated_cap

    def test_recording_state_change_updates_metrics(self, view_with_dispatch, tk_root):
        """Recording state change updates rec metrics display."""
        view, actions = view_with_dispatch

        # Not recording
        view.render(AppState(
            camera_status=CameraStatus.STREAMING,
            recording_status=RecordingStatus.STOPPED,
        ))
        tk_root.update()
        stopped_rec = view._metrics_fields["rec_tgt"].get()

        # Start recording
        view.render(AppState(
            camera_status=CameraStatus.STREAMING,
            recording_status=RecordingStatus.RECORDING,
            metrics=FrameMetrics(capture_fps_actual=30.0),
            settings=CameraSettings(frame_rate=5),
        ))
        tk_root.update()
        recording_rec = view._metrics_fields["rec_tgt"].get()

        assert "--" in stopped_rec
        assert "--" not in recording_rec
