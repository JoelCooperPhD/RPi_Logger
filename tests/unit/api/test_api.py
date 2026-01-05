"""Unit tests for REST API endpoints.

Tests all API routes using a mock controller to verify:
- Correct HTTP methods and status codes
- Request/response JSON structure
- Error handling for invalid requests
- Parameter validation

These tests run without requiring a real LoggerSystem or hardware.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Coroutine, TypeVar

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests.unit.api.conftest import (
    MockAPIController,
    MockLoggerSystem,
    create_test_app,
    run_async,
)


T = TypeVar("T")


# =============================================================================
# System Routes Tests
# =============================================================================


class TestSystemRoutes:
    """Tests for /api/v1/health, /api/v1/status, /api/v1/platform, etc."""

    def test_health_check(self, mock_controller: MockAPIController):
        """GET /api/v1/health returns healthy status."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/v1/health")
                assert resp.status == 200
                data = await resp.json()
                assert data["status"] == "healthy"
                assert "version" in data

        run_async(do_test())

    def test_status(self, mock_controller: MockAPIController):
        """GET /api/v1/status returns full system status."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/v1/status")
                assert resp.status == 200
                data = await resp.json()
                assert "session_active" in data
                assert "trial_active" in data
                assert "available_modules" in data
                assert "running_modules" in data
                assert isinstance(data["available_modules"], list)

        run_async(do_test())

    def test_platform_info(self, mock_controller: MockAPIController):
        """GET /api/v1/platform returns platform information."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/v1/platform")
                assert resp.status == 200
                data = await resp.json()
                assert "platform" in data
                assert "python_version" in data

        run_async(do_test())

    def test_system_info(self, mock_controller: MockAPIController):
        """GET /api/v1/info/system returns system metrics."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/v1/info/system")
                assert resp.status == 200
                data = await resp.json()
                assert "cpu_percent" in data
                assert "memory_percent" in data

        run_async(do_test())

    def test_shutdown(self, mock_controller: MockAPIController):
        """POST /api/v1/shutdown initiates shutdown."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.post("/api/v1/shutdown")
                assert resp.status == 200
                data = await resp.json()
                assert data["success"] is True

        run_async(do_test())


# =============================================================================
# Module Routes Tests
# =============================================================================


