"""Unit tests for ModuleManager."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rpi_logger.core.module_process import ModuleState


class MockModuleInfo:
    """Mock ModuleInfo for testing."""

    def __init__(
        self,
        name: str,
        module_id: str = None,
        config_path: Path = None,
        is_internal: bool = False
    ):
        self.name = name
        self.module_id = module_id or name.lower()
        self.config_path = config_path
        self.is_internal = is_internal
        self.main_module = f"rpi_logger.modules.{name}"


class MockModuleProcess:
    """Mock ModuleProcess for testing."""

    def __init__(self, name: str, running: bool = True):
        self.module_info = MockModuleInfo(name)
        self._running = running
        self._state = ModuleState.IDLE if running else ModuleState.STOPPED

    def is_running(self) -> bool:
        return self._running

    def get_state(self) -> ModuleState:
        return self._state


class MockStateManager:
    """Mock ModuleStateManager for testing."""

    def __init__(self):
        self._desired_states = {}
        self._actual_states = {}
        self._observers = []

    def register_module(self, module_name: str):
        self._desired_states[module_name] = False
        self._actual_states[module_name] = "STOPPED"

    def add_observer(self, callback, events=None):
        self._observers.append((callback, events))

    def is_module_enabled(self, module_name: str) -> bool:
        return self._desired_states.get(module_name, False)

    def get_desired_states(self):
        return self._desired_states.copy()

    def get_enabled_modules(self):
        return [name for name, enabled in self._desired_states.items() if enabled]

    def get_actual_state(self, module_name: str):
        return self._actual_states.get(module_name, "STOPPED")

    def is_state_consistent(self, module_name: str) -> bool:
        return True

    async def set_desired_state(self, module_name: str, enabled: bool, reconcile: bool = True):
        self._desired_states[module_name] = enabled


@pytest.fixture
def mock_state_manager():
    return MockStateManager()


@pytest.fixture
def mock_modules():
    return [
        MockModuleInfo("GPS", config_path=Path("/tmp/gps/config.txt")),
        MockModuleInfo("Audio", config_path=Path("/tmp/audio/config.txt")),
        MockModuleInfo("Notes", is_internal=True, config_path=Path("/tmp/notes/config.txt")),
    ]


class TestModuleManagerQueries:
    """Test ModuleManager query methods."""

    def test_is_module_running_true(self, mock_state_manager):
        with patch('rpi_logger.core.module_manager.get_module_logger'), \
             patch('rpi_logger.core.module_manager.discover_modules') as mock_discover, \
             patch('rpi_logger.core.module_manager.get_config_manager'):

            mock_discover.return_value = []

            from rpi_logger.core.module_manager import ModuleManager
            manager = ModuleManager(
                session_dir=Path("/tmp/test"),
                state_manager=mock_state_manager
            )

            manager.module_processes["GPS"] = MockModuleProcess("GPS", running=True)
            assert manager.is_module_running("GPS") is True

    def test_is_module_running_false(self, mock_state_manager):
        with patch('rpi_logger.core.module_manager.get_module_logger'), \
             patch('rpi_logger.core.module_manager.discover_modules') as mock_discover, \
             patch('rpi_logger.core.module_manager.get_config_manager'):

            mock_discover.return_value = []

            from rpi_logger.core.module_manager import ModuleManager
            manager = ModuleManager(
                session_dir=Path("/tmp/test"),
                state_manager=mock_state_manager
            )

            manager.module_processes["GPS"] = MockModuleProcess("GPS", running=False)
            assert manager.is_module_running("GPS") is False

    def test_is_module_running_not_exists(self, mock_state_manager):
        with patch('rpi_logger.core.module_manager.get_module_logger'), \
             patch('rpi_logger.core.module_manager.discover_modules') as mock_discover, \
             patch('rpi_logger.core.module_manager.get_config_manager'):

            mock_discover.return_value = []

            from rpi_logger.core.module_manager import ModuleManager
            manager = ModuleManager(
                session_dir=Path("/tmp/test"),
                state_manager=mock_state_manager
            )

            assert manager.is_module_running("NonExistent") is False

    def test_get_module_state(self, mock_state_manager):
        with patch('rpi_logger.core.module_manager.get_module_logger'), \
             patch('rpi_logger.core.module_manager.discover_modules') as mock_discover, \
             patch('rpi_logger.core.module_manager.get_config_manager'):

            mock_discover.return_value = []

            from rpi_logger.core.module_manager import ModuleManager
            manager = ModuleManager(
                session_dir=Path("/tmp/test"),
                state_manager=mock_state_manager
            )

            manager.module_processes["GPS"] = MockModuleProcess("GPS")
            assert manager.get_module_state("GPS") == ModuleState.IDLE

    def test_get_module_state_none(self, mock_state_manager):
        with patch('rpi_logger.core.module_manager.get_module_logger'), \
             patch('rpi_logger.core.module_manager.discover_modules') as mock_discover, \
             patch('rpi_logger.core.module_manager.get_config_manager'):

            mock_discover.return_value = []

            from rpi_logger.core.module_manager import ModuleManager
            manager = ModuleManager(
                session_dir=Path("/tmp/test"),
                state_manager=mock_state_manager
            )

            assert manager.get_module_state("NonExistent") is None

    def test_get_running_modules(self, mock_state_manager):
        with patch('rpi_logger.core.module_manager.get_module_logger'), \
             patch('rpi_logger.core.module_manager.discover_modules') as mock_discover, \
             patch('rpi_logger.core.module_manager.get_config_manager'):

            mock_discover.return_value = []

            from rpi_logger.core.module_manager import ModuleManager
            manager = ModuleManager(
                session_dir=Path("/tmp/test"),
                state_manager=mock_state_manager
            )

            manager.module_processes["GPS"] = MockModuleProcess("GPS", running=True)
            manager.module_processes["Audio"] = MockModuleProcess("Audio", running=False)
            manager.module_processes["Camera"] = MockModuleProcess("Camera", running=True)

            running = manager.get_running_modules()
            assert "GPS" in running
            assert "Camera" in running
            assert "Audio" not in running

    def test_get_available_modules(self, mock_state_manager, mock_modules):
        with patch('rpi_logger.core.module_manager.get_module_logger'), \
             patch('rpi_logger.core.module_manager.discover_modules') as mock_discover, \
             patch('rpi_logger.core.module_manager.get_config_manager'):

            mock_discover.return_value = mock_modules

            from rpi_logger.core.module_manager import ModuleManager
            manager = ModuleManager(
                session_dir=Path("/tmp/test"),
                state_manager=mock_state_manager
            )

            available = manager.get_available_modules()
            assert len(available) == 3
            assert available[0].name == "GPS"


class TestModuleManagerInternalModules:
    """Test internal module detection."""

    def test_is_internal_module_true(self, mock_state_manager, mock_modules):
        with patch('rpi_logger.core.module_manager.get_module_logger'), \
             patch('rpi_logger.core.module_manager.discover_modules') as mock_discover, \
             patch('rpi_logger.core.module_manager.get_config_manager'):

            mock_discover.return_value = mock_modules

            from rpi_logger.core.module_manager import ModuleManager
            manager = ModuleManager(
                session_dir=Path("/tmp/test"),
                state_manager=mock_state_manager
            )

            assert manager.is_internal_module("Notes") is True

    def test_is_internal_module_false(self, mock_state_manager, mock_modules):
        with patch('rpi_logger.core.module_manager.get_module_logger'), \
             patch('rpi_logger.core.module_manager.discover_modules') as mock_discover, \
             patch('rpi_logger.core.module_manager.get_config_manager'):

            mock_discover.return_value = mock_modules

            from rpi_logger.core.module_manager import ModuleManager
            manager = ModuleManager(
                session_dir=Path("/tmp/test"),
                state_manager=mock_state_manager
            )

            assert manager.is_internal_module("GPS") is False

    def test_is_internal_module_with_instance_id(self, mock_state_manager, mock_modules):
        with patch('rpi_logger.core.module_manager.get_module_logger'), \
             patch('rpi_logger.core.module_manager.discover_modules') as mock_discover, \
             patch('rpi_logger.core.module_manager.get_config_manager'):

            mock_discover.return_value = mock_modules

            from rpi_logger.core.module_manager import ModuleManager
            manager = ModuleManager(
                session_dir=Path("/tmp/test"),
                state_manager=mock_state_manager
            )

            assert manager.is_internal_module("Notes:default") is True

    def test_is_internal_module_unknown(self, mock_state_manager, mock_modules):
        with patch('rpi_logger.core.module_manager.get_module_logger'), \
             patch('rpi_logger.core.module_manager.discover_modules') as mock_discover, \
             patch('rpi_logger.core.module_manager.get_config_manager'):

            mock_discover.return_value = mock_modules

            from rpi_logger.core.module_manager import ModuleManager
            manager = ModuleManager(
                session_dir=Path("/tmp/test"),
                state_manager=mock_state_manager
            )

            assert manager.is_internal_module("Unknown") is False


class TestModuleManagerStateManagement:
    """Test module state management."""

    def test_is_module_enabled(self, mock_state_manager):
        with patch('rpi_logger.core.module_manager.get_module_logger'), \
             patch('rpi_logger.core.module_manager.discover_modules') as mock_discover, \
             patch('rpi_logger.core.module_manager.get_config_manager'):

            mock_discover.return_value = []

            from rpi_logger.core.module_manager import ModuleManager
            manager = ModuleManager(
                session_dir=Path("/tmp/test"),
                state_manager=mock_state_manager
            )

            mock_state_manager._desired_states["GPS"] = True
            assert manager.is_module_enabled("GPS") is True

            mock_state_manager._desired_states["Audio"] = False
            assert manager.is_module_enabled("Audio") is False

    def test_get_module_enabled_states(self, mock_state_manager):
        with patch('rpi_logger.core.module_manager.get_module_logger'), \
             patch('rpi_logger.core.module_manager.discover_modules') as mock_discover, \
             patch('rpi_logger.core.module_manager.get_config_manager'):

            mock_discover.return_value = []

            from rpi_logger.core.module_manager import ModuleManager
            manager = ModuleManager(
                session_dir=Path("/tmp/test"),
                state_manager=mock_state_manager
            )

            mock_state_manager._desired_states = {"GPS": True, "Audio": False}
            states = manager.get_module_enabled_states()

            assert states["GPS"] is True
            assert states["Audio"] is False

    def test_get_selected_modules(self, mock_state_manager):
        with patch('rpi_logger.core.module_manager.get_module_logger'), \
             patch('rpi_logger.core.module_manager.discover_modules') as mock_discover, \
             patch('rpi_logger.core.module_manager.get_config_manager'):

            mock_discover.return_value = []

            from rpi_logger.core.module_manager import ModuleManager
            manager = ModuleManager(
                session_dir=Path("/tmp/test"),
                state_manager=mock_state_manager
            )

            mock_state_manager._desired_states = {"GPS": True, "Audio": False, "Camera": True}
            selected = manager.get_selected_modules()

            assert "GPS" in selected
            assert "Camera" in selected
            assert "Audio" not in selected

    def test_get_module(self, mock_state_manager):
        with patch('rpi_logger.core.module_manager.get_module_logger'), \
             patch('rpi_logger.core.module_manager.discover_modules') as mock_discover, \
             patch('rpi_logger.core.module_manager.get_config_manager'):

            mock_discover.return_value = []

            from rpi_logger.core.module_manager import ModuleManager
            manager = ModuleManager(
                session_dir=Path("/tmp/test"),
                state_manager=mock_state_manager
            )

            mock_process = MockModuleProcess("GPS")
            manager.module_processes["GPS"] = mock_process

            assert manager.get_module("GPS") is mock_process
            assert manager.get_module("NonExistent") is None


class TestModuleManagerAsync:
    """Test async methods of ModuleManager."""

    @pytest.mark.asyncio
    async def test_set_module_enabled(self, mock_state_manager):
        with patch('rpi_logger.core.module_manager.get_module_logger'), \
             patch('rpi_logger.core.module_manager.discover_modules') as mock_discover, \
             patch('rpi_logger.core.module_manager.get_config_manager'):

            mock_discover.return_value = []

            from rpi_logger.core.module_manager import ModuleManager
            manager = ModuleManager(
                session_dir=Path("/tmp/test"),
                state_manager=mock_state_manager
            )

            result = await manager.set_module_enabled("GPS", True)
            assert result is True
            assert mock_state_manager._desired_states.get("GPS") is True

    @pytest.mark.asyncio
    async def test_load_enabled_modules(self, mock_state_manager, mock_modules):
        mock_config_manager = MagicMock()
        mock_config_manager.read_config_async = AsyncMock(return_value={"enabled": True})
        mock_config_manager.get_bool = MagicMock(return_value=True)

        with patch('rpi_logger.core.module_manager.get_module_logger'), \
             patch('rpi_logger.core.module_manager.discover_modules') as mock_discover, \
             patch('rpi_logger.core.module_manager.get_config_manager') as mock_get_config:

            mock_discover.return_value = mock_modules
            mock_get_config.return_value = mock_config_manager

            from rpi_logger.core.module_manager import ModuleManager
            manager = ModuleManager(
                session_dir=Path("/tmp/test"),
                state_manager=mock_state_manager
            )

            await manager.load_enabled_modules()

            for module in mock_modules:
                assert module.name in mock_state_manager._desired_states
