"""Device Routes - Device discovery, connection, and scanning endpoints."""

from aiohttp import web

from ..controller import APIController
from ..middleware import create_error_response, parse_json_body, result_to_response


def setup_device_routes(app: web.Application, controller: APIController) -> None:
    """Register device routes."""
    app.router.add_get("/api/v1/devices", list_devices_handler)
    app.router.add_get("/api/v1/devices/connected", connected_devices_handler)
    app.router.add_get("/api/v1/devices/{id}", get_device_handler)
    app.router.add_post("/api/v1/devices/{id}/connect", connect_device_handler)
    app.router.add_post("/api/v1/devices/{id}/disconnect", disconnect_device_handler)
    app.router.add_get("/api/v1/devices/scanning", scanning_status_handler)
    app.router.add_post("/api/v1/devices/scanning/start", start_scanning_handler)
    app.router.add_post("/api/v1/devices/scanning/stop", stop_scanning_handler)
    app.router.add_get("/api/v1/connections", list_connections_handler)
    app.router.add_put("/api/v1/connections/{interface}/{family}", set_connection_handler)
    app.router.add_get("/api/v1/xbee/status", xbee_status_handler)
    app.router.add_post("/api/v1/xbee/rescan", xbee_rescan_handler)


def _success_status(result: dict, fail_code: int = 500) -> int:
    return 200 if result.get("success") else fail_code


async def list_devices_handler(request: web.Request) -> web.Response:
    """GET /api/v1/devices - List all discovered devices."""
    controller: APIController = request.app["controller"]
    return web.json_response({"devices": await controller.list_devices()})


async def connected_devices_handler(request: web.Request) -> web.Response:
    """GET /api/v1/devices/connected - List connected devices."""
    controller: APIController = request.app["controller"]
    return web.json_response({"connected_devices": await controller.get_connected_devices()})


async def get_device_handler(request: web.Request) -> web.Response:
    """GET /api/v1/devices/{id} - Get specific device details."""
    controller: APIController = request.app["controller"]
    device = await controller.get_device(request.match_info["id"])
    return result_to_response(device, "DEVICE_NOT_FOUND", f"Device '{request.match_info['id']}' not found")


async def connect_device_handler(request: web.Request) -> web.Response:
    """POST /api/v1/devices/{id}/connect - Connect to a device."""
    controller: APIController = request.app["controller"]
    result = await controller.connect_device(request.match_info["id"])
    return web.json_response(result, status=_success_status(result))


async def disconnect_device_handler(request: web.Request) -> web.Response:
    """POST /api/v1/devices/{id}/disconnect - Disconnect from a device."""
    controller: APIController = request.app["controller"]
    result = await controller.disconnect_device(request.match_info["id"])
    return web.json_response(result, status=_success_status(result))


async def scanning_status_handler(request: web.Request) -> web.Response:
    """GET /api/v1/devices/scanning - Get scanning status."""
    return web.json_response(await request.app["controller"].get_scanning_status())


async def start_scanning_handler(request: web.Request) -> web.Response:
    """POST /api/v1/devices/scanning/start - Start device scanning."""
    return web.json_response(await request.app["controller"].start_scanning())


async def stop_scanning_handler(request: web.Request) -> web.Response:
    """POST /api/v1/devices/scanning/stop - Stop device scanning."""
    return web.json_response(await request.app["controller"].stop_scanning())


async def list_connections_handler(request: web.Request) -> web.Response:
    """GET /api/v1/connections - List enabled connection types."""
    controller: APIController = request.app["controller"]
    return web.json_response({"connections": await controller.get_enabled_connections()})


async def set_connection_handler(request: web.Request) -> web.Response:
    """PUT /api/v1/connections/{interface}/{family} - Enable/disable connection type."""
    controller: APIController = request.app["controller"]
    body, err = await parse_json_body(request)
    if err:
        return err
    if body.get("enabled") is None:
        return create_error_response("MISSING_ENABLED", "'enabled' field (boolean) is required", status=400)
    result = await controller.set_connection_enabled(
        request.match_info["interface"], request.match_info["family"], body["enabled"]
    )
    return web.json_response(result, status=_success_status(result, 400))


async def xbee_status_handler(request: web.Request) -> web.Response:
    """GET /api/v1/xbee/status - Get XBee dongle status."""
    return web.json_response(await request.app["controller"].get_xbee_status())


async def xbee_rescan_handler(request: web.Request) -> web.Response:
    """POST /api/v1/xbee/rescan - Trigger XBee network rescan."""
    result = await request.app["controller"].xbee_rescan()
    return web.json_response(result, status=_success_status(result, 400))
