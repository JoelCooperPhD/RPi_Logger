import pytest
import tkinter as tk
from typing import Callable
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.state import AppState, CameraStatus, RecordingStatus, CameraSettings, FrameMetrics
from core.actions import Action


@pytest.fixture
def initial_state() -> AppState:
    return AppState()


@pytest.fixture
def streaming_state() -> AppState:
    return AppState(
        camera_status=CameraStatus.STREAMING,
        camera_id="imx708",
        camera_index=0,
    )


@pytest.fixture
def recording_state() -> AppState:
    return AppState(
        camera_status=CameraStatus.STREAMING,
        recording_status=RecordingStatus.RECORDING,
        camera_id="imx708",
        camera_index=0,
        session_dir=Path("/data/session"),
        trial_number=1,
    )


@pytest.fixture
def action_collector() -> tuple[list[Action], Callable[[Action], None]]:
    actions: list[Action] = []
    def dispatch(action: Action) -> None:
        actions.append(action)
    return actions, dispatch


@pytest.fixture
def tk_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()
