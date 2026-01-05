"""Module Routes - Module management endpoints."""

from aiohttp import web

from ..controller import APIController
from ..middleware import create_error_response, parse_json_body, result_to_response


def setup_module_routes(app: web.Application, controller: APIController) -> None:
    """Register module routes."""
    app.router.add_get("/api/v1/modules", list_modules_handler)
    app.router.add_get("/api/v1/modules/running", running_modules_handler)
    app.router.add_get("/api/v1/modules/enabled-states", enabled_states_handler)
    app.router.add_get("/api/v1/modules/{name}", get_module_handler)
    app.router.add_get("/api/v1/modules/{name}/state", module_state_handler)
    app.router.add_post("/api/v1/modules/{name}/enable", enable_module_handler)
    app.router.add_post("/api/v1/modules/{name}/disable", disable_module_handler)
    app.router.add_post("/api/v1/modules/{name}/start", start_module_handler)
    app.router.add_post("/api/v1/modules/{name}/stop", stop_module_handler)
    app.router.add_post("/api/v1/modules/{name}/command", send_command_handler)
    app.router.add_post("/api/v1/modules/{name}/window/show", show_window_handler)
    app.router.add_post("/api/v1/modules/{name}/window/hide", hide_window_handler)
    app.router.add_get("/api/v1/instances", list_instances_handler)
    app.router.add_post("/api/v1/instances/{id}/stop", stop_instance_handler)


def _success_response(result: dict) -> web.Response:
    """Return JSON response with status based on success field."""
    return web.json_response(result, status=200 if result.get("success") else 500)


async def list_modules_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules - List all available modules."""
    controller: APIController = request.app["controller"]
    return web.json_response({"modules": await controller.list_modules()})


async def running_modules_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/running - List running modules."""
    controller: APIController = request.app["controller"]
    return web.json_response({"running_modules": await controller.get_running_modules()})


async def enabled_states_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/enabled-states - Get all enabled states."""
    controller: APIController = request.app["controller"]
    return web.json_response({"enabled_states": await controller.get_enabled_states()})


async def get_module_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/{name} - Get single module details."""
    controller: APIController = request.app["controller"]
    name = request.match_info["name"]
    module = await controller.get_module(name)
    return result_to_response(module, "MODULE_NOT_FOUND", f"Module '{name}' not found")


async def module_state_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/{name}/state - Get module state."""
    controller: APIController = request.app["controller"]
    name = request.match_info["name"]
    state = await controller.get_module_state(name)
    if state is None:
        return create_error_response("MODULE_NOT_FOUND", f"Module '{name}' not found", status=404)
    return web.json_response({"module": name, "state": state})


async def enable_module_handler(request: web.Request) -> web.Response:
    """POST /api/v1/modules/{name}/enable - Enable a module."""
    controller: APIController = request.app["controller"]
    return _success_response(await controller.enable_module(request.match_info["name"]))


async def disable_module_handler(request: web.Request) -> web.Response:
    """POST /api/v1/modules/{name}/disable - Disable a module."""
    controller: APIController = request.app["controller"]
    return _success_response(await controller.disable_module(request.match_info["name"]))


async def start_module_handler(request: web.Request) -> web.Response:
    """POST /api/v1/modules/{name}/start - Start a module."""
    controller: APIController = request.app["controller"]
    return _success_response(await controller.start_module(request.match_info["name"]))


async def stop_module_handler(request: web.Request) -> web.Response:
    """POST /api/v1/modules/{name}/stop - Stop a module."""
    controller: APIController = request.app["controller"]
    return _success_response(await controller.stop_module(request.match_info["name"]))


async def send_command_handler(request: web.Request) -> web.Response:
    """POST /api/v1/modules/{name}/command - Send command to module."""
    controller: APIController = request.app["controller"]
    body, _ = await parse_json_body(request, required=False)
    command = body.get("command")
    if not command:
        return create_error_response("MISSING_COMMAND", "'command' field is required", status=400)
    kwargs = {k: v for k, v in body.items() if k != "command"}
    return _success_response(await controller.send_module_command(request.match_info["name"], command, **kwargs))


async def show_window_handler(request: web.Request) -> web.Response:
    """POST /api/v1/modules/{name}/window/show - Show module window."""
    controller: APIController = request.app["controller"]
    return web.json_response(await controller.send_module_command(request.match_info["name"], "show_window"))


async def hide_window_handler(request: web.Request) -> web.Response:
    """POST /api/v1/modules/{name}/window/hide - Hide module window."""
    controller: APIController = request.app["controller"]
    return web.json_response(await controller.send_module_command(request.match_info["name"], "hide_window"))


async def list_instances_handler(request: web.Request) -> web.Response:
    """GET /api/v1/instances - List all running instances."""
    controller: APIController = request.app["controller"]
    return web.json_response({"instances": await controller.list_instances()})


async def stop_instance_handler(request: web.Request) -> web.Response:
    """POST /api/v1/instances/{id}/stop - Stop a specific instance."""
    controller: APIController = request.app["controller"]
    return _success_response(await controller.stop_instance(request.match_info["id"]))
