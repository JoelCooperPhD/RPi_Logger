"""
Device Routes - Device discovery, connection, and scanning endpoints.
"""

from aiohttp import web

from ..controller import APIController
from ..middleware import create_error_response


def setup_device_routes(app: web.Application, controller: APIController) -> None:
    """Register device routes."""
    # Device listing and details
    app.router.add_get("/api/v1/devices", list_devices_handler)
    app.router.add_get("/api/v1/devices/connected", connected_devices_handler)
    app.router.add_get("/api/v1/devices/{id}", get_device_handler)
    app.router.add_post("/api/v1/devices/{id}/connect", connect_device_handler)
    app.router.add_post("/api/v1/devices/{id}/disconnect", disconnect_device_handler)

    # Scanning control
    app.router.add_get("/api/v1/devices/scanning", scanning_status_handler)
    app.router.add_post("/api/v1/devices/scanning/start", start_scanning_handler)
    app.router.add_post("/api/v1/devices/scanning/stop", stop_scanning_handler)

    # Connection type management
    app.router.add_get("/api/v1/connections", list_connections_handler)
    app.router.add_put("/api/v1/connections/{interface}/{family}", set_connection_handler)

    # XBee management
    app.router.add_get("/api/v1/xbee/status", xbee_status_handler)
    app.router.add_post("/api/v1/xbee/rescan", xbee_rescan_handler)


async def list_devices_handler(request: web.Request) -> web.Response:
    """GET /api/v1/devices - List all discovered devices."""
    controller: APIController = request.app["controller"]
    devices = await controller.list_devices()
    return web.json_response({"devices": devices})


async def connected_devices_handler(request: web.Request) -> web.Response:
    """GET /api/v1/devices/connected - List connected devices."""
    controller: APIController = request.app["controller"]
    devices = await controller.get_connected_devices()
    return web.json_response({"connected_devices": devices})


async def get_device_handler(request: web.Request) -> web.Response:
    """GET /api/v1/devices/{id} - Get specific device details."""
    controller: APIController = request.app["controller"]
    device_id = request.match_info["id"]

    device = await controller.get_device(device_id)
    if not device:
        return create_error_response(
            "DEVICE_NOT_FOUND",
            f"Device '{device_id}' not found",
            status=404,
        )

    return web.json_response(device)


async def connect_device_handler(request: web.Request) -> web.Response:
    """POST /api/v1/devices/{id}/connect - Connect to a device."""
    controller: APIController = request.app["controller"]
    device_id = request.match_info["id"]

    result = await controller.connect_device(device_id)
    status = 200 if result["success"] else 500
    return web.json_response(result, status=status)


async def disconnect_device_handler(request: web.Request) -> web.Response:
    """POST /api/v1/devices/{id}/disconnect - Disconnect from a device."""
    controller: APIController = request.app["controller"]
    device_id = request.match_info["id"]

    result = await controller.disconnect_device(device_id)
    status = 200 if result["success"] else 500
    return web.json_response(result, status=status)


async def scanning_status_handler(request: web.Request) -> web.Response:
    """GET /api/v1/devices/scanning - Get scanning status."""
    controller: APIController = request.app["controller"]
    result = await controller.get_scanning_status()
    return web.json_response(result)


async def start_scanning_handler(request: web.Request) -> web.Response:
    """POST /api/v1/devices/scanning/start - Start device scanning."""
    controller: APIController = request.app["controller"]
    result = await controller.start_scanning()
    return web.json_response(result)


async def stop_scanning_handler(request: web.Request) -> web.Response:
    """POST /api/v1/devices/scanning/stop - Stop device scanning."""
    controller: APIController = request.app["controller"]
    result = await controller.stop_scanning()
    return web.json_response(result)


async def list_connections_handler(request: web.Request) -> web.Response:
    """GET /api/v1/connections - List enabled connection types."""
    controller: APIController = request.app["controller"]
    connections = await controller.get_enabled_connections()
    return web.json_response({"connections": connections})


async def set_connection_handler(request: web.Request) -> web.Response:
    """PUT /api/v1/connections/{interface}/{family} - Enable/disable connection type."""
    controller: APIController = request.app["controller"]
    interface = request.match_info["interface"]
    family = request.match_info["family"]

    try:
        body = await request.json()
    except Exception:
        return create_error_response(
            "INVALID_BODY",
            "Request body must be valid JSON",
            status=400,
        )

    enabled = body.get("enabled")
    if enabled is None:
        return create_error_response(
            "MISSING_ENABLED",
            "Request body must include 'enabled' field (boolean)",
            status=400,
        )

    result = await controller.set_connection_enabled(interface, family, enabled)
    status = 200 if result["success"] else 400
    return web.json_response(result, status=status)


async def xbee_status_handler(request: web.Request) -> web.Response:
    """GET /api/v1/xbee/status - Get XBee dongle status."""
    controller: APIController = request.app["controller"]
    result = await controller.get_xbee_status()
    return web.json_response(result)


async def xbee_rescan_handler(request: web.Request) -> web.Response:
    """POST /api/v1/xbee/rescan - Trigger XBee network rescan."""
    controller: APIController = request.app["controller"]
    result = await controller.xbee_rescan()
    status = 200 if result["success"] else 400
    return web.json_response(result, status=status)
