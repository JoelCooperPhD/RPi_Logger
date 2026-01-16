"""EyeTracker module API routes."""

from aiohttp import web


def result_to_response(result, error_code: str, error_msg: str) -> web.Response:
    """Convert result to JSON response, handling None as error."""
    if result is None:
        return web.json_response(
            {"error": {"code": error_code, "message": error_msg}},
            status=404
        )
    return web.json_response(result)


def setup_eyetracker_routes(app: web.Application, controller) -> None:
    """Register EyeTracker-specific routes."""
    app.router.add_get("/api/v1/modules/eyetracker/devices", list_devices_handler)
    app.router.add_get("/api/v1/modules/eyetracker/config", get_config_handler)
    app.router.add_put("/api/v1/modules/eyetracker/config", update_config_handler)
    app.router.add_get("/api/v1/modules/eyetracker/gaze", get_gaze_handler)
    app.router.add_get("/api/v1/modules/eyetracker/imu", get_imu_handler)
    app.router.add_get("/api/v1/modules/eyetracker/events", get_events_handler)
    app.router.add_post("/api/v1/modules/eyetracker/calibration", start_calibration_handler)
    app.router.add_get("/api/v1/modules/eyetracker/calibration", get_calibration_status_handler)
    app.router.add_get("/api/v1/modules/eyetracker/status", get_status_handler)
    app.router.add_get("/api/v1/modules/eyetracker/streams", get_stream_settings_handler)
    app.router.add_put("/api/v1/modules/eyetracker/streams/{stream_type}", set_stream_enabled_handler)
    app.router.add_post("/api/v1/modules/eyetracker/preview/start", start_preview_handler)
    app.router.add_post("/api/v1/modules/eyetracker/preview/stop", stop_preview_handler)


async def list_devices_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/eyetracker/devices - List available eye trackers."""
    controller = request.app["controller"]
    return web.json_response(await controller.list_eyetracker_devices())


async def get_config_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/eyetracker/config - Get configuration."""
    controller = request.app["controller"]
    result = await controller.get_eyetracker_config()
    return result_to_response(result, "MODULE_NOT_FOUND", "EyeTracker module not found")


async def update_config_handler(request: web.Request) -> web.Response:
    """PUT /api/v1/modules/eyetracker/config - Update configuration."""
    controller = request.app["controller"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"error": {"code": "INVALID_BODY", "message": "Request body must be valid JSON"}},
            status=400
        )
    result = await controller.update_eyetracker_config(body)
    return web.json_response(result, status=200 if result.get("success") else 400)


async def get_gaze_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/eyetracker/gaze - Get current gaze data."""
    controller = request.app["controller"]
    result = await controller.get_eyetracker_gaze_data()
    return result_to_response(result, "DATA_UNAVAILABLE", "Gaze data not available")


async def get_imu_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/eyetracker/imu - Get current IMU data."""
    controller = request.app["controller"]
    result = await controller.get_eyetracker_imu_data()
    return result_to_response(result, "DATA_UNAVAILABLE", "IMU data not available")


async def get_events_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/eyetracker/events - Get recent eye events."""
    controller = request.app["controller"]
    try:
        limit = int(request.query.get("limit", "10"))
    except ValueError:
        limit = 10
    result = await controller.get_eyetracker_events(limit)
    return result_to_response(result, "DATA_UNAVAILABLE", "Event data not available")


async def start_calibration_handler(request: web.Request) -> web.Response:
    """POST /api/v1/modules/eyetracker/calibration - Start calibration."""
    controller = request.app["controller"]
    result = await controller.start_eyetracker_calibration()
    return web.json_response(result, status=200 if result.get("success") else 400)


async def get_calibration_status_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/eyetracker/calibration - Get calibration status."""
    controller = request.app["controller"]
    result = await controller.get_eyetracker_calibration_status()
    return result_to_response(result, "STATUS_UNAVAILABLE", "Calibration status not available")


async def get_status_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/eyetracker/status - Get module status."""
    controller = request.app["controller"]
    result = await controller.get_eyetracker_status()
    return web.json_response(result)


async def get_stream_settings_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/eyetracker/streams - Get stream settings."""
    controller = request.app["controller"]
    result = await controller.get_eyetracker_stream_settings()
    return result_to_response(result, "SETTINGS_UNAVAILABLE", "Stream settings not available")


async def set_stream_enabled_handler(request: web.Request) -> web.Response:
    """PUT /api/v1/modules/eyetracker/streams/{stream_type} - Enable/disable stream."""
    controller = request.app["controller"]
    stream_type = request.match_info["stream_type"]

    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"error": {"code": "INVALID_BODY", "message": "Request body must be valid JSON"}},
            status=400
        )

    enabled = body.get("enabled", True)
    result = await controller.set_eyetracker_stream_enabled(stream_type, enabled)
    return web.json_response(result, status=200 if result.get("success") else 400)


async def start_preview_handler(request: web.Request) -> web.Response:
    """POST /api/v1/modules/eyetracker/preview/start - Start preview."""
    controller = request.app["controller"]
    result = await controller.start_eyetracker_preview()
    return web.json_response(result, status=200 if result.get("success") else 400)


async def stop_preview_handler(request: web.Request) -> web.Response:
    """POST /api/v1/modules/eyetracker/preview/stop - Stop preview."""
    controller = request.app["controller"]
    result = await controller.stop_eyetracker_preview()
    return web.json_response(result, status=200 if result.get("success") else 400)
