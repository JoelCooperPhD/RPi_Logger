"""
Log Routes - Log file access and viewing endpoints.
"""

from aiohttp import web

from ..controller import APIController
from ..middleware import create_error_response


def setup_log_routes(app: web.Application, controller: APIController) -> None:
    """Register log routes."""
    # Log paths
    app.router.add_get("/api/v1/logs/paths", log_paths_handler)

    # Log content (paginated)
    app.router.add_get("/api/v1/logs/master", master_log_handler)
    app.router.add_get("/api/v1/logs/session", session_log_handler)
    app.router.add_get("/api/v1/logs/events", events_log_handler)

    # Module-specific logs
    app.router.add_get("/api/v1/logs/modules/{name}", module_log_handler)

    # Tail a specific log file
    app.router.add_get("/api/v1/logs/tail/{path:.*}", tail_log_handler)


async def log_paths_handler(request: web.Request) -> web.Response:
    """GET /api/v1/logs/paths - Get all log file paths."""
    controller: APIController = request.app["controller"]
    result = await controller.get_log_paths()
    return web.json_response(result)


async def master_log_handler(request: web.Request) -> web.Response:
    """GET /api/v1/logs/master - Get master log content (paginated).

    Query parameters:
        offset: Line offset to start reading from (default: 0)
        limit: Maximum number of lines to return (default: 100)
    """
    controller: APIController = request.app["controller"]

    # Parse pagination parameters
    try:
        offset = int(request.query.get("offset", 0))
        limit = int(request.query.get("limit", 100))
    except ValueError:
        return create_error_response(
            "INVALID_PARAMETER",
            "offset and limit must be integers",
            status=400,
        )

    if offset < 0 or limit < 1:
        return create_error_response(
            "INVALID_PARAMETER",
            "offset must be >= 0 and limit must be >= 1",
            status=400,
        )

    result = await controller.read_master_log(offset, limit)
    if not result["success"]:
        return create_error_response(
            result.get("error", "READ_ERROR"),
            result.get("message", "Failed to read log file"),
            status=404 if result.get("error") == "FILE_NOT_FOUND" else 500,
        )

    return web.json_response(result)


async def session_log_handler(request: web.Request) -> web.Response:
    """GET /api/v1/logs/session - Get session log content (paginated).

    Query parameters:
        offset: Line offset to start reading from (default: 0)
        limit: Maximum number of lines to return (default: 100)
    """
    controller: APIController = request.app["controller"]

    # Parse pagination parameters
    try:
        offset = int(request.query.get("offset", 0))
        limit = int(request.query.get("limit", 100))
    except ValueError:
        return create_error_response(
            "INVALID_PARAMETER",
            "offset and limit must be integers",
            status=400,
        )

    if offset < 0 or limit < 1:
        return create_error_response(
            "INVALID_PARAMETER",
            "offset must be >= 0 and limit must be >= 1",
            status=400,
        )

    result = await controller.read_session_log(offset, limit)
    if not result["success"]:
        status = 404 if result.get("error") == "FILE_NOT_FOUND" else 400
        return create_error_response(
            result.get("error", "READ_ERROR"),
            result.get("message", "Failed to read log file"),
            status=status,
        )

    return web.json_response(result)


async def events_log_handler(request: web.Request) -> web.Response:
    """GET /api/v1/logs/events - Get event log content (paginated).

    Query parameters:
        offset: Line offset to start reading from (default: 0)
        limit: Maximum number of lines to return (default: 100)
    """
    controller: APIController = request.app["controller"]

    # Parse pagination parameters
    try:
        offset = int(request.query.get("offset", 0))
        limit = int(request.query.get("limit", 100))
    except ValueError:
        return create_error_response(
            "INVALID_PARAMETER",
            "offset and limit must be integers",
            status=400,
        )

    if offset < 0 or limit < 1:
        return create_error_response(
            "INVALID_PARAMETER",
            "offset must be >= 0 and limit must be >= 1",
            status=400,
        )

    result = await controller.read_events_log(offset, limit)
    if not result["success"]:
        status = 404 if result.get("error") == "FILE_NOT_FOUND" else 400
        return create_error_response(
            result.get("error", "READ_ERROR"),
            result.get("message", "Failed to read log file"),
            status=status,
        )

    return web.json_response(result)


async def module_log_handler(request: web.Request) -> web.Response:
    """GET /api/v1/logs/modules/{name} - Get module-specific log.

    Query parameters:
        offset: Line offset to start reading from (default: 0)
        limit: Maximum number of lines to return (default: 100)
    """
    controller: APIController = request.app["controller"]
    module_name = request.match_info["name"]

    # Parse pagination parameters
    try:
        offset = int(request.query.get("offset", 0))
        limit = int(request.query.get("limit", 100))
    except ValueError:
        return create_error_response(
            "INVALID_PARAMETER",
            "offset and limit must be integers",
            status=400,
        )

    if offset < 0 or limit < 1:
        return create_error_response(
            "INVALID_PARAMETER",
            "offset must be >= 0 and limit must be >= 1",
            status=400,
        )

    result = await controller.read_module_log(module_name, offset, limit)
    if not result["success"]:
        status = 404 if result.get("error") in ("FILE_NOT_FOUND", "MODULE_NOT_FOUND") else 500
        return create_error_response(
            result.get("error", "READ_ERROR"),
            result.get("message", "Failed to read log file"),
            status=status,
        )

    return web.json_response(result)


async def tail_log_handler(request: web.Request) -> web.Response:
    """GET /api/v1/logs/tail/{path} - Tail a specific log file.

    Query parameters:
        lines: Number of lines to return from end of file (default: 50)
    """
    controller: APIController = request.app["controller"]
    path = request.match_info["path"]

    # Parse lines parameter
    try:
        lines = int(request.query.get("lines", 50))
    except ValueError:
        return create_error_response(
            "INVALID_PARAMETER",
            "lines must be an integer",
            status=400,
        )

    if lines < 1:
        return create_error_response(
            "INVALID_PARAMETER",
            "lines must be >= 1",
            status=400,
        )

    result = await controller.tail_log_file(path, lines)
    if not result["success"]:
        status = 404 if result.get("error") == "FILE_NOT_FOUND" else 403
        return create_error_response(
            result.get("error", "READ_ERROR"),
            result.get("message", "Failed to read log file"),
            status=status,
        )

    return web.json_response(result)
