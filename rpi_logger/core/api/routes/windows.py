"""
Window Management Routes - API endpoints for controlling module GUI windows.

Provides programmatic control over module window visibility, positioning,
focus, and bulk window operations.

Endpoints:
- POST /api/v1/modules/{name}/window/show       - Show module window
- POST /api/v1/modules/{name}/window/hide       - Hide module window
- GET  /api/v1/modules/{name}/window/geometry   - Get window geometry
- PUT  /api/v1/modules/{name}/window/geometry   - Set window geometry
- POST /api/v1/modules/{name}/window/focus      - Bring window to front
- GET  /api/v1/modules/{name}/window/state      - Get window state
- GET  /api/v1/windows                          - List all module windows
- POST /api/v1/windows/arrange                  - Auto-arrange windows
- POST /api/v1/windows/minimize-all             - Minimize all windows
- POST /api/v1/windows/restore-all              - Restore all windows
"""

from aiohttp import web

from ..controller import APIController
from ..middleware import create_error_response


def setup_windows_routes(app: web.Application, controller: APIController) -> None:
    """Register window management routes."""
    # Single module window operations
    app.router.add_post(
        "/api/v1/modules/{name}/window/show", show_module_window_handler
    )
    app.router.add_post(
        "/api/v1/modules/{name}/window/hide", hide_module_window_handler
    )
    app.router.add_get(
        "/api/v1/modules/{name}/window/geometry", get_window_geometry_handler
    )
    app.router.add_put(
        "/api/v1/modules/{name}/window/geometry", set_window_geometry_handler
    )
    app.router.add_post(
        "/api/v1/modules/{name}/window/focus", focus_module_window_handler
    )
    app.router.add_get(
        "/api/v1/modules/{name}/window/state", get_window_state_handler
    )

    # Bulk window operations
    app.router.add_get("/api/v1/windows", list_all_windows_handler)
    app.router.add_post("/api/v1/windows/arrange", arrange_windows_handler)
    app.router.add_post("/api/v1/windows/minimize-all", minimize_all_windows_handler)
    app.router.add_post("/api/v1/windows/restore-all", restore_all_windows_handler)


async def show_module_window_handler(request: web.Request) -> web.Response:
    """POST /api/v1/modules/{name}/window/show - Show a module's GUI window.

    Makes the module window visible if it was hidden.
    """
    controller: APIController = request.app["controller"]
    name = request.match_info["name"]

    result = await controller.show_module_window(name)

    if not result.get("success"):
        error = result.get("error", "unknown")
        if error == "module_not_found":
            return web.json_response(result, status=404)
        elif error == "module_not_running":
            return web.json_response(result, status=503)
        elif error == "no_gui_window":
            return web.json_response(result, status=400)
        return web.json_response(result, status=500)

    return web.json_response(result)


async def hide_module_window_handler(request: web.Request) -> web.Response:
    """POST /api/v1/modules/{name}/window/hide - Hide a module's GUI window.

    Hides the module window without stopping the module.
    """
    controller: APIController = request.app["controller"]
    name = request.match_info["name"]

    result = await controller.hide_module_window(name)

    if not result.get("success"):
        error = result.get("error", "unknown")
        if error == "module_not_found":
            return web.json_response(result, status=404)
        elif error == "module_not_running":
            return web.json_response(result, status=503)
        elif error == "no_gui_window":
            return web.json_response(result, status=400)
        return web.json_response(result, status=500)

    return web.json_response(result)


