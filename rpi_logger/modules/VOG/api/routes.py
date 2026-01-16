"""VOG module API routes."""

from aiohttp import web


def create_error_response(code: str, message: str, status: int = 400) -> web.Response:
    """Create a JSON error response."""
    return web.json_response(
        {"error": {"code": code, "message": message}},
        status=status
    )


def setup_vog_routes(app: web.Application, controller) -> None:
    """Register VOG-specific routes."""
    app.router.add_get("/api/v1/modules/vog/devices", list_vog_devices_handler)
    app.router.add_get("/api/v1/modules/vog/config", get_vog_config_handler)
    app.router.add_put("/api/v1/modules/vog/config", update_vog_config_handler)
    app.router.add_get("/api/v1/modules/vog/eye-position", get_eye_position_handler)
    app.router.add_get("/api/v1/modules/vog/pupil", get_pupil_data_handler)
    app.router.add_post("/api/v1/modules/vog/lens", switch_lens_handler)
    app.router.add_get("/api/v1/modules/vog/battery", get_battery_handler)
    app.router.add_get("/api/v1/modules/vog/status", get_status_handler)


async def list_vog_devices_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/vog/devices - List available VOG devices."""
    controller = request.app["controller"]
    return web.json_response(await controller.list_vog_devices())


async def get_vog_config_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/vog/config - Get VOG configuration."""
    controller = request.app["controller"]
    device_id = request.query.get("device_id")
    result = await controller.get_vog_config(device_id)
    if not result.get("success", True):
        return web.json_response(result, status=404 if result.get("error") == "device_not_found" else 400)
    return web.json_response(result)


async def update_vog_config_handler(request: web.Request) -> web.Response:
    """PUT /api/v1/modules/vog/config - Update VOG configuration."""
    controller = request.app["controller"]
    try:
        body = await request.json()
    except Exception:
        return create_error_response("INVALID_BODY", "Request body must be valid JSON")

    device_id = body.pop("device_id", None)
    result = await controller.update_vog_config(device_id, body)
    if not result.get("success"):
        return web.json_response(result, status=404 if result.get("error") == "device_not_found" else 400)
    return web.json_response(result)


async def get_eye_position_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/vog/eye-position - Get eye position data."""
    controller = request.app["controller"]
    device_id = request.query.get("device_id")
    result = await controller.get_vog_eye_position(device_id)
    if not result.get("success", True):
        return web.json_response(result, status=404 if "not_found" in result.get("error", "") else 400)
    return web.json_response(result)


async def get_pupil_data_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/vog/pupil - Get pupil/shutter state data."""
    controller = request.app["controller"]
    device_id = request.query.get("device_id")
    result = await controller.get_vog_pupil_data(device_id)
    return web.json_response(result)


async def switch_lens_handler(request: web.Request) -> web.Response:
    """POST /api/v1/modules/vog/lens - Switch lens state."""
    controller = request.app["controller"]
    try:
        body = await request.json()
    except Exception:
        return create_error_response("INVALID_BODY", "Request body must be valid JSON")

    device_id = body.get("device_id")
    lens = body.get("lens", "X")  # Default to both lenses
    state = body.get("state", "open")  # Default to open

    if state not in ("open", "closed"):
        return create_error_response("INVALID_STATE", "state must be 'open' or 'closed'")
    if lens not in ("A", "B", "X"):
        return create_error_response("INVALID_LENS", "lens must be 'A', 'B', or 'X'")

    result = await controller.switch_vog_lens(device_id, lens, state)
    if not result.get("success"):
        return web.json_response(result, status=404 if result.get("error") == "device_not_found" else 400)
    return web.json_response(result)


async def get_battery_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/vog/battery - Get battery level (wVOG only)."""
    controller = request.app["controller"]
    device_id = request.query.get("device_id")
    result = await controller.get_vog_battery(device_id)
    if not result.get("success", True):
        return web.json_response(result, status=404 if "not_found" in result.get("error", "") else 400)
    return web.json_response(result)


async def get_status_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/vog/status - Get VOG module status."""
    controller = request.app["controller"]
    result = await controller.get_vog_status()
    if not result.get("success", True):
        return web.json_response(result, status=404)
    return web.json_response(result)
