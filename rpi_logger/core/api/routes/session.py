"""
Session Routes - Session and trial management endpoints.
"""

from aiohttp import web

from ..controller import APIController
from ..middleware import create_error_response


def setup_session_routes(app: web.Application, controller: APIController) -> None:
    """Register session and trial routes."""
    # Session management
    app.router.add_get("/api/v1/session", get_session_handler)
    app.router.add_post("/api/v1/session/start", start_session_handler)
    app.router.add_post("/api/v1/session/stop", stop_session_handler)
    app.router.add_get("/api/v1/session/directory", get_directory_handler)
    app.router.add_put("/api/v1/session/directory", set_directory_handler)
    app.router.add_get("/api/v1/session/recording", recording_status_handler)

    # Trial management
    app.router.add_get("/api/v1/trial", get_trial_handler)
    app.router.add_post("/api/v1/trial/start", start_trial_handler)
    app.router.add_post("/api/v1/trial/stop", stop_trial_handler)
    app.router.add_get("/api/v1/trial/counter", trial_counter_handler)


async def get_session_handler(request: web.Request) -> web.Response:
    """GET /api/v1/session - Get current session info."""
    controller: APIController = request.app["controller"]
    result = await controller.get_session_info()
    return web.json_response(result)


async def start_session_handler(request: web.Request) -> web.Response:
    """POST /api/v1/session/start - Start a recording session."""
    controller: APIController = request.app["controller"]

    try:
        body = await request.json()
    except Exception:
        body = {}

    directory = body.get("directory")

    result = await controller.start_session(directory)
    status = 200 if result.get("success") else 400
    return web.json_response(result, status=status)


async def stop_session_handler(request: web.Request) -> web.Response:
    """POST /api/v1/session/stop - Stop the recording session."""
    controller: APIController = request.app["controller"]

    result = await controller.stop_session()
    status = 200 if result.get("success") else 400
    return web.json_response(result, status=status)


async def get_directory_handler(request: web.Request) -> web.Response:
    """GET /api/v1/session/directory - Get session directory."""
    controller: APIController = request.app["controller"]
    result = await controller.get_session_directory()
    return web.json_response(result)


async def set_directory_handler(request: web.Request) -> web.Response:
    """PUT /api/v1/session/directory - Set idle session directory."""
    controller: APIController = request.app["controller"]

    try:
        body = await request.json()
    except Exception:
        return create_error_response(
            "INVALID_BODY",
            "Request body must be valid JSON",
            status=400,
        )

    directory = body.get("directory")
    if not directory:
        return create_error_response(
            "MISSING_DIRECTORY",
            "Request body must include 'directory' field",
            status=400,
        )

    result = await controller.set_idle_session_directory(directory)
    return web.json_response(result)


async def recording_status_handler(request: web.Request) -> web.Response:
    """GET /api/v1/session/recording - Check if recording."""
    controller: APIController = request.app["controller"]
    return web.json_response({
        "recording": controller.logger_system.recording,
        "trial_active": controller.trial_active,
    })


async def get_trial_handler(request: web.Request) -> web.Response:
    """GET /api/v1/trial - Get current trial info."""
    controller: APIController = request.app["controller"]
    result = await controller.get_trial_info()
    return web.json_response(result)


async def start_trial_handler(request: web.Request) -> web.Response:
    """POST /api/v1/trial/start - Start recording a trial."""
    controller: APIController = request.app["controller"]

    try:
        body = await request.json()
    except Exception:
        body = {}

    label = body.get("label", "")

    result = await controller.start_trial(label)
    status = 200 if result.get("success") else 400
    return web.json_response(result, status=status)


async def stop_trial_handler(request: web.Request) -> web.Response:
    """POST /api/v1/trial/stop - Stop recording the current trial."""
    controller: APIController = request.app["controller"]

    result = await controller.stop_trial()
    status = 200 if result.get("success") else 400
    return web.json_response(result, status=status)


async def trial_counter_handler(request: web.Request) -> web.Response:
    """GET /api/v1/trial/counter - Get trial counter."""
    controller: APIController = request.app["controller"]
    return web.json_response({
        "trial_counter": controller.trial_counter,
    })
