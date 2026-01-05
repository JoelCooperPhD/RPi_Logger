"""
Audio Module Routes - Audio-specific API endpoints for device discovery,
configuration, recording control, and level monitoring.

Endpoints:
- GET  /api/v1/modules/audio/devices  - List available audio input devices
- GET  /api/v1/modules/audio/config   - Get audio-specific configuration
- PUT  /api/v1/modules/audio/config   - Update audio configuration
- GET  /api/v1/modules/audio/levels   - Get current audio input levels
- POST /api/v1/modules/audio/test     - Start test recording
- GET  /api/v1/modules/audio/status   - Get recording status
"""

from aiohttp import web

from ..controller import APIController
from ..middleware import create_error_response


def setup_audio_routes(app: web.Application, controller: APIController) -> None:
    """Register audio module routes."""
    # Device listing
    app.router.add_get("/api/v1/modules/audio/devices", list_audio_devices_handler)

    # Audio configuration
    app.router.add_get("/api/v1/modules/audio/config", get_audio_config_handler)
    app.router.add_put("/api/v1/modules/audio/config", update_audio_config_handler)

    # Audio levels and status
    app.router.add_get("/api/v1/modules/audio/levels", get_audio_levels_handler)
    app.router.add_get("/api/v1/modules/audio/status", get_audio_status_handler)

    # Test recording
    app.router.add_post("/api/v1/modules/audio/test", start_test_recording_handler)


async def list_audio_devices_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/audio/devices - List available audio input devices.

    Returns a list of audio devices discovered by the system, including
    device IDs, names, channel counts, and sample rates.
    """
    controller: APIController = request.app["controller"]
    result = await controller.list_audio_devices()
    return web.json_response(result)


async def get_audio_config_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/audio/config - Get audio-specific configuration.

    Returns current audio module configuration including sample rate,
    output directory, session prefix, and other settings.
    """
    controller: APIController = request.app["controller"]
    result = await controller.get_audio_config()

    if result is None:
        return create_error_response(
            "MODULE_NOT_FOUND",
            "Audio module not found or not available",
            status=404,
        )

    return web.json_response(result)


async def update_audio_config_handler(request: web.Request) -> web.Response:
    """PUT /api/v1/modules/audio/config - Update audio configuration.

    Request body should contain configuration key-value pairs to update.
    Valid keys include: sample_rate, output_dir, session_prefix, log_level,
    meter_refresh_interval, recorder_start_timeout, recorder_stop_timeout.
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

    result = await controller.update_audio_config(body)

    if not result.get("success"):
        status = 404 if result.get("error") == "module_not_found" else 400
        return web.json_response(result, status=status)

    return web.json_response(result)


async def get_audio_levels_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/audio/levels - Get current audio input levels.

    Returns the current RMS and peak audio levels in dB for the active
    audio device. Returns null values if no device is active.
    """
    controller: APIController = request.app["controller"]
    result = await controller.get_audio_levels()
    return web.json_response(result)


async def get_audio_status_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/audio/status - Get recording status.

    Returns current audio module status including:
    - Whether recording is active
    - Current trial number
    - Assigned device information
    - Session directory
    """
    controller: APIController = request.app["controller"]
    result = await controller.get_audio_status()
    return web.json_response(result)


async def start_test_recording_handler(request: web.Request) -> web.Response:
    """POST /api/v1/modules/audio/test - Start test recording.

    Starts a short test recording to verify audio device functionality.

    Optional request body parameters:
        duration: Test duration in seconds (default: 5, max: 30)

    The test recording is saved to the current session directory if a
    session is active, otherwise to the idle session directory.
    """
    controller: APIController = request.app["controller"]

    # Parse optional parameters
    duration = 5  # Default 5 seconds

    try:
        body = await request.json()
        if body:
            duration = min(30, max(1, int(body.get("duration", duration))))
    except Exception:
        # No body or invalid JSON is okay - use defaults
        pass

    result = await controller.start_audio_test_recording(duration)

    if not result.get("success"):
        status = 400 if result.get("error") == "no_device" else 500
        return web.json_response(result, status=status)

    return web.json_response(result)
