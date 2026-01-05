"""
GPS Routes - GPS module-specific API endpoints.

Provides direct access to GPS functionality without going through
the generic module command interface.
"""

from aiohttp import web

from ..controller import APIController
from ..middleware import create_error_response


def setup_gps_routes(app: web.Application, controller: APIController) -> None:
    """Register GPS-specific routes."""
    # Device discovery
    app.router.add_get("/api/v1/modules/gps/devices", gps_devices_handler)

    # Configuration
    app.router.add_get("/api/v1/modules/gps/config", gps_config_handler)
    app.router.add_put("/api/v1/modules/gps/config", update_gps_config_handler)

    # Position and navigation data
    app.router.add_get("/api/v1/modules/gps/position", gps_position_handler)
    app.router.add_get("/api/v1/modules/gps/satellites", gps_satellites_handler)
    app.router.add_get("/api/v1/modules/gps/fix", gps_fix_handler)

    # Raw data access
    app.router.add_get("/api/v1/modules/gps/nmea/raw", gps_nmea_raw_handler)

    # Module status
    app.router.add_get("/api/v1/modules/gps/status", gps_status_handler)


async def gps_devices_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/gps/devices - List available GPS devices.

    Returns a list of GPS devices that have been discovered or are
    currently connected to the system.
    """
    controller: APIController = request.app["controller"]
    result = await controller.get_gps_devices()
    return web.json_response(result)


async def gps_config_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/gps/config - Get GPS configuration.

    Returns the current GPS module configuration including serial port
    settings, map settings, and UI preferences.
    """
    controller: APIController = request.app["controller"]
    result = await controller.get_gps_config()

    if result is None:
        return create_error_response(
            "GPS_NOT_AVAILABLE",
            "GPS module not found or not configured",
            status=404,
        )

    return web.json_response(result)


async def update_gps_config_handler(request: web.Request) -> web.Response:
    """PUT /api/v1/modules/gps/config - Update GPS configuration.

    Request body should contain configuration key-value pairs to update.
    Only provided keys will be modified.

    Example body:
        {"baud_rate": 115200, "nmea_history": 50}
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

    if not body:
        return create_error_response(
            "EMPTY_BODY",
            "Request body must contain configuration updates",
            status=400,
        )

    result = await controller.update_gps_config(body)
    status = 200 if result.get("success") else 400
    return web.json_response(result, status=status)


async def gps_position_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/gps/position - Get current GPS position.

    Returns the current position (latitude, longitude, altitude) if
    a valid GPS fix is available.

    Query parameters:
        device_id: Optional device ID to get position from specific device
    """
    controller: APIController = request.app["controller"]
    device_id = request.query.get("device_id")

    result = await controller.get_gps_position(device_id)

    if result is None:
        return create_error_response(
            "GPS_NOT_AVAILABLE",
            "GPS module not running or no devices connected",
            status=404,
        )

    return web.json_response(result)


async def gps_satellites_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/gps/satellites - Get satellite information.

    Returns satellite tracking information including:
    - Number of satellites in use
    - Number of satellites in view
    - DOP values (HDOP, VDOP, PDOP)

    Query parameters:
        device_id: Optional device ID to get satellites from specific device
    """
    controller: APIController = request.app["controller"]
    device_id = request.query.get("device_id")

    result = await controller.get_gps_satellites(device_id)

    if result is None:
        return create_error_response(
            "GPS_NOT_AVAILABLE",
            "GPS module not running or no devices connected",
            status=404,
        )

    return web.json_response(result)


async def gps_fix_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/gps/fix - Get GPS fix quality and status.

    Returns comprehensive fix information including:
    - Fix validity
    - Fix quality (0=invalid, 1=GPS fix, 2=DGPS fix, etc.)
    - Fix mode (2D/3D)
    - Age of fix

    Query parameters:
        device_id: Optional device ID to get fix from specific device
    """
    controller: APIController = request.app["controller"]
    device_id = request.query.get("device_id")

    result = await controller.get_gps_fix(device_id)

    if result is None:
        return create_error_response(
            "GPS_NOT_AVAILABLE",
            "GPS module not running or no devices connected",
            status=404,
        )

    return web.json_response(result)


async def gps_nmea_raw_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/gps/nmea/raw - Get raw NMEA sentences.

    Returns the most recent raw NMEA sentences received from the GPS device.
    The number of sentences returned depends on the nmea_history configuration.

    Query parameters:
        device_id: Optional device ID to get NMEA from specific device
        limit: Maximum number of sentences to return (default: all available)
    """
    controller: APIController = request.app["controller"]
    device_id = request.query.get("device_id")

    try:
        limit = int(request.query.get("limit", 0))
    except ValueError:
        limit = 0

    result = await controller.get_gps_nmea_raw(device_id, limit)

    if result is None:
        return create_error_response(
            "GPS_NOT_AVAILABLE",
            "GPS module not running or no devices connected",
            status=404,
        )

    return web.json_response(result)


async def gps_status_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/gps/status - Get GPS module status.

    Returns overall GPS module status including:
    - Module running state
    - Recording state
    - Connected devices and their connection status
    - Current session/trial information
    """
    controller: APIController = request.app["controller"]
    result = await controller.get_gps_status()

    if result is None:
        return create_error_response(
            "GPS_NOT_AVAILABLE",
            "GPS module not found",
            status=404,
        )

    return web.json_response(result)
