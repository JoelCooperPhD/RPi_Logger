"""Session Routes - Session and trial management endpoints."""

from aiohttp import web

from ..controller import APIController
from ..middleware import create_error_response, parse_json_body


def setup_session_routes(app: web.Application, controller: APIController) -> None:
    """Register session and trial routes."""
    app.router.add_get("/api/v1/session", get_session_handler)
    app.router.add_post("/api/v1/session/start", start_session_handler)
    app.router.add_post("/api/v1/session/stop", stop_session_handler)
    app.router.add_get("/api/v1/session/directory", get_directory_handler)
    app.router.add_put("/api/v1/session/directory", set_directory_handler)
    app.router.add_get("/api/v1/session/recording", recording_status_handler)
    app.router.add_get("/api/v1/trial", get_trial_handler)
    app.router.add_post("/api/v1/trial/start", start_trial_handler)
    app.router.add_post("/api/v1/trial/stop", stop_trial_handler)
    app.router.add_get("/api/v1/trial/counter", trial_counter_handler)


def _success_status(result: dict) -> int:
    return 200 if result.get("success") else 400


async def get_session_handler(request: web.Request) -> web.Response:
    """GET /api/v1/session - Get current session info."""
    controller: APIController = request.app["controller"]
    return web.json_response(await controller.get_session_info())


async def start_session_handler(request: web.Request) -> web.Response:
    """POST /api/v1/session/start - Start a recording session."""
    controller: APIController = request.app["controller"]
    body, _ = await parse_json_body(request, required=False)
    result = await controller.start_session(body.get("directory"))
    return web.json_response(result, status=_success_status(result))


async def stop_session_handler(request: web.Request) -> web.Response:
    """POST /api/v1/session/stop - Stop the recording session."""
    controller: APIController = request.app["controller"]
    result = await controller.stop_session()
    return web.json_response(result, status=_success_status(result))


async def get_directory_handler(request: web.Request) -> web.Response:
    """GET /api/v1/session/directory - Get session directory."""
    controller: APIController = request.app["controller"]
    return web.json_response(await controller.get_session_directory())


async def set_directory_handler(request: web.Request) -> web.Response:
    """PUT /api/v1/session/directory - Set idle session directory."""
    controller: APIController = request.app["controller"]
    body, err = await parse_json_body(request)
    if err:
        return err
    if not body.get("directory"):
        return create_error_response("MISSING_DIRECTORY", "'directory' field is required", status=400)
    return web.json_response(await controller.set_idle_session_directory(body["directory"]))


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
    return web.json_response(await controller.get_trial_info())


async def start_trial_handler(request: web.Request) -> web.Response:
    """POST /api/v1/trial/start - Start recording a trial."""
    controller: APIController = request.app["controller"]
    body, _ = await parse_json_body(request, required=False)
    result = await controller.start_trial(body.get("label", ""))
    return web.json_response(result, status=_success_status(result))


async def stop_trial_handler(request: web.Request) -> web.Response:
    """POST /api/v1/trial/stop - Stop recording the current trial."""
    controller: APIController = request.app["controller"]
    result = await controller.stop_trial()
    return web.json_response(result, status=_success_status(result))


async def trial_counter_handler(request: web.Request) -> web.Response:
    """GET /api/v1/trial/counter - Get trial counter."""
    controller: APIController = request.app["controller"]
    return web.json_response({"trial_counter": controller.trial_counter})
