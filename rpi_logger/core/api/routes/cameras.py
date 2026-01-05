"""Cameras Routes - Camera-specific API endpoints."""

from aiohttp import web

from ..controller import APIController
from ..middleware import create_error_response, parse_json_body, result_to_response


def setup_camera_routes(app: web.Application, controller: APIController) -> None:
    """Register camera-specific routes."""
    app.router.add_get("/api/v1/modules/cameras/devices", list_camera_devices_handler)
    app.router.add_get("/api/v1/modules/cameras/config", get_camera_config_handler)
    app.router.add_put("/api/v1/modules/cameras/config", update_camera_config_handler)
    app.router.add_get("/api/v1/modules/cameras/status", get_cameras_status_handler)
    app.router.add_get("/api/v1/modules/cameras/{camera_id}/preview", get_camera_preview_handler)
    app.router.add_post("/api/v1/modules/cameras/{camera_id}/snapshot", capture_snapshot_handler)
    app.router.add_put("/api/v1/modules/cameras/{camera_id}/resolution", set_camera_resolution_handler)
    app.router.add_put("/api/v1/modules/cameras/{camera_id}/fps", set_camera_fps_handler)


async def list_camera_devices_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/cameras/devices - List available USB cameras."""
    controller: APIController = request.app["controller"]
    return web.json_response(await controller.list_camera_devices())


async def get_camera_config_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/cameras/config - Get camera configuration."""
    controller: APIController = request.app["controller"]
    return web.json_response(await controller.get_camera_config())


async def update_camera_config_handler(request: web.Request) -> web.Response:
    """PUT /api/v1/modules/cameras/config - Update camera configuration."""
    controller: APIController = request.app["controller"]
    body, err = await parse_json_body(request, required=False)
    if err:
        return err
    result = await controller.update_camera_config(body)
    return web.json_response(result, status=200 if result.get("success") else 400)


async def get_camera_preview_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/cameras/{camera_id}/preview - Get preview frame (base64)."""
    controller: APIController = request.app["controller"]
    result = await controller.get_camera_preview(request.match_info["camera_id"])
    return result_to_response(result, "CAMERA_NOT_FOUND", "Camera not found or not active")


async def capture_snapshot_handler(request: web.Request) -> web.Response:
    """POST /api/v1/modules/cameras/{camera_id}/snapshot - Capture single frame."""
    controller: APIController = request.app["controller"]
    body, _ = await parse_json_body(request, required=False)
    result = await controller.capture_camera_snapshot(
        request.match_info["camera_id"],
        save_path=body.get("save_path"),
        format=body.get("format", "jpeg"),
    )
    return result_to_response(result, "CAMERA_NOT_FOUND", "Camera not found or not active")


async def get_cameras_status_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/cameras/status - Get recording status for all cameras."""
    controller: APIController = request.app["controller"]
    return web.json_response(await controller.get_cameras_status())


async def set_camera_resolution_handler(request: web.Request) -> web.Response:
    """PUT /api/v1/modules/cameras/{camera_id}/resolution - Set resolution."""
    controller: APIController = request.app["controller"]
    body, err = await parse_json_body(request)
    if err:
        return err

    width, height = body.get("width"), body.get("height")
    if width is None or height is None:
        return create_error_response("MISSING_PARAMETERS", "'width' and 'height' are required", status=400)
    try:
        width, height = int(width), int(height)
    except (ValueError, TypeError):
        return create_error_response("INVALID_PARAMETERS", "Width and height must be integers", status=400)

    result = await controller.set_camera_resolution(request.match_info["camera_id"], width, height)
    return result_to_response(result, "CAMERA_NOT_FOUND", "Camera not found or not active")


async def set_camera_fps_handler(request: web.Request) -> web.Response:
    """PUT /api/v1/modules/cameras/{camera_id}/fps - Set frame rate."""
    controller: APIController = request.app["controller"]
    body, err = await parse_json_body(request)
    if err:
        return err

    fps = body.get("fps")
    if fps is None:
        return create_error_response("MISSING_PARAMETERS", "'fps' is required", status=400)
    try:
        fps = float(fps)
    except (ValueError, TypeError):
        return create_error_response("INVALID_PARAMETERS", "FPS must be a number", status=400)
    if fps <= 0:
        return create_error_response("INVALID_PARAMETERS", "FPS must be positive", status=400)

    result = await controller.set_camera_fps(request.match_info["camera_id"], fps)
    return result_to_response(result, "CAMERA_NOT_FOUND", "Camera not found or not active")
