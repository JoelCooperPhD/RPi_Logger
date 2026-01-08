import pytest
import asyncio
from pathlib import Path

from core import (
    AppState, CameraStatus, RecordingStatus, CameraSettings, CameraCapabilities,
    Store, create_store,
    Action, AssignCamera, CameraAssigned, CameraError, UnassignCamera,
    StartRecording, StopRecording, RecordingStarted, RecordingStopped,
    ApplySettings, Shutdown,
    Effect, ProbeCamera, OpenCamera, StartCapture,
)


class MockEffectExecutor:
    def __init__(self):
        self.executed_effects: list[Effect] = []
        self.auto_dispatch: dict[type, Action] = {}

    def set_auto_dispatch(self, effect_type: type, action: Action) -> None:
        self.auto_dispatch[effect_type] = action

    async def __call__(self, effect: Effect, dispatch) -> None:
        self.executed_effects.append(effect)
        effect_type = type(effect)
        if effect_type in self.auto_dispatch:
            await dispatch(self.auto_dispatch[effect_type])


class TestStoreBasics:
    def test_initial_state(self):
        store = create_store()
        assert store.state.camera_status == CameraStatus.IDLE
        assert store.state.recording_status == RecordingStatus.STOPPED

    def test_subscribe_called_on_subscribe(self):
        store = create_store()
        states = []
        store.subscribe(lambda s: states.append(s))
        assert len(states) == 1
        assert states[0].camera_status == CameraStatus.IDLE

    @pytest.mark.asyncio
    async def test_dispatch_updates_state(self):
        store = create_store()
        states = []
        store.subscribe(lambda s: states.append(s))

        await store.dispatch(AssignCamera(0))

        assert len(states) == 2
        assert states[1].camera_status == CameraStatus.ASSIGNING

    @pytest.mark.asyncio
    async def test_dispatch_executes_effects(self):
        store = create_store()
        executor = MockEffectExecutor()
        store.set_effect_handler(executor)

        await store.dispatch(AssignCamera(0))

        assert len(executor.executed_effects) == 1
        assert isinstance(executor.executed_effects[0], ProbeCamera)


class TestStoreWithMockExecutor:
    @pytest.mark.asyncio
    async def test_camera_assignment_flow(self):
        store = create_store()
        executor = MockEffectExecutor()
        caps = CameraCapabilities(camera_id="imx708")
        executor.set_auto_dispatch(ProbeCamera, CameraAssigned("imx708", 0, caps))
        store.set_effect_handler(executor)

        states = []
        store.subscribe(lambda s: states.append(s))

        await store.dispatch(AssignCamera(0))

        assert store.state.camera_status == CameraStatus.STREAMING
        assert store.state.camera_id == "imx708"
        assert any(isinstance(e, OpenCamera) for e in executor.executed_effects)
        assert any(isinstance(e, StartCapture) for e in executor.executed_effects)

    @pytest.mark.asyncio
    async def test_camera_error_flow(self):
        store = create_store()
        executor = MockEffectExecutor()
        executor.set_auto_dispatch(ProbeCamera, CameraError("Camera not found"))
        store.set_effect_handler(executor)

        await store.dispatch(AssignCamera(0))

        assert store.state.camera_status == CameraStatus.ERROR
        assert store.state.error_message == "Camera not found"

    @pytest.mark.asyncio
    async def test_full_recording_workflow(self):
        store = create_store()
        executor = MockEffectExecutor()
        caps = CameraCapabilities(camera_id="imx708")

        executor.set_auto_dispatch(ProbeCamera, CameraAssigned("imx708", 0, caps))
        store.set_effect_handler(executor)

        await store.dispatch(AssignCamera(0))
        assert store.state.camera_status == CameraStatus.STREAMING

        await store.dispatch(StartRecording(Path("/data"), 1))
        assert store.state.recording_status == RecordingStatus.STARTING

        await store.dispatch(RecordingStarted())
        assert store.state.recording_status == RecordingStatus.RECORDING

        await store.dispatch(StopRecording())
        assert store.state.recording_status == RecordingStatus.STOPPING

        await store.dispatch(RecordingStopped())
        assert store.state.recording_status == RecordingStatus.STOPPED

    @pytest.mark.asyncio
    async def test_settings_applied(self):
        store = create_store()
        executor = MockEffectExecutor()
        caps = CameraCapabilities(camera_id="imx708")
        executor.set_auto_dispatch(ProbeCamera, CameraAssigned("imx708", 0, caps))
        store.set_effect_handler(executor)

        await store.dispatch(AssignCamera(0))

        new_settings = CameraSettings(
            resolution=(1280, 720),
            capture_fps=60,
            preview_fps=5,
            record_fps=10,
        )
        await store.dispatch(ApplySettings(new_settings))

        assert store.state.settings.resolution == (1280, 720)
        assert store.state.settings.capture_fps == 60

    @pytest.mark.asyncio
    async def test_shutdown_cleans_up(self):
        store = create_store()
        executor = MockEffectExecutor()
        caps = CameraCapabilities(camera_id="imx708")
        executor.set_auto_dispatch(ProbeCamera, CameraAssigned("imx708", 0, caps))
        store.set_effect_handler(executor)

        await store.dispatch(AssignCamera(0))
        await store.dispatch(StartRecording(Path("/data"), 1))
        await store.dispatch(RecordingStarted())

        await store.dispatch(Shutdown())

        assert store.state.camera_status == CameraStatus.IDLE
        assert store.state.recording_status == RecordingStatus.STOPPED


class TestMultipleSubscribers:
    @pytest.mark.asyncio
    async def test_all_subscribers_notified(self):
        store = create_store()
        states1 = []
        states2 = []

        store.subscribe(lambda s: states1.append(s))
        store.subscribe(lambda s: states2.append(s))

        await store.dispatch(AssignCamera(0))

        assert len(states1) == 2
        assert len(states2) == 2

    @pytest.mark.asyncio
    async def test_unsubscribe_works(self):
        store = create_store()
        states = []

        unsubscribe = store.subscribe(lambda s: states.append(s))
        assert len(states) == 1

        unsubscribe()
        await store.dispatch(AssignCamera(0))

        assert len(states) == 1
