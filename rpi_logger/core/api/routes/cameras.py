"""
Cameras Routes - Camera-specific API endpoints.

Provides endpoints for:
- Listing available USB cameras
- Getting/updating camera configuration
- Preview frame capture (base64)
- Single frame snapshot
- Recording status
- Resolution and FPS settings
"""

from aiohttp import web

from ..controller import APIController
from ..middleware import create_error_response


def setup_camera_routes(app: web.Application, controller: APIController) -> None:
    """Register camera-specific routes."""
    # Camera device listing
    app.router.add_get("/api/v1/modules/cameras/devices", list_camera_devices_handler)

    # Camera configuration
    app.router.add_get("/api/v1/modules/cameras/config", get_camera_config_handler)
    app.router.add_put("/api/v1/modules/cameras/config", update_camera_config_handler)

    # Recording status
    app.router.add_get("/api/v1/modules/cameras/status", get_cameras_status_handler)

    # Per-camera operations (must come after /status to avoid route conflicts)
    app.router.add_get(
        "/api/v1/modules/cameras/{camera_id}/preview", get_camera_preview_handler
    )
    app.router.add_post(
        "/api/v1/modules/cameras/{camera_id}/snapshot", capture_snapshot_handler
    )
    app.router.add_put(
        "/api/v1/modules/cameras/{camera_id}/resolution", set_camera_resolution_handler
    )
    app.router.add_put(
        "/api/v1/modules/cameras/{camera_id}/fps", set_camera_fps_handler
    )


async def list_camera_devices_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/cameras/devices - List available USB cameras."""
    controller: APIController = request.app["controller"]
    result = await controller.list_camera_devices()
    return web.json_response(result)


async def get_camera_config_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/cameras/config - Get camera configuration."""
    controller: APIController = request.app["controller"]
    result = await controller.get_camera_config()
    return web.json_response(result)


async def update_camera_config_handler(request: web.Request) -> web.Response:
    """PUT /api/v1/modules/cameras/config - Update camera configuration."""
    controller: APIController = request.app["controller"]

    try:
        body = await request.json()
    except Exception:
        return create_error_response(
            "INVALID_BODY",
            "Request body must be valid JSON",
            status=400,
        )

    result = await controller.update_camera_config(body)
    status = 200 if result.get("success") else 400
    return web.json_response(result, status=status)


async def get_camera_preview_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/cameras/{camera_id}/preview - Get preview frame (base64)."""
    controller: APIController = request.app["controller"]
    camera_id = request.match_info["camera_id"]

    result = await controller.get_camera_preview(camera_id)
    if not result:
        return create_error_response(
            "CAMERA_NOT_FOUND",
            f"Camera '{camera_id}' not found or not active",
            status=404,
        )

    if result.get("error"):
        return create_error_response(
            result.get("error_code", "PREVIEW_ERROR"),
            result.get("error"),
            status=400,
        )

    return web.json_response(result)


async def capture_snapshot_handler(request: web.Request) -> web.Response:
    """POST /api/v1/modules/cameras/{camera_id}/snapshot - Capture single frame."""
    controller: APIController = request.app["controller"]
    camera_id = request.match_info["camera_id"]

    # Optional body with save path or format
    try:
        body = await request.json()
    except Exception:
        body = {}

    result = await controller.capture_camera_snapshot(
        camera_id,
        save_path=body.get("save_path"),
        format=body.get("format", "jpeg"),
    )

    if not result:
        return create_error_response(
            "CAMERA_NOT_FOUND",
            f"Camera '{camera_id}' not found or not active",
            status=404,
        )

    if result.get("error"):
        return create_error_response(
            result.get("error_code", "SNAPSHOT_ERROR"),
            result.get("error"),
            status=400,
        )

    status = 200 if result.get("success") else 400
    return web.json_response(result, status=status)


async def get_cameras_status_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/cameras/status - Get recording status for all cameras."""
    controller: APIController = request.app["controller"]
    result = await controller.get_cameras_status()
    return web.json_response(result)


async def set_camera_resolution_handler(request: web.Request) -> web.Response:
    """PUT /api/v1/modules/cameras/{camera_id}/resolution - Set resolution."""
    controller: APIController = request.app["controller"]
    camera_id = request.match_info["camera_id"]

    try:
        body = await request.json()
    except Exception:
        return create_error_response(
            "INVALID_BODY",
            "Request body must be valid JSON",
            status=400,
        )

    width = body.get("width")
    height = body.get("height")

    if width is None or height is None:
        return create_error_response(
            "MISSING_PARAMETERS",
            "Request body must include 'width' and 'height' fields",
            status=400,
        )

    try:
        width = int(width)
        height = int(height)
    except (ValueError, TypeError):
        return create_error_response(
            "INVALID_PARAMETERS",
            "Width and height must be integers",
            status=400,
        )

    result = await controller.set_camera_resolution(camera_id, width, height)
    if not result:
        return create_error_response(
            "CAMERA_NOT_FOUND",
            f"Camera '{camera_id}' not found or not active",
            status=404,
        )

    status = 200 if result.get("success") else 400
    return web.json_response(result, status=status)


async def set_camera_fps_handler(request: web.Request) -> web.Response:
    """PUT /api/v1/modules/cameras/{camera_id}/fps - Set frame rate."""
    controller: APIController = request.app["controller"]
    camera_id = request.match_info["camera_id"]

    try:
        body = await request.json()
    except Exception:
        return create_error_response(
            "INVALID_BODY",
            "Request body must be valid JSON",
            status=400,
        )

    fps = body.get("fps")
    if fps is None:
        return create_error_response(
            "MISSING_PARAMETERS",
            "Request body must include 'fps' field",
            status=400,
        )

    try:
        fps = float(fps)
    except (ValueError, TypeError):
        return create_error_response(
            "INVALID_PARAMETERS",
            "FPS must be a number",
            status=400,
        )

    if fps <= 0:
        return create_error_response(
            "INVALID_PARAMETERS",
            "FPS must be a positive number",
            status=400,
        )

    result = await controller.set_camera_fps(camera_id, fps)
    if not result:
        return create_error_response(
            "CAMERA_NOT_FOUND",
            f"Camera '{camera_id}' not found or not active",
            status=404,
        )

    status = 200 if result.get("success") else 400
    return web.json_response(result, status=status)
