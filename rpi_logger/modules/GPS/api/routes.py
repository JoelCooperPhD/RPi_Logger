"""GPS module API routes."""

from aiohttp import web


_GPS_NOT_FOUND = ("GPS_NOT_AVAILABLE", "GPS module not running or no devices connected")


def result_to_response(result, error_code: str, error_msg: str) -> web.Response:
    """Convert result to JSON response, handling None as error."""
    if result is None:
        return web.json_response(
            {"error": {"code": error_code, "message": error_msg}},
            status=404
        )
    return web.json_response(result)


def setup_gps_routes(app: web.Application, controller) -> None:
    """Register GPS-specific routes."""
    app.router.add_get("/api/v1/modules/gps/devices", gps_devices_handler)
    app.router.add_get("/api/v1/modules/gps/config", gps_config_handler)
    app.router.add_put("/api/v1/modules/gps/config", update_gps_config_handler)
    app.router.add_get("/api/v1/modules/gps/position", gps_position_handler)
    app.router.add_get("/api/v1/modules/gps/satellites", gps_satellites_handler)
    app.router.add_get("/api/v1/modules/gps/fix", gps_fix_handler)
    app.router.add_get("/api/v1/modules/gps/nmea/raw", gps_nmea_raw_handler)
    app.router.add_get("/api/v1/modules/gps/status", gps_status_handler)


async def gps_devices_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/gps/devices - List available GPS devices."""
    controller = request.app["controller"]
    return web.json_response(await controller.get_gps_devices())


async def gps_config_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/gps/config - Get GPS configuration."""
    controller = request.app["controller"]
    return result_to_response(await controller.get_gps_config(), *_GPS_NOT_FOUND)


async def update_gps_config_handler(request: web.Request) -> web.Response:
    """PUT /api/v1/modules/gps/config - Update GPS configuration."""
    controller = request.app["controller"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"error": {"code": "INVALID_BODY", "message": "Request body must be valid JSON"}},
            status=400
        )
    result = await controller.update_gps_config(body)
    return web.json_response(result, status=200 if result.get("success") else 400)


async def gps_position_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/gps/position - Get current GPS position."""
    controller = request.app["controller"]
    result = await controller.get_gps_position(request.query.get("device_id"))
    return result_to_response(result, *_GPS_NOT_FOUND)


async def gps_satellites_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/gps/satellites - Get satellite information."""
    controller = request.app["controller"]
    result = await controller.get_gps_satellites(request.query.get("device_id"))
    return result_to_response(result, *_GPS_NOT_FOUND)


async def gps_fix_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/gps/fix - Get GPS fix quality and status."""
    controller = request.app["controller"]
    result = await controller.get_gps_fix(request.query.get("device_id"))
    return result_to_response(result, *_GPS_NOT_FOUND)


async def gps_nmea_raw_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/gps/nmea/raw - Get raw NMEA sentences."""
    controller = request.app["controller"]
    try:
        limit = int(request.query.get("limit", 0))
    except ValueError:
        limit = 0
    result = await controller.get_gps_nmea_raw(request.query.get("device_id"), limit)
    return result_to_response(result, *_GPS_NOT_FOUND)


async def gps_status_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/gps/status - Get GPS module status."""
    controller = request.app["controller"]
    result = await controller.get_gps_status()
    return result_to_response(result, "GPS_NOT_AVAILABLE", "GPS module not found")