async def get_window_geometry_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/{name}/window/geometry - Get window position and size.

    Returns the window geometry as:
    {
        "x": int,      - X position in pixels
        "y": int,      - Y position in pixels
        "width": int,  - Width in pixels
        "height": int  - Height in pixels
    }
    """
    controller: APIController = request.app["controller"]
    name = request.match_info["name"]

    result = await controller.get_window_geometry(name)

    if not result.get("success"):
        error = result.get("error", "unknown")
        if error == "module_not_found":
            return web.json_response(result, status=404)
        elif error == "module_not_running":
            return web.json_response(result, status=503)
        elif error == "no_gui_window":
            return web.json_response(result, status=400)
        return web.json_response(result, status=500)

    return web.json_response(result)


async def set_window_geometry_handler(request: web.Request) -> web.Response:
    """PUT /api/v1/modules/{name}/window/geometry - Set window position and size.

    Accepts either a dict format:
    {
        "x": int,      - X position in pixels
        "y": int,      - Y position in pixels
        "width": int,  - Width in pixels
        "height": int  - Height in pixels
    }

    Or a geometry string format:
    {
        "geometry": "WIDTHxHEIGHT+X+Y"  - e.g., "800x600+100+100"
    }

    All fields are optional; only provided values will be updated.
    """
    controller: APIController = request.app["controller"]
    name = request.match_info["name"]

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
            "Request body must contain geometry data",
            status=400,
        )

    result = await controller.set_window_geometry(name, body)

    if not result.get("success"):
        error = result.get("error", "unknown")
        if error == "module_not_found":
            return web.json_response(result, status=404)
        elif error == "module_not_running":
            return web.json_response(result, status=503)
        elif error == "no_gui_window":
            return web.json_response(result, status=400)
        elif error == "invalid_geometry":
            return web.json_response(result, status=400)
        return web.json_response(result, status=500)

    return web.json_response(result)


async def focus_module_window_handler(request: web.Request) -> web.Response:
    """POST /api/v1/modules/{name}/window/focus - Bring window to front.

    Raises the module window above other windows and gives it focus.
    """
    controller: APIController = request.app["controller"]
    name = request.match_info["name"]

    result = await controller.focus_module_window(name)

    if not result.get("success"):
        error = result.get("error", "unknown")
        if error == "module_not_found":
            return web.json_response(result, status=404)
        elif error == "module_not_running":
            return web.json_response(result, status=503)
        elif error == "no_gui_window":
            return web.json_response(result, status=400)
        return web.json_response(result, status=500)

    return web.json_response(result)


async def get_window_state_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/{name}/window/state - Get window state.

    Returns the window state including:
    {
        "visible": bool,    - Whether window is visible
        "minimized": bool,  - Whether window is minimized
        "maximized": bool,  - Whether window is maximized
        "focused": bool     - Whether window has focus
    }
    """
    controller: APIController = request.app["controller"]
    name = request.match_info["name"]

    result = await controller.get_window_state(name)

    if not result.get("success"):
        error = result.get("error", "unknown")
        if error == "module_not_found":
            return web.json_response(result, status=404)
        elif error == "module_not_running":
            return web.json_response(result, status=503)
        elif error == "no_gui_window":
            return web.json_response(result, status=400)
        return web.json_response(result, status=500)

    return web.json_response(result)


async def list_all_windows_handler(request: web.Request) -> web.Response:
    """GET /api/v1/windows - List all module windows with their states.

    Returns a list of all module windows including their visibility,
    geometry, and state information.
    """
    controller: APIController = request.app["controller"]
    result = await controller.list_all_windows()
    return web.json_response(result)


async def arrange_windows_handler(request: web.Request) -> web.Response:
    """POST /api/v1/windows/arrange - Auto-arrange windows on screen.

    Arranges all visible module windows according to the specified layout.

    Request body (optional):
    {
        "layout": "grid" | "cascade" | "tile_horizontal" | "tile_vertical"
    }

    Default layout is "grid".
    """
    controller: APIController = request.app["controller"]

    layout = "grid"  # Default layout

    try:
        body = await request.json()
        if body:
            layout = body.get("layout", "grid")
    except Exception:
        # No body or invalid JSON is okay - use defaults
        pass

    # Validate layout
    valid_layouts = ["grid", "cascade", "tile_horizontal", "tile_vertical"]
    if layout not in valid_layouts:
        return create_error_response(
            "INVALID_LAYOUT",
            f"Layout must be one of: {', '.join(valid_layouts)}",
            status=400,
        )

    result = await controller.arrange_windows(layout)

    if not result.get("success"):
        return web.json_response(result, status=500)

    return web.json_response(result)


async def minimize_all_windows_handler(request: web.Request) -> web.Response:
    """POST /api/v1/windows/minimize-all - Minimize all module windows.

    Minimizes all visible module windows.
    """
    controller: APIController = request.app["controller"]
    result = await controller.minimize_all_windows()

    if not result.get("success"):
        return web.json_response(result, status=500)

    return web.json_response(result)


async def restore_all_windows_handler(request: web.Request) -> web.Response:
    """POST /api/v1/windows/restore-all - Restore all minimized windows.

    Restores all minimized module windows to their previous state.
    """
    controller: APIController = request.app["controller"]
    result = await controller.restore_all_windows()

    if not result.get("success"):
        return web.json_response(result, status=500)

    return web.json_response(result)
