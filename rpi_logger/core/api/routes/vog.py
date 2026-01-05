"""
VOG Routes - VOG (Video Oculography) module-specific API endpoints.

Provides endpoints for managing VOG devices (sVOG wired and wVOG wireless),
including device listing, configuration, eye position data, pupil diameter,
lens control, and battery status.

Endpoints:
- GET  /api/v1/modules/vog/devices        - List available VOG devices (sVOG/wVOG)
- GET  /api/v1/modules/vog/config         - Get VOG configuration
- PUT  /api/v1/modules/vog/config         - Update VOG configuration
- GET  /api/v1/modules/vog/eye-position   - Get current eye position data
- GET  /api/v1/modules/vog/pupil          - Get pupil diameter
- POST /api/v1/modules/vog/lens           - Switch lens (wVOG: A/B/X)
- GET  /api/v1/modules/vog/battery        - Get battery level (wVOG only)
- GET  /api/v1/modules/vog/status         - Get module status
"""

from aiohttp import web

from ..controller import APIController
from ..middleware import create_error_response


def setup_vog_routes(app: web.Application, controller: APIController) -> None:
    """Register VOG module-specific routes."""
    # Device listing
    app.router.add_get("/api/v1/modules/vog/devices", list_vog_devices_handler)

    # Configuration
    app.router.add_get("/api/v1/modules/vog/config", get_vog_config_handler)
    app.router.add_put("/api/v1/modules/vog/config", update_vog_config_handler)

    # Data endpoints
    app.router.add_get("/api/v1/modules/vog/eye-position", get_eye_position_handler)
    app.router.add_get("/api/v1/modules/vog/pupil", get_pupil_handler)

    # Lens control
    app.router.add_post("/api/v1/modules/vog/lens", switch_lens_handler)

    # Battery status (wVOG only)
    app.router.add_get("/api/v1/modules/vog/battery", get_battery_handler)

    # Module status
    app.router.add_get("/api/v1/modules/vog/status", get_vog_status_handler)


async def list_vog_devices_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/vog/devices - List available VOG devices.

    Returns list of discovered/connected VOG devices with their types
    (sVOG for wired, wVOG for wireless).
    """
    controller: APIController = request.app["controller"]
    result = await controller.list_vog_devices()
    return web.json_response(result)


async def get_vog_config_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/vog/config - Get VOG configuration.

    Query parameters:
    - device_id: Optional device ID to get config for specific device
    """
    controller: APIController = request.app["controller"]
    device_id = request.query.get("device_id")

    result = await controller.get_vog_config(device_id)
    if not result.get("success", True):
        status = 404 if result.get("error") == "device_not_found" else 500
        return web.json_response(result, status=status)

    return web.json_response(result)


async def update_vog_config_handler(request: web.Request) -> web.Response:
    """PUT /api/v1/modules/vog/config - Update VOG configuration.

    Request body:
    {
        "device_id": "optional-device-id",
        "config": {
            "param": "value",
            ...
        }
    }
    """
    controller: APIController = request.app["controller"]

    try:
        body = await request.json()
    except Exception:
        return create_error_response(
            "INVALID_BODY",
            "Request body must be valid JSON",
            status=400,
        )

    device_id = body.get("device_id")
    config_updates = body.get("config", {})

    if not config_updates:
        return create_error_response(
            "MISSING_CONFIG",
            "Request body must include 'config' object with updates",
            status=400,
        )

    result = await controller.update_vog_config(device_id, config_updates)
    if not result.get("success"):
        status = 404 if result.get("error") == "device_not_found" else 500
        return web.json_response(result, status=status)

    return web.json_response(result)


async def get_eye_position_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/vog/eye-position - Get current eye position data.

    Query parameters:
    - device_id: Optional device ID to get data for specific device

    Returns shutter timing data (open/closed durations) from VOG devices.
    """
    controller: APIController = request.app["controller"]
    device_id = request.query.get("device_id")

    result = await controller.get_vog_eye_position(device_id)
    if not result.get("success", True):
        status = 404 if result.get("error") == "device_not_found" else 500
        return web.json_response(result, status=status)

    return web.json_response(result)


async def get_pupil_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/vog/pupil - Get pupil diameter.

    Query parameters:
    - device_id: Optional device ID to get data for specific device

    Note: VOG devices report shutter state, not direct pupil measurements.
    This endpoint returns the current shutter state data.
    """
    controller: APIController = request.app["controller"]
    device_id = request.query.get("device_id")

    result = await controller.get_vog_pupil_data(device_id)
    if not result.get("success", True):
        status = 404 if result.get("error") == "device_not_found" else 500
        return web.json_response(result, status=status)

    return web.json_response(result)


async def switch_lens_handler(request: web.Request) -> web.Response:
    """POST /api/v1/modules/vog/lens - Switch lens state.

    Request body:
    {
        "device_id": "optional-device-id",
        "lens": "A" | "B" | "X",  // X = both lenses (wVOG only, sVOG ignores)
        "state": "open" | "closed"
    }

    For sVOG devices, the 'lens' parameter is ignored (single lens only).
    For wVOG devices:
    - "A" = left lens
    - "B" = right lens
    - "X" = both lenses
    """
    controller: APIController = request.app["controller"]

    try:
        body = await request.json()
    except Exception:
        return create_error_response(
            "INVALID_BODY",
            "Request body must be valid JSON",
            status=400,
        )

    device_id = body.get("device_id")
    lens = body.get("lens", "X").upper()
    state = body.get("state", "").lower()

    if state not in ("open", "closed"):
        return create_error_response(
            "INVALID_STATE",
            "State must be 'open' or 'closed'",
            status=400,
        )

    if lens not in ("A", "B", "X"):
        return create_error_response(
            "INVALID_LENS",
            "Lens must be 'A', 'B', or 'X' (both)",
            status=400,
        )

    result = await controller.switch_vog_lens(device_id, lens, state)
    if not result.get("success"):
        status = 404 if result.get("error") == "device_not_found" else 500
        return web.json_response(result, status=status)

    return web.json_response(result)


async def get_battery_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/vog/battery - Get battery level (wVOG only).

    Query parameters:
    - device_id: Optional device ID to get battery for specific device

    Note: Battery monitoring is only available on wVOG (wireless) devices.
    sVOG devices will return an error or indicate battery is not available.
    """
    controller: APIController = request.app["controller"]
    device_id = request.query.get("device_id")

    result = await controller.get_vog_battery(device_id)
    if not result.get("success", True):
        status = 404 if result.get("error") == "device_not_found" else 500
        return web.json_response(result, status=status)

    return web.json_response(result)


async def get_vog_status_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/vog/status - Get VOG module status.

    Returns comprehensive status including:
    - Module state (running, enabled)
    - Connected devices and their types
    - Recording state
    - Session information
    """
    controller: APIController = request.app["controller"]
    result = await controller.get_vog_status()
    return web.json_response(result)
