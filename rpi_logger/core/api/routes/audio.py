"""Audio Module Routes - Audio-specific API endpoints."""

from aiohttp import web

from ..controller import APIController
from ..middleware import create_error_response, parse_json_body, result_to_response


def setup_audio_routes(app: web.Application, controller: APIController) -> None:
    """Register audio module routes."""
    app.router.add_get("/api/v1/modules/audio/devices", list_audio_devices_handler)
    app.router.add_get("/api/v1/modules/audio/config", get_audio_config_handler)
    app.router.add_put("/api/v1/modules/audio/config", update_audio_config_handler)
    app.router.add_get("/api/v1/modules/audio/levels", get_audio_levels_handler)
    app.router.add_get("/api/v1/modules/audio/status", get_audio_status_handler)
    app.router.add_post("/api/v1/modules/audio/test", start_test_recording_handler)


async def list_audio_devices_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/audio/devices - List available audio input devices."""
    controller: APIController = request.app["controller"]
    return web.json_response(await controller.list_audio_devices())


async def get_audio_config_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/audio/config - Get audio-specific configuration."""
    controller: APIController = request.app["controller"]
    result = await controller.get_audio_config()
    return result_to_response(result, "MODULE_NOT_FOUND", "Audio module not found or not available")


async def update_audio_config_handler(request: web.Request) -> web.Response:
    """PUT /api/v1/modules/audio/config - Update audio configuration."""
    controller: APIController = request.app["controller"]
    body, err = await parse_json_body(request)
    if err:
        return err
    result = await controller.update_audio_config(body)
    if not result.get("success"):
        return web.json_response(result, status=404 if result.get("error") == "module_not_found" else 400)
    return web.json_response(result)


async def get_audio_levels_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/audio/levels - Get current audio input levels."""
    controller: APIController = request.app["controller"]
    return web.json_response(await controller.get_audio_levels())


async def get_audio_status_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/audio/status - Get recording status."""
    controller: APIController = request.app["controller"]
    return web.json_response(await controller.get_audio_status())


async def start_test_recording_handler(request: web.Request) -> web.Response:
    """POST /api/v1/modules/audio/test - Start test recording (1-30 seconds)."""
    controller: APIController = request.app["controller"]
    body, _ = await parse_json_body(request, required=False)
    duration = min(30, max(1, int(body.get("duration", 5)))) if body else 5
    result = await controller.start_audio_test_recording(duration)
    if not result.get("success"):
        return web.json_response(result, status=400 if result.get("error") == "no_device" else 500)
    return web.json_response(result)
