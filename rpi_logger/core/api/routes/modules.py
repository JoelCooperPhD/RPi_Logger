"""
Module Routes - Module management endpoints.
"""

from aiohttp import web

from ..controller import APIController
from ..middleware import create_error_response


def setup_module_routes(app: web.Application, controller: APIController) -> None:
    """Register module routes."""
    # Module listing
    app.router.add_get("/api/v1/modules", list_modules_handler)
    app.router.add_get("/api/v1/modules/running", running_modules_handler)
    app.router.add_get("/api/v1/modules/enabled-states", enabled_states_handler)

    # Single module operations
    app.router.add_get("/api/v1/modules/{name}", get_module_handler)
    app.router.add_get("/api/v1/modules/{name}/state", module_state_handler)
    app.router.add_post("/api/v1/modules/{name}/enable", enable_module_handler)
    app.router.add_post("/api/v1/modules/{name}/disable", disable_module_handler)
    app.router.add_post("/api/v1/modules/{name}/start", start_module_handler)
    app.router.add_post("/api/v1/modules/{name}/stop", stop_module_handler)
    app.router.add_post("/api/v1/modules/{name}/command", send_command_handler)

    # Window control
    app.router.add_post("/api/v1/modules/{name}/window/show", show_window_handler)
    app.router.add_post("/api/v1/modules/{name}/window/hide", hide_window_handler)

    # Instance management (multi-instance modules)
    app.router.add_get("/api/v1/instances", list_instances_handler)
    app.router.add_post("/api/v1/instances/{id}/stop", stop_instance_handler)


async def list_modules_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules - List all available modules."""
    controller: APIController = request.app["controller"]
    modules = await controller.list_modules()
    return web.json_response({"modules": modules})


async def running_modules_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/running - List running modules."""
    controller: APIController = request.app["controller"]
    modules = await controller.get_running_modules()
    return web.json_response({"running_modules": modules})


async def enabled_states_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/enabled-states - Get all enabled states."""
    controller: APIController = request.app["controller"]
    states = await controller.get_enabled_states()
    return web.json_response({"enabled_states": states})


async def get_module_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/{name} - Get single module details."""
    controller: APIController = request.app["controller"]
    name = request.match_info["name"]

    module = await controller.get_module(name)
    if not module:
        return create_error_response(
            "MODULE_NOT_FOUND",
            f"Module '{name}' not found",
            status=404,
        )

    return web.json_response(module)


async def module_state_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/{name}/state - Get module state."""
    controller: APIController = request.app["controller"]
    name = request.match_info["name"]

    state = await controller.get_module_state(name)
    if state is None:
        return create_error_response(
            "MODULE_NOT_FOUND",
            f"Module '{name}' not found",
            status=404,
        )

    return web.json_response({"module": name, "state": state})


async def enable_module_handler(request: web.Request) -> web.Response:
    """POST /api/v1/modules/{name}/enable - Enable a module."""
    controller: APIController = request.app["controller"]
    name = request.match_info["name"]

    result = await controller.enable_module(name)
    status = 200 if result["success"] else 500
    return web.json_response(result, status=status)


async def disable_module_handler(request: web.Request) -> web.Response:
    """POST /api/v1/modules/{name}/disable - Disable a module."""
    controller: APIController = request.app["controller"]
    name = request.match_info["name"]

    result = await controller.disable_module(name)
    status = 200 if result["success"] else 500
    return web.json_response(result, status=status)


async def start_module_handler(request: web.Request) -> web.Response:
    """POST /api/v1/modules/{name}/start - Start a module."""
    controller: APIController = request.app["controller"]
    name = request.match_info["name"]

    result = await controller.start_module(name)
    status = 200 if result["success"] else 500
    return web.json_response(result, status=status)


async def stop_module_handler(request: web.Request) -> web.Response:
    """POST /api/v1/modules/{name}/stop - Stop a module."""
    controller: APIController = request.app["controller"]
    name = request.match_info["name"]

    result = await controller.stop_module(name)
    status = 200 if result["success"] else 500
    return web.json_response(result, status=status)


async def send_command_handler(request: web.Request) -> web.Response:
    """POST /api/v1/modules/{name}/command - Send command to module."""
    controller: APIController = request.app["controller"]
    name = request.match_info["name"]

    try:
        body = await request.json()
    except Exception:
        body = {}

    command = body.get("command")
    if not command:
        return create_error_response(
            "MISSING_COMMAND",
            "Request body must include 'command' field",
            status=400,
        )

    # Extract any additional kwargs
    kwargs = {k: v for k, v in body.items() if k != "command"}

    result = await controller.send_module_command(name, command, **kwargs)
    status = 200 if result["success"] else 500
    return web.json_response(result, status=status)


async def show_window_handler(request: web.Request) -> web.Response:
    """POST /api/v1/modules/{name}/window/show - Show module window."""
    controller: APIController = request.app["controller"]
    name = request.match_info["name"]

    result = await controller.send_module_command(name, "show_window")
    return web.json_response(result)


async def hide_window_handler(request: web.Request) -> web.Response:
    """POST /api/v1/modules/{name}/window/hide - Hide module window."""
    controller: APIController = request.app["controller"]
    name = request.match_info["name"]

    result = await controller.send_module_command(name, "hide_window")
    return web.json_response(result)


async def list_instances_handler(request: web.Request) -> web.Response:
    """GET /api/v1/instances - List all running instances."""
    controller: APIController = request.app["controller"]
    instances = await controller.list_instances()
    return web.json_response({"instances": instances})


async def stop_instance_handler(request: web.Request) -> web.Response:
    """POST /api/v1/instances/{id}/stop - Stop a specific instance."""
    controller: APIController = request.app["controller"]
    instance_id = request.match_info["id"]

    result = await controller.stop_instance(instance_id)
    status = 200 if result["success"] else 500
    return web.json_response(result, status=status)
