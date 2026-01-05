"""Log Routes - Log file access and viewing endpoints."""

from typing import Optional, Tuple
from aiohttp import web

from ..controller import APIController
from ..middleware import create_error_response


def setup_log_routes(app: web.Application, controller: APIController) -> None:
    """Register log routes."""
    app.router.add_get("/api/v1/logs/paths", log_paths_handler)
    app.router.add_get("/api/v1/logs/master", master_log_handler)
    app.router.add_get("/api/v1/logs/session", session_log_handler)
    app.router.add_get("/api/v1/logs/events", events_log_handler)
    app.router.add_get("/api/v1/logs/modules/{name}", module_log_handler)
    app.router.add_get("/api/v1/logs/tail/{path:.*}", tail_log_handler)


def _parse_pagination(request: web.Request) -> Tuple[Optional[int], Optional[int], Optional[web.Response]]:
    """Parse offset/limit from query params. Returns (offset, limit, error_response)."""
    try:
        offset = int(request.query.get("offset", 0))
        limit = int(request.query.get("limit", 100))
    except ValueError:
        return None, None, create_error_response("INVALID_PARAMETER", "offset and limit must be integers", status=400)
    if offset < 0 or limit < 1:
        return None, None, create_error_response("INVALID_PARAMETER", "offset must be >= 0 and limit must be >= 1", status=400)
    return offset, limit, None


def _log_result_response(result: dict, not_found_errors: tuple = ("FILE_NOT_FOUND",)) -> web.Response:
    """Convert log read result to response, handling errors."""
    if not result["success"]:
        status = 404 if result.get("error") in not_found_errors else 500
        return create_error_response(result.get("error", "READ_ERROR"), result.get("message", "Failed to read log file"), status=status)
    return web.json_response(result)


async def log_paths_handler(request: web.Request) -> web.Response:
    """GET /api/v1/logs/paths - Get all log file paths."""
    controller: APIController = request.app["controller"]
    return web.json_response(await controller.get_log_paths())


async def master_log_handler(request: web.Request) -> web.Response:
    """GET /api/v1/logs/master - Get master log content (paginated)."""
    controller: APIController = request.app["controller"]
    offset, limit, err = _parse_pagination(request)
    if err:
        return err
    return _log_result_response(await controller.read_master_log(offset, limit))


async def session_log_handler(request: web.Request) -> web.Response:
    """GET /api/v1/logs/session - Get session log content (paginated)."""
    controller: APIController = request.app["controller"]
    offset, limit, err = _parse_pagination(request)
    if err:
        return err
    return _log_result_response(await controller.read_session_log(offset, limit))


async def events_log_handler(request: web.Request) -> web.Response:
    """GET /api/v1/logs/events - Get event log content (paginated)."""
    controller: APIController = request.app["controller"]
    offset, limit, err = _parse_pagination(request)
    if err:
        return err
    return _log_result_response(await controller.read_events_log(offset, limit))


async def module_log_handler(request: web.Request) -> web.Response:
    """GET /api/v1/logs/modules/{name} - Get module-specific log (paginated)."""
    controller: APIController = request.app["controller"]
    offset, limit, err = _parse_pagination(request)
    if err:
        return err
    result = await controller.read_module_log(request.match_info["name"], offset, limit)
    return _log_result_response(result, ("FILE_NOT_FOUND", "MODULE_NOT_FOUND"))


async def tail_log_handler(request: web.Request) -> web.Response:
    """GET /api/v1/logs/tail/{path} - Tail a specific log file."""
    controller: APIController = request.app["controller"]
    try:
        lines = int(request.query.get("lines", 50))
    except ValueError:
        return create_error_response("INVALID_PARAMETER", "lines must be an integer", status=400)
    if lines < 1:
        return create_error_response("INVALID_PARAMETER", "lines must be >= 1", status=400)
    result = await controller.tail_log_file(request.match_info["path"], lines)
    if not result["success"]:
        status = 404 if result.get("error") == "FILE_NOT_FOUND" else 403
        return create_error_response(result.get("error", "READ_ERROR"), result.get("message", "Failed to read log file"), status=status)
    return web.json_response(result)