class TestModuleRoutes:
    """Tests for /api/v1/modules/* endpoints."""

    def test_list_modules(self, mock_controller: MockAPIController):
        """GET /api/v1/modules returns all modules."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/v1/modules")
                assert resp.status == 200
                data = await resp.json()
                assert "modules" in data
                assert len(data["modules"]) == 7  # 7 mock modules
                module = data["modules"][0]
                assert "name" in module
                assert "enabled" in module
                assert "running" in module
                assert "state" in module

        run_async(do_test())

    def test_get_running_modules(self, mock_controller: MockAPIController):
        """GET /api/v1/modules/running returns running modules."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/v1/modules/running")
                assert resp.status == 200
                data = await resp.json()
                assert "running_modules" in data
                assert isinstance(data["running_modules"], list)

        run_async(do_test())

    def test_get_enabled_states(self, mock_controller: MockAPIController):
        """GET /api/v1/modules/enabled-states returns enabled states."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/v1/modules/enabled-states")
                assert resp.status == 200
                data = await resp.json()
                assert "enabled_states" in data
                assert isinstance(data["enabled_states"], dict)

        run_async(do_test())

    def test_get_module(self, mock_controller: MockAPIController):
        """GET /api/v1/modules/{name} returns module details."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/v1/modules/Audio")
                assert resp.status == 200
                data = await resp.json()
                assert data["name"] == "Audio"
                assert "enabled" in data
                assert "state" in data

        run_async(do_test())

    def test_get_module_not_found(self, mock_controller: MockAPIController):
        """GET /api/v1/modules/{name} returns 404 for unknown module."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/v1/modules/NonExistent")
                assert resp.status == 404
                data = await resp.json()
                assert "error" in data

        run_async(do_test())

    def test_get_module_state(self, mock_controller: MockAPIController):
        """GET /api/v1/modules/{name}/state returns module state."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/v1/modules/Audio/state")
                assert resp.status == 200
                data = await resp.json()
                assert data["module"] == "Audio"
                assert data["state"] in ["running", "stopped", "starting", "stopping"]

        run_async(do_test())

    def test_enable_module(self, mock_controller: MockAPIController):
        """POST /api/v1/modules/{name}/enable enables a module."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.post("/api/v1/modules/VOG/enable")
                assert resp.status == 200
                data = await resp.json()
                assert data["success"] is True
                assert data["enabled"] is True

        run_async(do_test())

    def test_disable_module(self, mock_controller: MockAPIController):
        """POST /api/v1/modules/{name}/disable disables a module."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.post("/api/v1/modules/Audio/disable")
                assert resp.status == 200
                data = await resp.json()
                assert data["success"] is True
                assert data["enabled"] is False

        run_async(do_test())

    def test_start_module(self, mock_controller: MockAPIController):
        """POST /api/v1/modules/{name}/start starts a module."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.post("/api/v1/modules/Audio/start")
                assert resp.status == 200
                data = await resp.json()
                assert data["success"] is True
                assert data["state"] == "running"

        run_async(do_test())

    def test_stop_module(self, mock_controller: MockAPIController):
        """POST /api/v1/modules/{name}/stop stops a module."""

        async def do_test():
            app = create_test_app(mock_controller)
            # First start the module
            await mock_controller.start_module("Audio")

            async with TestClient(TestServer(app)) as client:
                resp = await client.post("/api/v1/modules/Audio/stop")
                assert resp.status == 200
                data = await resp.json()
                assert data["success"] is True
                assert data["state"] == "stopped"

        run_async(do_test())

    def test_send_command(self, mock_controller: MockAPIController):
        """POST /api/v1/modules/{name}/command sends command to module."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.post(
                    "/api/v1/modules/Audio/command",
                    json={"command": "get_levels"},
                )
                assert resp.status == 200
                data = await resp.json()
                assert data["success"] is True
                assert data["command"] == "get_levels"

        run_async(do_test())

    def test_send_command_missing_command(self, mock_controller: MockAPIController):
        """POST /api/v1/modules/{name}/command requires command field."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.post(
                    "/api/v1/modules/Audio/command",
                    json={},
                )
                assert resp.status == 400
                data = await resp.json()
                assert "error" in data

        run_async(do_test())

    def test_list_instances(self, mock_controller: MockAPIController):
        """GET /api/v1/instances returns running instances."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/v1/instances")
                assert resp.status == 200
                data = await resp.json()
                assert "instances" in data

        run_async(do_test())


# =============================================================================
# Session Routes Tests
# =============================================================================


