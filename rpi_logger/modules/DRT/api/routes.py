"""DRT module API routes."""

from aiohttp import web


def create_error_response(code: str, message: str, status: int = 400) -> web.Response:
    """Create a JSON error response."""
    return web.json_response(
        {"error": {"code": code, "message": message}},
        status=status
    )


def setup_drt_routes(app: web.Application, controller) -> None:
    """Register DRT-specific routes."""
    # Device listing
    app.router.add_get("/api/v1/modules/drt/devices", list_drt_devices_handler)

    # Configuration
    app.router.add_get("/api/v1/modules/drt/config", get_drt_config_handler)
    app.router.add_put("/api/v1/modules/drt/config", update_drt_config_handler)

    # Stimulus control
    app.router.add_post("/api/v1/modules/drt/stimulus", trigger_stimulus_handler)

    # Response data
    app.router.add_get("/api/v1/modules/drt/responses", get_drt_responses_handler)

    # Statistics
    app.router.add_get("/api/v1/modules/drt/statistics", get_drt_statistics_handler)

    # Battery (wDRT only)
    app.router.add_get("/api/v1/modules/drt/battery", get_drt_battery_handler)

    # Module status
    app.router.add_get("/api/v1/modules/drt/status", get_drt_status_handler)


async def list_drt_devices_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/drt/devices - List available DRT devices."""
    controller = request.app["controller"]
    result = await controller.list_drt_devices()
    return web.json_response(result)


async def get_drt_config_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/drt/config - Get DRT configuration."""
    controller = request.app["controller"]

    # Optional device_id query parameter
    device_id = request.query.get("device_id")

    result = await controller.get_drt_config(device_id)
    if not result.get("success", True) and result.get("error") == "no_devices":
        return create_error_response(
            "NO_DRT_DEVICES",
            result.get("message", "No DRT devices connected"),
            status=404,
        )

    return web.json_response(result)


async def update_drt_config_handler(request: web.Request) -> web.Response:
    """PUT /api/v1/modules/drt/config - Update DRT configuration."""
    controller = request.app["controller"]

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

    # Optional device_id in body
    device_id = body.pop("device_id", None)

    result = await controller.update_drt_config(body, device_id)
    if not result.get("success"):
        status = 404 if result.get("error") in ("no_devices", "device_not_found") else 500
        return web.json_response(result, status=status)

    return web.json_response(result)


async def trigger_stimulus_handler(request: web.Request) -> web.Response:
    """POST /api/v1/modules/drt/stimulus - Trigger manual stimulus."""
    controller = request.app["controller"]

    try:
        body = await request.json()
    except Exception:
        body = {}

    # Optional parameters
    device_id = body.get("device_id")
    on = body.get("on", True)  # Default to turning stimulus on
    duration_ms = body.get("duration_ms")  # Optional auto-off duration

    result = await controller.trigger_drt_stimulus(device_id, on, duration_ms)
    if not result.get("success"):
        status = 404 if result.get("error") in ("no_devices", "device_not_found") else 500
        return web.json_response(result, status=status)

    return web.json_response(result)


async def get_drt_responses_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/drt/responses - Get recent DRT responses."""
    controller = request.app["controller"]

    # Optional query parameters
    device_id = request.query.get("device_id")
    limit_str = request.query.get("limit", "100")

    try:
        limit = int(limit_str)
    except ValueError:
        return create_error_response(
            "INVALID_LIMIT",
            "limit must be a valid integer",
            status=400,
        )

    result = await controller.get_drt_responses(device_id, limit)
    return web.json_response(result)


async def get_drt_statistics_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/drt/statistics - Get session statistics."""
    controller = request.app["controller"]

    # Optional device_id query parameter
    device_id = request.query.get("device_id")

    result = await controller.get_drt_statistics(device_id)
    return web.json_response(result)


async def get_drt_battery_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/drt/battery - Get battery level (wDRT only)."""
    controller = request.app["controller"]

    # Optional device_id query parameter
    device_id = request.query.get("device_id")

    result = await controller.get_drt_battery(device_id)
    if not result.get("success", True) and result.get("error") == "not_wireless":
        return create_error_response(
            "NOT_WIRELESS_DEVICE",
            result.get("message", "Battery level only available for wDRT devices"),
            status=400,
        )

    return web.json_response(result)


async def get_drt_status_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/drt/status - Get DRT module status."""
    controller = request.app["controller"]
    result = await controller.get_drt_status()
    return web.json_response(result)
