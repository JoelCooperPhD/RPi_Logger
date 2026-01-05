"""Pytest fixtures for API unit tests.

Provides fixtures for creating mock API controllers and aiohttp test clients
that can be used to test API endpoints without requiring a real LoggerSystem.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncGenerator, Coroutine, Dict, List, Optional, TypeVar
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, TestClient, TestServer

from rpi_logger.core.api.server import APIServer
from rpi_logger.core.api.controller import APIController
from rpi_logger.core.api.routes import setup_all_routes


T = TypeVar("T")


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Run an async coroutine synchronously for testing."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class MockLoggerSystem:
    """Mock LoggerSystem for API testing."""

    def __init__(self):
        self.recording = False
        self.session_active = False
        self.session_dir = None
        self._modules = self._create_mock_modules()
        self._enabled_states = {m.name: True for m in self._modules[:4]}
        self._running_modules = []

    def _create_mock_modules(self) -> List[MagicMock]:
        """Create mock module descriptors."""
        modules = []
        for name in ["Audio", "Cameras", "GPS", "DRT", "VOG", "EyeTracker", "Notes"]:
            module = MagicMock()
            module.name = name
            module.display_name = name
            module.module_id = name.lower()
            module.entry_point = f"/path/to/{name.lower()}.py"
            module.config_path = f"/path/to/{name.lower()}/config.txt"
            modules.append(module)
        return modules

    def get_available_modules(self) -> List[MagicMock]:
        return self._modules

    def get_module_by_name(self, name: str) -> Optional[MagicMock]:
        for m in self._modules:
            if m.name.lower() == name.lower():
                return m
        return None

    def is_module_enabled(self, name: str) -> bool:
        return self._enabled_states.get(name, False)

    def set_module_enabled(self, name: str, enabled: bool) -> None:
        self._enabled_states[name] = enabled

    def get_running_modules(self) -> List[str]:
        return self._running_modules

    async def start_module(self, name: str) -> bool:
        if name not in self._running_modules:
            self._running_modules.append(name)
        return True

    async def stop_module(self, name: str) -> bool:
        if name in self._running_modules:
            self._running_modules.remove(name)
        return True

    async def send_module_command(self, name: str, command: str, **kwargs) -> Dict:
        return {"success": True, "command": command}


class MockAPIController(APIController):
    """Mock APIController with stubbed methods for testing."""

    def __init__(self, logger_system: Optional[MockLoggerSystem] = None):
        self._logger_system = logger_system or MockLoggerSystem()
        self._session_active = False
        self._session_dir = None
        self._trial_active = False
        self._trial_counter = 0
        self._trial_label = None

    @property
    def logger_system(self):
        return self._logger_system

    @property
    def trial_active(self) -> bool:
        return self._trial_active

    @property
    def trial_counter(self) -> int:
        return self._trial_counter

    # System endpoints
    async def health_check(self) -> Dict:
        return {"status": "healthy", "version": "1.0.0"}

    async def get_status(self) -> Dict:
        return {
            "session_active": self._session_active,
            "trial_active": self._trial_active,
            "trial_counter": self._trial_counter,
            "trial_label": self._trial_label,
            "session_dir": str(self._session_dir) if self._session_dir else None,
            "available_modules": [m.name for m in self._logger_system.get_available_modules()],
            "running_modules": self._logger_system.get_running_modules(),
            "selected_modules": list(self._logger_system._enabled_states.keys()),
            "recording": self._logger_system.recording,
            "scanning_enabled": False,
        }

    async def get_platform_info(self) -> Dict:
        return {
            "platform": "linux",
            "python_version": "3.12.0",
            "hostname": "test-host",
        }

    async def get_system_info(self) -> Dict:
        return {
            "cpu_percent": 25.0,
            "memory_percent": 50.0,
            "disk_free_gb": 100.0,
        }

    async def shutdown(self) -> Dict:
        return {"success": True, "message": "Shutdown initiated"}

    # Module endpoints
    async def list_modules(self) -> List[Dict]:
        modules = []
        for m in self._logger_system.get_available_modules():
            modules.append({
                "name": m.name,
                "display_name": m.display_name,
                "module_id": m.module_id,
                "entry_point": m.entry_point,
                "enabled": self._logger_system.is_module_enabled(m.name),
                "running": m.name in self._logger_system.get_running_modules(),
                "state": "running" if m.name in self._logger_system.get_running_modules() else "stopped",
                "config_path": m.config_path,
            })
        return modules

    async def get_module(self, name: str) -> Optional[Dict]:
        m = self._logger_system.get_module_by_name(name)
        if not m:
            return None
        return {
            "name": m.name,
            "display_name": m.display_name,
            "module_id": m.module_id,
            "entry_point": m.entry_point,
            "enabled": self._logger_system.is_module_enabled(m.name),
            "running": m.name in self._logger_system.get_running_modules(),
            "state": "running" if m.name in self._logger_system.get_running_modules() else "stopped",
            "config_path": m.config_path,
        }

    async def get_module_state(self, name: str) -> Optional[str]:
        m = self._logger_system.get_module_by_name(name)
        if not m:
            return None
        return "running" if m.name in self._logger_system.get_running_modules() else "stopped"

    async def get_running_modules(self) -> List[str]:
        return self._logger_system.get_running_modules()

    async def get_enabled_states(self) -> Dict[str, bool]:
        return self._logger_system._enabled_states.copy()

    async def enable_module(self, name: str) -> Dict:
        m = self._logger_system.get_module_by_name(name)
        if not m:
            return {"success": False, "error": "module_not_found"}
        self._logger_system.set_module_enabled(name, True)
        return {"success": True, "module": name, "enabled": True}

    async def disable_module(self, name: str) -> Dict:
        m = self._logger_system.get_module_by_name(name)
        if not m:
            return {"success": False, "error": "module_not_found"}
        self._logger_system.set_module_enabled(name, False)
        return {"success": True, "module": name, "enabled": False}

    async def start_module(self, name: str) -> Dict:
        m = self._logger_system.get_module_by_name(name)
        if not m:
            return {"success": False, "error": "module_not_found"}
        await self._logger_system.start_module(name)
        return {"success": True, "module": name, "state": "running"}

    async def stop_module(self, name: str) -> Dict:
        m = self._logger_system.get_module_by_name(name)
        if not m:
            return {"success": False, "error": "module_not_found"}
        await self._logger_system.stop_module(name)
        return {"success": True, "module": name, "state": "stopped"}

    async def send_module_command(self, name: str, command: str, **kwargs) -> Dict:
        m = self._logger_system.get_module_by_name(name)
        if not m:
            return {"success": False, "error": "module_not_found"}
        return {"success": True, "module": name, "command": command, "result": "ok"}

    async def list_instances(self) -> List[Dict]:
        return []

    async def stop_instance(self, instance_id: str) -> Dict:
        return {"success": False, "error": "instance_not_found"}

    # Session endpoints
    async def get_session_info(self) -> Dict:
        return {
            "active": self._session_active,
            "directory": str(self._session_dir) if self._session_dir else None,
            "trial_counter": self._trial_counter,
        }

    async def start_session(self, directory: Optional[str] = None) -> Dict:
        if self._session_active:
            return {"success": False, "error": "session_already_active"}
        self._session_active = True
        self._session_dir = directory or "/tmp/test_session"
        return {"success": True, "directory": self._session_dir}

    async def stop_session(self) -> Dict:
        if not self._session_active:
            return {"success": False, "error": "no_active_session"}
        self._session_active = False
        self._session_dir = None
        self._trial_counter = 0
        return {"success": True}

    async def get_session_directory(self) -> Dict:
        return {"directory": str(self._session_dir) if self._session_dir else None}

    async def set_idle_session_directory(self, directory: str) -> Dict:
        if self._session_active:
            return {"success": False, "error": "session_active"}
        self._session_dir = directory
        return {"success": True, "directory": directory}

    # Trial endpoints
    async def get_trial_info(self) -> Dict:
        return {
            "active": self._trial_active,
            "counter": self._trial_counter,
            "label": self._trial_label,
        }

    async def start_trial(self, label: str = "") -> Dict:
        if not self._session_active:
            return {"success": False, "error": "no_active_session"}
        if self._trial_active:
            return {"success": False, "error": "trial_already_active"}
        self._trial_active = True
        self._trial_counter += 1
        self._trial_label = label or f"trial_{self._trial_counter}"
        self._logger_system.recording = True
        return {
            "success": True,
            "trial_number": self._trial_counter,
            "label": self._trial_label,
        }

    async def stop_trial(self) -> Dict:
        if not self._trial_active:
            return {"success": False, "error": "no_active_trial"}
        self._trial_active = False
        self._logger_system.recording = False
        return {"success": True, "trial_number": self._trial_counter}

    # Device endpoints
    async def list_devices(self) -> List[Dict]:
        return [
            {"id": "usb_gps_1", "type": "GPS", "port": "/dev/ttyUSB0", "connected": True},
            {"id": "usb_drt_1", "type": "DRT", "port": "/dev/ttyUSB1", "connected": False},
        ]

    async def get_connected_devices(self) -> List[Dict]:
        return [{"id": "usb_gps_1", "type": "GPS", "port": "/dev/ttyUSB0"}]

    async def get_device(self, device_id: str) -> Optional[Dict]:
        if device_id == "usb_gps_1":
            return {"id": "usb_gps_1", "type": "GPS", "port": "/dev/ttyUSB0", "connected": True}
        return None

    async def connect_device(self, device_id: str) -> Dict:
        if device_id == "usb_gps_1":
            return {"success": True, "device_id": device_id}
        return {"success": False, "error": "device_not_found"}

    async def disconnect_device(self, device_id: str) -> Dict:
        if device_id == "usb_gps_1":
            return {"success": True, "device_id": device_id}
        return {"success": False, "error": "device_not_found"}

    async def get_scanning_status(self) -> Dict:
        return {"scanning": False, "last_scan": None}

    async def start_scanning(self) -> Dict:
        return {"success": True, "scanning": True}

    async def stop_scanning(self) -> Dict:
        return {"success": True, "scanning": False}

    async def get_enabled_connections(self) -> Dict:
        return {"USB": {"GPS": True, "DRT": True}, "XBee": {"DRT": False, "VOG": False}}

    async def set_connection_enabled(self, interface: str, family: str, enabled: bool) -> Dict:
        return {"success": True, "interface": interface, "family": family, "enabled": enabled}

    async def get_xbee_status(self) -> Dict:
        return {"connected": False, "port": None, "network_id": None}

    async def xbee_rescan(self) -> Dict:
        return {"success": True, "devices_found": 0}

    # Config endpoints
    async def get_config(self) -> Dict:
        return {"data_dir": "data", "session_prefix": "session", "log_level": "info"}

    async def update_config(self, updates: Dict) -> Dict:
        return {"success": True, "updated": list(updates.keys())}

    async def get_config_path(self) -> Dict:
        return {"path": "/home/user/.config/rpi-logger/config.txt"}

    async def get_module_config(self, name: str) -> Optional[Dict]:
        m = self._logger_system.get_module_by_name(name)
        if not m:
            return None
        return {"output_dir": f"{name.lower()}_data", "log_level": "info"}

    async def update_module_config(self, name: str, updates: Dict) -> Dict:
        m = self._logger_system.get_module_by_name(name)
        if not m:
            return {"success": False, "error": "module_not_found"}
        return {"success": True, "module": name, "updated": list(updates.keys())}

    async def get_module_preferences(self, name: str) -> Optional[Dict]:
        m = self._logger_system.get_module_by_name(name)
        if not m:
            return None
        return {"window_geometry": "800x600+100+100", "auto_start": True}

    async def update_module_preference(self, name: str, key: str, value: Any) -> Dict:
        m = self._logger_system.get_module_by_name(name)
        if not m:
            return {"success": False, "error": "module_not_found"}
        return {"success": True, "module": name, "key": key, "value": value}

    # Log endpoints
    async def get_log_paths(self) -> Dict:
        return {
            "master": "/logs/master.log",
            "session": "/logs/session.log",
            "events": "/logs/events.log",
        }

    async def read_master_log(self, offset: int = 0, limit: int = 100) -> Dict:
        return {
            "success": True,
            "lines": ["2024-01-01 12:00:00 | INFO | Test log line"],
            "offset": offset,
            "limit": limit,
            "total_lines": 1,
        }

    async def read_session_log(self, offset: int = 0, limit: int = 100) -> Dict:
        return {
            "success": True,
            "lines": ["2024-01-01 12:00:00 | INFO | Session log line"],
            "offset": offset,
            "limit": limit,
            "total_lines": 1,
        }

    async def read_events_log(self, offset: int = 0, limit: int = 100) -> Dict:
        return {
            "success": True,
            "lines": ["2024-01-01 12:00:00 | INFO | Event log line"],
            "offset": offset,
            "limit": limit,
            "total_lines": 1,
        }

    async def read_module_log(self, name: str, offset: int = 0, limit: int = 100) -> Dict:
        m = self._logger_system.get_module_by_name(name)
        if not m:
            return {"success": False, "error": "MODULE_NOT_FOUND"}
        return {
            "success": True,
            "lines": [f"2024-01-01 12:00:00 | INFO | {name} log line"],
            "offset": offset,
            "limit": limit,
            "total_lines": 1,
        }

    async def tail_log_file(self, path: str, lines: int = 50) -> Dict:
        return {
            "success": True,
            "path": path,
            "lines": ["2024-01-01 12:00:00 | INFO | Last log line"],
            "count": 1,
        }


def create_test_app(controller: Optional[MockAPIController] = None) -> web.Application:
    """Create a test aiohttp application with all routes registered."""
    if controller is None:
        controller = MockAPIController()

    app = web.Application()
    app["controller"] = controller
    setup_all_routes(app, controller)
    return app


@pytest.fixture
def mock_controller() -> MockAPIController:
    """Create a mock API controller for testing."""
    return MockAPIController()


@pytest.fixture
def mock_logger_system() -> MockLoggerSystem:
    """Create a mock logger system for testing."""
    return MockLoggerSystem()


@pytest.fixture
def test_app(mock_controller: MockAPIController) -> web.Application:
    """Create a test aiohttp application."""
    return create_test_app(mock_controller)


@pytest.fixture
def api_client(test_app: web.Application):
    """Create an aiohttp test client.

    Usage:
        def test_endpoint(api_client):
            async def do_test():
                async with api_client as client:
                    resp = await client.get("/api/v1/health")
                    assert resp.status == 200
            run_async(do_test())
    """
    return TestClient(TestServer(test_app))