class TestSessionRoutes:
    """Tests for /api/v1/session/* endpoints."""

    def test_get_session(self, mock_controller: MockAPIController):
        """GET /api/v1/session returns session info."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/v1/session")
                assert resp.status == 200
                data = await resp.json()
                assert "active" in data
                assert "directory" in data

        run_async(do_test())

    def test_start_session(self, mock_controller: MockAPIController):
        """POST /api/v1/session/start starts a session."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.post(
                    "/api/v1/session/start",
                    json={"directory": "/tmp/test_session"},
                )
                assert resp.status == 200
                data = await resp.json()
                assert data["success"] is True
                assert "directory" in data

        run_async(do_test())

    def test_start_session_already_active(self, mock_controller: MockAPIController):
        """POST /api/v1/session/start fails if session active."""

        async def do_test():
            app = create_test_app(mock_controller)
            # First start a session
            await mock_controller.start_session()

            async with TestClient(TestServer(app)) as client:
                resp = await client.post("/api/v1/session/start")
                assert resp.status == 400
                data = await resp.json()
                assert data["success"] is False

        run_async(do_test())

    def test_stop_session(self, mock_controller: MockAPIController):
        """POST /api/v1/session/stop stops a session."""

        async def do_test():
            app = create_test_app(mock_controller)
            # First start a session
            await mock_controller.start_session()

            async with TestClient(TestServer(app)) as client:
                resp = await client.post("/api/v1/session/stop")
                assert resp.status == 200
                data = await resp.json()
                assert data["success"] is True

        run_async(do_test())

    def test_stop_session_not_active(self, mock_controller: MockAPIController):
        """POST /api/v1/session/stop fails if no session active."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.post("/api/v1/session/stop")
                assert resp.status == 400
                data = await resp.json()
                assert data["success"] is False

        run_async(do_test())

    def test_get_session_directory(self, mock_controller: MockAPIController):
        """GET /api/v1/session/directory returns session directory."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/v1/session/directory")
                assert resp.status == 200
                data = await resp.json()
                assert "directory" in data

        run_async(do_test())

    def test_set_session_directory(self, mock_controller: MockAPIController):
        """PUT /api/v1/session/directory sets idle session directory."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.put(
                    "/api/v1/session/directory",
                    json={"directory": "/data/sessions"},
                )
                assert resp.status == 200
                data = await resp.json()
                assert data["success"] is True

        run_async(do_test())

    def test_set_session_directory_missing_field(
        self, mock_controller: MockAPIController
    ):
        """PUT /api/v1/session/directory requires directory field."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.put(
                    "/api/v1/session/directory",
                    json={},
                )
                assert resp.status == 400
                data = await resp.json()
                assert "error" in data

        run_async(do_test())

    def test_recording_status(self, mock_controller: MockAPIController):
        """GET /api/v1/session/recording returns recording status."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/v1/session/recording")
                assert resp.status == 200
                data = await resp.json()
                assert "recording" in data
                assert "trial_active" in data

        run_async(do_test())


# =============================================================================
# Trial Routes Tests
# =============================================================================


class TestTrialRoutes:
    """Tests for /api/v1/trial/* endpoints."""

    def test_get_trial(self, mock_controller: MockAPIController):
        """GET /api/v1/trial returns trial info."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/v1/trial")
                assert resp.status == 200
                data = await resp.json()
                assert "active" in data
                assert "counter" in data

        run_async(do_test())

    def test_start_trial(self, mock_controller: MockAPIController):
        """POST /api/v1/trial/start starts a trial."""

        async def do_test():
            app = create_test_app(mock_controller)
            # First start a session
            await mock_controller.start_session()

            async with TestClient(TestServer(app)) as client:
                resp = await client.post(
                    "/api/v1/trial/start",
                    json={"label": "baseline_01"},
                )
                assert resp.status == 200
                data = await resp.json()
                assert data["success"] is True
                assert data["trial_number"] == 1
                assert data["label"] == "baseline_01"

        run_async(do_test())

    def test_start_trial_no_session(self, mock_controller: MockAPIController):
        """POST /api/v1/trial/start fails without active session."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.post("/api/v1/trial/start")
                assert resp.status == 400
                data = await resp.json()
                assert data["success"] is False

        run_async(do_test())

    def test_stop_trial(self, mock_controller: MockAPIController):
        """POST /api/v1/trial/stop stops a trial."""

        async def do_test():
            app = create_test_app(mock_controller)
            # Start session and trial
            await mock_controller.start_session()
            await mock_controller.start_trial("test")

            async with TestClient(TestServer(app)) as client:
                resp = await client.post("/api/v1/trial/stop")
                assert resp.status == 200
                data = await resp.json()
                assert data["success"] is True

        run_async(do_test())

    def test_stop_trial_not_active(self, mock_controller: MockAPIController):
        """POST /api/v1/trial/stop fails if no trial active."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.post("/api/v1/trial/stop")
                assert resp.status == 400
                data = await resp.json()
                assert data["success"] is False

        run_async(do_test())

    def test_trial_counter(self, mock_controller: MockAPIController):
        """GET /api/v1/trial/counter returns trial counter."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/v1/trial/counter")
                assert resp.status == 200
                data = await resp.json()
                assert "trial_counter" in data
                assert isinstance(data["trial_counter"], int)

        run_async(do_test())

    def test_trial_counter_increments(self, mock_controller: MockAPIController):
        """Trial counter increments with each trial."""

        async def do_test():
            app = create_test_app(mock_controller)
            await mock_controller.start_session()

            async with TestClient(TestServer(app)) as client:
                # Check initial counter
                resp = await client.get("/api/v1/trial/counter")
                data = await resp.json()
                assert data["trial_counter"] == 0

                # Start and stop first trial
                await mock_controller.start_trial("trial_1")
                await mock_controller.stop_trial()

                resp = await client.get("/api/v1/trial/counter")
                data = await resp.json()
                assert data["trial_counter"] == 1

                # Start and stop second trial
                await mock_controller.start_trial("trial_2")
                await mock_controller.stop_trial()

                resp = await client.get("/api/v1/trial/counter")
                data = await resp.json()
                assert data["trial_counter"] == 2

        run_async(do_test())


# =============================================================================
# Device Routes Tests
# =============================================================================


class TestDeviceRoutes:
    """Tests for /api/v1/devices/* endpoints."""

    def test_list_devices(self, mock_controller: MockAPIController):
        """GET /api/v1/devices returns all devices."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/v1/devices")
                assert resp.status == 200
                data = await resp.json()
                assert "devices" in data
                assert len(data["devices"]) == 2

        run_async(do_test())

    def test_connected_devices(self, mock_controller: MockAPIController):
        """GET /api/v1/devices/connected returns connected devices."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/v1/devices/connected")
                assert resp.status == 200
                data = await resp.json()
                assert "connected_devices" in data

        run_async(do_test())

    def test_get_device(self, mock_controller: MockAPIController):
        """GET /api/v1/devices/{id} returns device details."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/v1/devices/usb_gps_1")
                assert resp.status == 200
                data = await resp.json()
                assert data["id"] == "usb_gps_1"

        run_async(do_test())

    def test_get_device_not_found(self, mock_controller: MockAPIController):
        """GET /api/v1/devices/{id} returns 404 for unknown device."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/v1/devices/nonexistent")
                assert resp.status == 404

        run_async(do_test())

    def test_connect_device(self, mock_controller: MockAPIController):
        """POST /api/v1/devices/{id}/connect connects to device."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.post("/api/v1/devices/usb_gps_1/connect")
                assert resp.status == 200
                data = await resp.json()
                assert data["success"] is True

        run_async(do_test())

    def test_disconnect_device(self, mock_controller: MockAPIController):
        """POST /api/v1/devices/{id}/disconnect disconnects from device."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.post("/api/v1/devices/usb_gps_1/disconnect")
                assert resp.status == 200
                data = await resp.json()
                assert data["success"] is True

        run_async(do_test())

    def test_scanning_status(self, mock_controller: MockAPIController):
        """GET /api/v1/devices/scanning returns scanning status."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/v1/devices/scanning")
                assert resp.status == 200
                data = await resp.json()
                assert "scanning" in data

        run_async(do_test())

    def test_start_scanning(self, mock_controller: MockAPIController):
        """POST /api/v1/devices/scanning/start starts scanning."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.post("/api/v1/devices/scanning/start")
                assert resp.status == 200
                data = await resp.json()
                assert data["success"] is True

        run_async(do_test())

    def test_stop_scanning(self, mock_controller: MockAPIController):
        """POST /api/v1/devices/scanning/stop stops scanning."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.post("/api/v1/devices/scanning/stop")
                assert resp.status == 200
                data = await resp.json()
                assert data["success"] is True

        run_async(do_test())

    def test_list_connections(self, mock_controller: MockAPIController):
        """GET /api/v1/connections returns connection types."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/v1/connections")
                assert resp.status == 200
                data = await resp.json()
                assert "connections" in data

        run_async(do_test())

    def test_xbee_status(self, mock_controller: MockAPIController):
        """GET /api/v1/xbee/status returns XBee status."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/v1/xbee/status")
                assert resp.status == 200
                data = await resp.json()
                assert "connected" in data

        run_async(do_test())

    def test_xbee_rescan(self, mock_controller: MockAPIController):
        """POST /api/v1/xbee/rescan triggers XBee rescan."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.post("/api/v1/xbee/rescan")
                assert resp.status == 200
                data = await resp.json()
                assert data["success"] is True

        run_async(do_test())


# =============================================================================
# Config Routes Tests
# =============================================================================


class TestConfigRoutes:
    """Tests for /api/v1/config/* endpoints."""

    def test_get_config(self, mock_controller: MockAPIController):
        """GET /api/v1/config returns global configuration."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/v1/config")
                assert resp.status == 200
                data = await resp.json()
                assert "config" in data
                assert "data_dir" in data["config"]

        run_async(do_test())

    def test_update_config(self, mock_controller: MockAPIController):
        """PUT /api/v1/config updates configuration."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.put(
                    "/api/v1/config",
                    json={"log_level": "debug"},
                )
                assert resp.status == 200
                data = await resp.json()
                assert data["success"] is True

        run_async(do_test())

    def test_update_config_empty_body(self, mock_controller: MockAPIController):
        """PUT /api/v1/config requires non-empty body."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.put(
                    "/api/v1/config",
                    json={},
                )
                assert resp.status == 400

        run_async(do_test())

    def test_get_config_path(self, mock_controller: MockAPIController):
        """GET /api/v1/config/path returns config file path."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/v1/config/path")
                assert resp.status == 200
                data = await resp.json()
                assert "path" in data

        run_async(do_test())

    def test_get_module_config(self, mock_controller: MockAPIController):
        """GET /api/v1/modules/{name}/config returns module config."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/v1/modules/Audio/config")
                assert resp.status == 200
                data = await resp.json()
                # Config is returned directly, not wrapped
                assert "output_dir" in data or "log_level" in data

        run_async(do_test())

    def test_get_module_config_not_found(self, mock_controller: MockAPIController):
        """GET /api/v1/modules/{name}/config returns 404 for unknown module."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/v1/modules/NonExistent/config")
                assert resp.status == 404

        run_async(do_test())

    def test_update_module_config(self, mock_controller: MockAPIController):
        """PUT /api/v1/modules/{name}/config updates module config."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.put(
                    "/api/v1/modules/Audio/config",
                    json={"log_level": "debug"},
                )
                assert resp.status == 200
                data = await resp.json()
                assert data["success"] is True

        run_async(do_test())

    def test_get_module_preferences(self, mock_controller: MockAPIController):
        """GET /api/v1/modules/{name}/preferences returns preferences."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/v1/modules/Audio/preferences")
                assert resp.status == 200
                data = await resp.json()
                # Preferences are returned directly, not wrapped
                assert "window_geometry" in data or "auto_start" in data

        run_async(do_test())

    def test_update_module_preference(self, mock_controller: MockAPIController):
        """PUT /api/v1/modules/{name}/preferences/{key} updates preference."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.put(
                    "/api/v1/modules/Audio/preferences/auto_start",
                    json={"value": False},
                )
                assert resp.status == 200
                data = await resp.json()
                assert data["success"] is True

        run_async(do_test())


# =============================================================================
# Log Routes Tests
# =============================================================================


class TestLogRoutes:
    """Tests for /api/v1/logs/* endpoints."""

    def test_get_log_paths(self, mock_controller: MockAPIController):
        """GET /api/v1/logs/paths returns log file paths."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/v1/logs/paths")
                assert resp.status == 200
                data = await resp.json()
                assert "master" in data or "paths" in data

        run_async(do_test())

    def test_get_master_log(self, mock_controller: MockAPIController):
        """GET /api/v1/logs/master returns master log content."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/v1/logs/master")
                assert resp.status == 200
                data = await resp.json()
                assert "lines" in data

        run_async(do_test())

    def test_get_master_log_with_pagination(self, mock_controller: MockAPIController):
        """GET /api/v1/logs/master supports pagination."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/v1/logs/master?offset=10&limit=50")
                assert resp.status == 200
                data = await resp.json()
                assert "lines" in data

        run_async(do_test())

    def test_tail_log(self, mock_controller: MockAPIController):
        """GET /api/v1/logs/tail/{path} returns last log lines."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                # The tail endpoint uses /api/v1/logs/tail/{path}
                resp = await client.get("/api/v1/logs/tail/logs/master.log?lines=20")
                assert resp.status == 200
                data = await resp.json()
                assert "lines" in data

        run_async(do_test())


# =============================================================================
# Full Workflow Integration Test
# =============================================================================


class TestAPIWorkflow:
    """Integration tests for complete API workflows."""

    def test_full_recording_workflow(self, mock_controller: MockAPIController):
        """Test complete session -> trial -> stop workflow."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                # 1. Check health
                resp = await client.get("/api/v1/health")
                assert resp.status == 200

                # 2. Check initial status
                resp = await client.get("/api/v1/status")
                data = await resp.json()
                assert data["session_active"] is False
                assert data["trial_active"] is False

                # 3. Start session
                resp = await client.post(
                    "/api/v1/session/start",
                    json={"directory": "/tmp/test_recording"},
                )
                assert resp.status == 200

                # 4. Verify session active
                resp = await client.get("/api/v1/status")
                data = await resp.json()
                assert data["session_active"] is True

                # 5. Start trial
                resp = await client.post(
                    "/api/v1/trial/start",
                    json={"label": "baseline"},
                )
                assert resp.status == 200

                # 6. Verify recording
                resp = await client.get("/api/v1/session/recording")
                data = await resp.json()
                assert data["recording"] is True
                assert data["trial_active"] is True

                # 7. Stop trial
                resp = await client.post("/api/v1/trial/stop")
                assert resp.status == 200

                # 8. Verify not recording
                resp = await client.get("/api/v1/session/recording")
                data = await resp.json()
                assert data["recording"] is False

                # 9. Stop session
                resp = await client.post("/api/v1/session/stop")
                assert resp.status == 200

                # 10. Verify clean state
                resp = await client.get("/api/v1/status")
                data = await resp.json()
                assert data["session_active"] is False
                assert data["trial_active"] is False

        run_async(do_test())

    def test_module_lifecycle_workflow(self, mock_controller: MockAPIController):
        """Test module enable -> start -> stop -> disable workflow."""

        async def do_test():
            app = create_test_app(mock_controller)
            async with TestClient(TestServer(app)) as client:
                module_name = "GPS"

                # 1. Check module is initially disabled (GPS not in default enabled)
                resp = await client.get(f"/api/v1/modules/{module_name}")
                data = await resp.json()
                initial_enabled = data["enabled"]

                # 2. Enable module
                resp = await client.post(f"/api/v1/modules/{module_name}/enable")
                assert resp.status == 200

                # 3. Verify enabled
                resp = await client.get(f"/api/v1/modules/{module_name}")
                data = await resp.json()
                assert data["enabled"] is True

                # 4. Start module
                resp = await client.post(f"/api/v1/modules/{module_name}/start")
                assert resp.status == 200

                # 5. Verify running
                resp = await client.get(f"/api/v1/modules/{module_name}/state")
                data = await resp.json()
                assert data["state"] == "running"

                # 6. Check in running modules list
                resp = await client.get("/api/v1/modules/running")
                data = await resp.json()
                assert module_name in data["running_modules"]

                # 7. Stop module
                resp = await client.post(f"/api/v1/modules/{module_name}/stop")
                assert resp.status == 200

                # 8. Verify stopped
                resp = await client.get(f"/api/v1/modules/{module_name}/state")
                data = await resp.json()
                assert data["state"] == "stopped"

                # 9. Disable module
                resp = await client.post(f"/api/v1/modules/{module_name}/disable")
                assert resp.status == 200

                # 10. Verify disabled
                resp = await client.get(f"/api/v1/modules/{module_name}")
                data = await resp.json()
                assert data["enabled"] is False

        run_async(do_test())
