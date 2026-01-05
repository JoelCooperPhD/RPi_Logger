"""
Configuration Routes - Global and module-specific configuration endpoints.

Endpoints:
- GET  /api/v1/config                          - Get global configuration
- PUT  /api/v1/config                          - Update global configuration
- GET  /api/v1/config/path                     - Get config file path
- GET  /api/v1/modules/{name}/config           - Get module-specific config
- PUT  /api/v1/modules/{name}/config           - Update module-specific config
- GET  /api/v1/modules/{name}/preferences      - Get module preferences snapshot
- PUT  /api/v1/modules/{name}/preferences/{key} - Update specific preference
"""

from aiohttp import web

from ..controller import APIController
from ..middleware import create_error_response


def setup_config_routes(app: web.Application, controller: APIController) -> None:
    """Register configuration routes."""
    # Global configuration
    app.router.add_get("/api/v1/config", get_config_handler)
    app.router.add_put("/api/v1/config", update_config_handler)
    app.router.add_get("/api/v1/config/path", get_config_path_handler)

    # Module-specific configuration
    app.router.add_get("/api/v1/modules/{name}/config", get_module_config_handler)
    app.router.add_put("/api/v1/modules/{name}/config", update_module_config_handler)

    # Module preferences
    app.router.add_get(
        "/api/v1/modules/{name}/preferences", get_module_preferences_handler
    )
    app.router.add_put(
        "/api/v1/modules/{name}/preferences/{key}", update_module_preference_handler
    )


async def get_config_handler(request: web.Request) -> web.Response:
    """GET /api/v1/config - Get global configuration."""
    controller: APIController = request.app["controller"]
    config = await controller.get_config()
    return web.json_response({"config": config})


async def update_config_handler(request: web.Request) -> web.Response:
    """PUT /api/v1/config - Update global configuration."""
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

    result = await controller.update_config(body)
    return web.json_response(result)


async def get_config_path_handler(request: web.Request) -> web.Response:
    """GET /api/v1/config/path - Get config file path."""
    controller: APIController = request.app["controller"]
    result = await controller.get_config_path()
    return web.json_response(result)


async def get_module_config_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/{name}/config - Get module-specific configuration."""
    controller: APIController = request.app["controller"]
    name = request.match_info["name"]

    result = await controller.get_module_config(name)
    if result is None:
        return create_error_response(
            "MODULE_NOT_FOUND",
            f"Module '{name}' not found or has no configuration",
            status=404,
        )

    return web.json_response(result)


async def update_module_config_handler(request: web.Request) -> web.Response:
    """PUT /api/v1/modules/{name}/config - Update module-specific configuration."""
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
            "Request body must contain configuration updates",
            status=400,
        )

    result = await controller.update_module_config(name, body)
    if not result.get("success"):
        status = 404 if result.get("error") == "module_not_found" else 500
        return web.json_response(result, status=status)

    return web.json_response(result)


async def get_module_preferences_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/{name}/preferences - Get module preferences snapshot."""
    controller: APIController = request.app["controller"]
    name = request.match_info["name"]

    result = await controller.get_module_preferences(name)
    if result is None:
        return create_error_response(
            "MODULE_NOT_FOUND",
            f"Module '{name}' not found or has no preferences",
            status=404,
        )

    return web.json_response(result)


async def update_module_preference_handler(request: web.Request) -> web.Response:
    """PUT /api/v1/modules/{name}/preferences/{key} - Update specific preference."""
    controller: APIController = request.app["controller"]
    name = request.match_info["name"]
    key = request.match_info["key"]

    try:
        body = await request.json()
    except Exception:
        return create_error_response(
            "INVALID_BODY",
            "Request body must be valid JSON",
            status=400,
        )

    value = body.get("value")
    if value is None and "value" not in body:
        return create_error_response(
            "MISSING_VALUE",
            "Request body must include 'value' field",
            status=400,
        )

    result = await controller.update_module_preference(name, key, value)
    if not result.get("success"):
        status = 404 if result.get("error") == "module_not_found" else 500
        return web.json_response(result, status=status)

    return web.json_response(result)
