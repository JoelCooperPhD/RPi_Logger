"""Configuration Routes - Global and module-specific configuration endpoints."""

from aiohttp import web

from ..controller import APIController
from ..middleware import create_error_response, parse_json_body, result_to_response


def setup_config_routes(app: web.Application, controller: APIController) -> None:
    """Register configuration routes."""
    app.router.add_get("/api/v1/config", get_config_handler)
    app.router.add_put("/api/v1/config", update_config_handler)
    app.router.add_get("/api/v1/config/path", get_config_path_handler)
    app.router.add_get("/api/v1/modules/{name}/config", get_module_config_handler)
    app.router.add_put("/api/v1/modules/{name}/config", update_module_config_handler)
    app.router.add_get("/api/v1/modules/{name}/preferences", get_module_preferences_handler)
    app.router.add_put("/api/v1/modules/{name}/preferences/{key}", update_module_preference_handler)


async def get_config_handler(request: web.Request) -> web.Response:
    """GET /api/v1/config - Get global configuration."""
    controller: APIController = request.app["controller"]
    return web.json_response({"config": await controller.get_config()})


async def update_config_handler(request: web.Request) -> web.Response:
    """PUT /api/v1/config - Update global configuration."""
    controller: APIController = request.app["controller"]
    body, err = await parse_json_body(request)
    if err:
        return err
    return web.json_response(await controller.update_config(body))


async def get_config_path_handler(request: web.Request) -> web.Response:
    """GET /api/v1/config/path - Get config file path."""
    controller: APIController = request.app["controller"]
    return web.json_response(await controller.get_config_path())


async def get_module_config_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/{name}/config - Get module-specific configuration."""
    controller: APIController = request.app["controller"]
    name = request.match_info["name"]
    result = await controller.get_module_config(name)
    return result_to_response(result, "MODULE_NOT_FOUND", f"Module '{name}' not found or has no configuration")


async def update_module_config_handler(request: web.Request) -> web.Response:
    """PUT /api/v1/modules/{name}/config - Update module-specific configuration."""
    controller: APIController = request.app["controller"]
    body, err = await parse_json_body(request)
    if err:
        return err
    result = await controller.update_module_config(request.match_info["name"], body)
    if not result.get("success"):
        return web.json_response(result, status=404 if result.get("error") == "module_not_found" else 500)
    return web.json_response(result)


async def get_module_preferences_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/{name}/preferences - Get module preferences snapshot."""
    controller: APIController = request.app["controller"]
    name = request.match_info["name"]
    result = await controller.get_module_preferences(name)
    return result_to_response(result, "MODULE_NOT_FOUND", f"Module '{name}' not found or has no preferences")


async def update_module_preference_handler(request: web.Request) -> web.Response:
    """PUT /api/v1/modules/{name}/preferences/{key} - Update specific preference."""
    controller: APIController = request.app["controller"]
    body, err = await parse_json_body(request, required=False)
    if err:
        return err
    if "value" not in body:
        return create_error_response("MISSING_VALUE", "'value' field is required", status=400)
    result = await controller.update_module_preference(request.match_info["name"], request.match_info["key"], body["value"])
    if not result.get("success"):
        return web.json_response(result, status=404 if result.get("error") == "module_not_found" else 500)
    return web.json_response(result)
