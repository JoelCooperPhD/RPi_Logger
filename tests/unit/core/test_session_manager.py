"""Unit tests for SessionManager."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rpi_logger.core.session_manager import SessionManager
from rpi_logger.core.module_process import ModuleState


class MockModuleProcess:
    """Mock ModuleProcess for testing."""

    def __init__(
        self,
        name: str = "TestModule",
        running: bool = True,
        initialized: bool = True,
        recording: bool = False
    ):
        self.name = name
        self._running = running
        self._initialized = initialized
        self._recording = recording
        self._state = ModuleState.IDLE if initialized else ModuleState.STOPPED
        self.output_dir = None

        self.start_session = AsyncMock()
        self.stop_session = AsyncMock()
        self.record = AsyncMock()
        self.pause = AsyncMock()
        self.get_status = AsyncMock()

    def is_running(self) -> bool:
        return self._running

    def is_initialized(self) -> bool:
        return self._initialized

    def is_recording(self) -> bool:
        return self._recording

    def get_state(self) -> ModuleState:
        return self._state


@pytest.fixture
def session_manager():
    with patch('rpi_logger.core.session_manager.get_module_logger'):
        return SessionManager()


@pytest.fixture
def mock_processes():
    return {
        "GPS": MockModuleProcess("GPS"),
        "Audio": MockModuleProcess("Audio"),
        "Camera": MockModuleProcess("Camera"),
    }


class TestSessionManagerInit:
    """Test SessionManager initialization."""

    def test_init(self, session_manager):
        assert session_manager.recording is False

    def test_is_any_recording_none(self, session_manager):
        processes = {}
        assert session_manager.is_any_recording(processes) is False

    def test_is_any_recording_false(self, session_manager, mock_processes):
        assert session_manager.is_any_recording(mock_processes) is False

    def test_is_any_recording_true(self, session_manager):
        processes = {
            "GPS": MockModuleProcess("GPS", recording=False),
            "Audio": MockModuleProcess("Audio", recording=True),
        }
        assert session_manager.is_any_recording(processes) is True


class TestSessionManagerStartSession:
    """Test start_session_all functionality."""

    @pytest.mark.asyncio
    async def test_start_session_all_success(self, session_manager, mock_processes, tmp_path):
        results = await session_manager.start_session_all(mock_processes, tmp_path)

        assert results["GPS"] is True
        assert results["Audio"] is True
        assert results["Camera"] is True

        for process in mock_processes.values():
            process.start_session.assert_called_once()
            assert process.output_dir == tmp_path

    @pytest.mark.asyncio
    async def test_start_session_skips_not_running(self, session_manager, tmp_path):
        processes = {
            "GPS": MockModuleProcess("GPS", running=False),
            "Audio": MockModuleProcess("Audio"),
        }

        results = await session_manager.start_session_all(processes, tmp_path)

        assert results["GPS"] is False
        assert results["Audio"] is True
        processes["GPS"].start_session.assert_not_called()
        processes["Audio"].start_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_session_skips_not_initialized(self, session_manager, tmp_path):
        processes = {
            "GPS": MockModuleProcess("GPS", initialized=False),
            "Audio": MockModuleProcess("Audio"),
        }

        results = await session_manager.start_session_all(processes, tmp_path)

        assert results["GPS"] is False
        assert results["Audio"] is True

    @pytest.mark.asyncio
    async def test_start_session_handles_exception(self, session_manager, tmp_path):
        processes = {
            "GPS": MockModuleProcess("GPS"),
            "Audio": MockModuleProcess("Audio"),
        }
        processes["GPS"].start_session.side_effect = RuntimeError("Connection failed")

        results = await session_manager.start_session_all(processes, tmp_path)

        assert results["GPS"] is False
        assert results["Audio"] is True


class TestSessionManagerStopSession:
    """Test stop_session_all functionality."""

    @pytest.mark.asyncio
    async def test_stop_session_all_success(self, session_manager, mock_processes):
        results = await session_manager.stop_session_all(mock_processes)

        assert all(results.values())
        for process in mock_processes.values():
            process.stop_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_session_skips_not_running(self, session_manager):
        processes = {
            "GPS": MockModuleProcess("GPS", running=False),
            "Audio": MockModuleProcess("Audio"),
        }

        results = await session_manager.stop_session_all(processes)

        assert results["GPS"] is False
        assert results["Audio"] is True

    @pytest.mark.asyncio
    async def test_stop_session_handles_exception(self, session_manager):
        processes = {
            "GPS": MockModuleProcess("GPS"),
        }
        processes["GPS"].stop_session.side_effect = RuntimeError("Stop failed")

        results = await session_manager.stop_session_all(processes)

        assert results["GPS"] is False


class TestSessionManagerRecord:
    """Test record_all functionality."""

    @pytest.mark.asyncio
    async def test_record_all_success(self, session_manager, mock_processes, tmp_path):
        results = await session_manager.record_all(
            mock_processes, tmp_path, trial_number=1, trial_label="baseline"
        )

        assert all(results.values())
        assert session_manager.recording is True
        for process in mock_processes.values():
            process.record.assert_called_once_with(1, "baseline")

    @pytest.mark.asyncio
    async def test_record_all_already_recording(self, session_manager, tmp_path):
        processes = {
            "GPS": MockModuleProcess("GPS", recording=True),
        }

        results = await session_manager.record_all(processes, tmp_path)

        assert results == {}
        assert session_manager.recording is True

    @pytest.mark.asyncio
    async def test_record_all_skips_not_running(self, session_manager, tmp_path):
        processes = {
            "GPS": MockModuleProcess("GPS", running=False),
            "Audio": MockModuleProcess("Audio"),
        }

        results = await session_manager.record_all(processes, tmp_path)

        assert results["GPS"] is False
        assert results["Audio"] is True

    @pytest.mark.asyncio
    async def test_record_all_handles_exception(self, session_manager, tmp_path):
        processes = {
            "GPS": MockModuleProcess("GPS"),
        }
        processes["GPS"].record.side_effect = RuntimeError("Record failed")

        results = await session_manager.record_all(processes, tmp_path)

        assert results["GPS"] is False
        assert session_manager.recording is False


class TestSessionManagerPause:
    """Test pause_all functionality."""

    @pytest.mark.asyncio
    async def test_pause_all_success(self, session_manager, mock_processes):
        session_manager.recording = True

        results = await session_manager.pause_all(mock_processes)

        assert all(results.values())
        assert session_manager.recording is False
        for process in mock_processes.values():
            process.pause.assert_called_once()

    @pytest.mark.asyncio
    async def test_pause_all_not_recording(self, session_manager, mock_processes):
        session_manager.recording = False

        results = await session_manager.pause_all(mock_processes)

        assert results == {}

    @pytest.mark.asyncio
    async def test_pause_all_handles_exception(self, session_manager):
        session_manager.recording = True
        processes = {
            "GPS": MockModuleProcess("GPS"),
        }
        processes["GPS"].pause.side_effect = RuntimeError("Pause failed")

        results = await session_manager.pause_all(processes)

        assert results["GPS"] is False


class TestSessionManagerStatus:
    """Test get_status_all functionality."""

    @pytest.mark.asyncio
    async def test_get_status_all(self, session_manager, mock_processes):
        results = await session_manager.get_status_all(mock_processes)

        assert len(results) == 3
        for name, state in results.items():
            assert state == ModuleState.IDLE

    @pytest.mark.asyncio
    async def test_get_status_not_running(self, session_manager):
        processes = {
            "GPS": MockModuleProcess("GPS", running=False),
        }
        processes["GPS"]._state = ModuleState.STOPPED

        results = await session_manager.get_status_all(processes)

        assert results["GPS"] == ModuleState.STOPPED

    @pytest.mark.asyncio
    async def test_get_status_handles_exception(self, session_manager):
        processes = {
            "GPS": MockModuleProcess("GPS"),
        }
        processes["GPS"].get_status.side_effect = RuntimeError("Status failed")

        results = await session_manager.get_status_all(processes)

        assert results["GPS"] == ModuleState.ERROR
