"""
Notes module API routes.

Provides dedicated endpoints for the Notes module that go beyond
the generic module command interface.
"""

from aiohttp import web


def create_error_response(code: str, message: str, status: int = 400) -> web.Response:
    """Create a JSON error response."""
    return web.json_response(
        {"error": {"code": code, "message": message}},
        status=status
    )


def setup_notes_routes(app: web.Application, controller) -> None:
    """Register Notes module-specific routes."""
    # Configuration endpoints
    app.router.add_get("/api/v1/modules/notes/config", get_notes_config_handler)
    app.router.add_put("/api/v1/modules/notes/config", update_notes_config_handler)

    # Status endpoint
    app.router.add_get("/api/v1/modules/notes/status", get_notes_status_handler)

    # Categories endpoint
    app.router.add_get("/api/v1/modules/notes/categories", get_notes_categories_handler)

    # Notes CRUD endpoints
    app.router.add_get("/api/v1/modules/notes", get_notes_handler)
    app.router.add_post("/api/v1/modules/notes", add_note_handler)
    app.router.add_get("/api/v1/modules/notes/{id}", get_note_handler)
    app.router.add_delete("/api/v1/modules/notes/{id}", delete_note_handler)


async def get_notes_config_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/notes/config - Get notes module configuration."""
    controller = request.app["controller"]
    result = await controller.get_notes_config()
    return web.json_response(result)


async def update_notes_config_handler(request: web.Request) -> web.Response:
    """PUT /api/v1/modules/notes/config - Update notes module configuration."""
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

    result = await controller.update_notes_config(body)
    if not result.get("success"):
        return web.json_response(result, status=500)

    return web.json_response(result)


async def get_notes_status_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/notes/status - Get notes module status."""
    controller = request.app["controller"]
    result = await controller.get_notes_status()
    return web.json_response(result)


async def get_notes_categories_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/notes/categories - Get available note categories."""
    controller = request.app["controller"]
    result = await controller.get_notes_categories()
    return web.json_response(result)


async def get_notes_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/notes - Get all notes for current session."""
    controller = request.app["controller"]

    # Get optional query parameters
    limit = request.query.get("limit")
    trial_number = request.query.get("trial_number")

    # Convert query params to appropriate types
    limit_int = None
    if limit:
        try:
            limit_int = int(limit)
            if limit_int < 1:
                return create_error_response(
                    "INVALID_PARAMETER",
                    "limit must be a positive integer",
                    status=400,
                )
        except ValueError:
            return create_error_response(
                "INVALID_PARAMETER",
                "limit must be a valid integer",
                status=400,
            )

    trial_int = None
    if trial_number:
        try:
            trial_int = int(trial_number)
            if trial_int < 1:
                return create_error_response(
                    "INVALID_PARAMETER",
                    "trial_number must be a positive integer",
                    status=400,
                )
        except ValueError:
            return create_error_response(
                "INVALID_PARAMETER",
                "trial_number must be a valid integer",
                status=400,
            )

    result = await controller.get_notes(limit=limit_int, trial_number=trial_int)
    return web.json_response(result)


async def add_note_handler(request: web.Request) -> web.Response:
    """POST /api/v1/modules/notes - Add a new note."""
    controller = request.app["controller"]

    try:
        body = await request.json()
    except Exception:
        return create_error_response(
            "INVALID_BODY",
            "Request body must be valid JSON",
            status=400,
        )

    # Extract note text (required)
    note_text = body.get("text") or body.get("note_text") or body.get("note")
    if not note_text:
        return create_error_response(
            "MISSING_FIELD",
            "Request body must include 'text' field with note content",
            status=400,
        )

    if not isinstance(note_text, str):
        return create_error_response(
            "INVALID_FIELD",
            "'text' field must be a string",
            status=400,
        )

    note_text = note_text.strip()
    if not note_text:
        return create_error_response(
            "EMPTY_NOTE",
            "Note text cannot be empty",
            status=400,
        )

    # Extract optional timestamp
    timestamp = body.get("timestamp")
    if timestamp is not None:
        if not isinstance(timestamp, (int, float)):
            return create_error_response(
                "INVALID_FIELD",
                "'timestamp' field must be a number (Unix timestamp)",
                status=400,
            )

    # Extract optional category
    category = body.get("category")

    result = await controller.add_note(
        note_text=note_text,
        timestamp=timestamp,
        category=category,
    )

    if not result.get("success"):
        status = 500
        if result.get("error") == "no_active_session":
            status = 400
        elif result.get("error") == "module_not_running":
            status = 503
        return web.json_response(result, status=status)

    return web.json_response(result, status=201)


async def get_note_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/notes/{id} - Get specific note by ID."""
    controller = request.app["controller"]
    note_id = request.match_info["id"]

    # Validate note ID
    try:
        note_id_int = int(note_id)
        if note_id_int < 1:
            return create_error_response(
                "INVALID_NOTE_ID",
                "Note ID must be a positive integer",
                status=400,
            )
    except ValueError:
        return create_error_response(
            "INVALID_NOTE_ID",
            "Note ID must be a valid integer",
            status=400,
        )

    result = await controller.get_note(note_id_int)
    if not result.get("success"):
        status = 404 if result.get("error") == "note_not_found" else 500
        return web.json_response(result, status=status)

    return web.json_response(result)


async def delete_note_handler(request: web.Request) -> web.Response:
    """DELETE /api/v1/modules/notes/{id} - Delete a note by ID."""
    controller = request.app["controller"]
    note_id = request.match_info["id"]

    # Validate note ID
    try:
        note_id_int = int(note_id)
        if note_id_int < 1:
            return create_error_response(
                "INVALID_NOTE_ID",
                "Note ID must be a positive integer",
                status=400,
            )
    except ValueError:
        return create_error_response(
            "INVALID_NOTE_ID",
            "Note ID must be a valid integer",
            status=400,
        )

    result = await controller.delete_note(note_id_int)
    if not result.get("success"):
        status = 404 if result.get("error") == "note_not_found" else 500
        return web.json_response(result, status=status)

    return web.json_response(result)
