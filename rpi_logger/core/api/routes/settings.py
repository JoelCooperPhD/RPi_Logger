"""
Settings Routes - Comprehensive settings management endpoints.

Provides per-module and global settings management:

Per-Module Settings:
- GET  /api/v1/modules/{name}/settings          - Get all module settings
- PUT  /api/v1/modules/{name}/settings          - Update module settings (batch)
- GET  /api/v1/modules/{name}/settings/{key}    - Get specific setting
- PUT  /api/v1/modules/{name}/settings/{key}    - Update specific setting
- POST /api/v1/modules/{name}/settings/reset    - Reset to defaults
- GET  /api/v1/modules/{name}/settings/schema   - Get settings schema

Global Settings:
- GET  /api/v1/settings                         - Get all global settings
- PUT  /api/v1/settings                         - Update global settings
- GET  /api/v1/settings/connection-types        - Get enabled connection types
- PUT  /api/v1/settings/connection-types        - Update connection types
- GET  /api/v1/settings/window-geometries       - Get saved window positions
"""

from aiohttp import web

from ..controller import APIController
from ..middleware import create_error_response


def setup_settings_routes(app: web.Application, controller: APIController) -> None:
    """Register settings management routes."""
    # Per-module settings endpoints
    app.router.add_get(
        "/api/v1/modules/{name}/settings",
        get_module_settings_handler
    )
    app.router.add_put(
        "/api/v1/modules/{name}/settings",
        update_module_settings_handler
    )
    app.router.add_get(
        "/api/v1/modules/{name}/settings/schema",
        get_module_settings_schema_handler
    )
    app.router.add_post(
        "/api/v1/modules/{name}/settings/reset",
        reset_module_settings_handler
    )
    app.router.add_get(
        "/api/v1/modules/{name}/settings/{key:.*}",
        get_module_setting_handler
    )
    app.router.add_put(
        "/api/v1/modules/{name}/settings/{key:.*}",
        update_module_setting_handler
    )

    # Global settings endpoints
    app.router.add_get("/api/v1/settings", get_global_settings_handler)
    app.router.add_put("/api/v1/settings", update_global_settings_handler)
    app.router.add_get(
        "/api/v1/settings/connection-types",
        get_connection_types_handler
    )
    app.router.add_put(
        "/api/v1/settings/connection-types",
        update_connection_types_handler
    )
    app.router.add_get(
        "/api/v1/settings/window-geometries",
        get_window_geometries_handler
    )


# =============================================================================
# Per-Module Settings Handlers
# =============================================================================

async def get_module_settings_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/{name}/settings - Get all module settings.

    Returns all current settings for the specified module, including
    both persisted preferences and runtime configuration.
    """
    controller: APIController = request.app["controller"]
    name = request.match_info["name"]

    result = await controller.get_module_settings(name)

    if not result.get("success"):
        error = result.get("error", "unknown_error")
        if error == "module_not_found":
            return create_error_response(
                "MODULE_NOT_FOUND",
                f"Module '{name}' not found",
                status=404,
            )
        return web.json_response(result, status=500)

    return web.json_response(result)


async def update_module_settings_handler(request: web.Request) -> web.Response:
    """PUT /api/v1/modules/{name}/settings - Update module settings (batch).

    Request body should be a JSON object with settings key-value pairs.
    Supports nested keys using dot notation (e.g., "preview.resolution").

    Example:
        {
            "sample_rate": 44100,
            "console_output": true,
            "preview.fps_cap": 15.0
        }
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
            "Request body must contain settings to update",
            status=400,
        )

    if not isinstance(body, dict):
        return create_error_response(
            "INVALID_BODY",
            "Request body must be a JSON object",
            status=400,
        )

    result = await controller.update_module_settings(name, body)

    if not result.get("success"):
        error = result.get("error", "unknown_error")
        if error == "module_not_found":
            return create_error_response(
                "MODULE_NOT_FOUND",
                f"Module '{name}' not found",
                status=404,
            )
        elif error == "validation_error":
            return create_error_response(
                "VALIDATION_ERROR",
                result.get("message", "Settings validation failed"),
                status=400,
                details={"errors": result.get("errors", [])},
            )
        return web.json_response(result, status=500)

    return web.json_response(result)


async def get_module_setting_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/{name}/settings/{key} - Get specific setting.

    The key can use dot notation for nested settings (e.g., "preview.resolution").
    """
    controller: APIController = request.app["controller"]
    name = request.match_info["name"]
    key = request.match_info["key"]

    if not key:
        return create_error_response(
            "MISSING_KEY",
            "Setting key is required",
            status=400,
        )

    result = await controller.get_module_setting(name, key)

    if not result.get("success"):
        error = result.get("error", "unknown_error")
        if error == "module_not_found":
            return create_error_response(
                "MODULE_NOT_FOUND",
                f"Module '{name}' not found",
                status=404,
            )
        elif error == "setting_not_found":
            return create_error_response(
                "SETTING_NOT_FOUND",
                f"Setting '{key}' not found in module '{name}'",
                status=404,
            )
        return web.json_response(result, status=500)

    return web.json_response(result)


async def update_module_setting_handler(request: web.Request) -> web.Response:
    """PUT /api/v1/modules/{name}/settings/{key} - Update specific setting.

    Request body should contain a "value" field with the new value.

    Example:
        { "value": 44100 }
    """
    controller: APIController = request.app["controller"]
    name = request.match_info["name"]
    key = request.match_info["key"]

    if not key:
        return create_error_response(
            "MISSING_KEY",
            "Setting key is required",
            status=400,
        )

    try:
        body = await request.json()
    except Exception:
        return create_error_response(
            "INVALID_BODY",
            "Request body must be valid JSON",
            status=400,
        )

    if "value" not in body:
        return create_error_response(
            "MISSING_VALUE",
            "Request body must include 'value' field",
            status=400,
        )

    value = body["value"]
    result = await controller.update_module_setting(name, key, value)

    if not result.get("success"):
        error = result.get("error", "unknown_error")
        if error == "module_not_found":
            return create_error_response(
                "MODULE_NOT_FOUND",
                f"Module '{name}' not found",
                status=404,
            )
        elif error == "validation_error":
            return create_error_response(
                "VALIDATION_ERROR",
                result.get("message", "Setting validation failed"),
                status=400,
            )
        return web.json_response(result, status=500)

    return web.json_response(result)


async def reset_module_settings_handler(request: web.Request) -> web.Response:
    """POST /api/v1/modules/{name}/settings/reset - Reset to defaults.

    Resets all module settings to their default values as defined
    in the settings schema.
    """
    controller: APIController = request.app["controller"]
    name = request.match_info["name"]

    result = await controller.reset_module_settings(name)

    if not result.get("success"):
        error = result.get("error", "unknown_error")
        if error == "module_not_found":
            return create_error_response(
                "MODULE_NOT_FOUND",
                f"Module '{name}' not found",
                status=404,
            )
        elif error == "no_schema":
            return create_error_response(
                "NO_SCHEMA",
                f"No settings schema available for module '{name}'",
                status=404,
            )
        return web.json_response(result, status=500)

    return web.json_response(result)


async def get_module_settings_schema_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/{name}/settings/schema - Get settings schema.

    Returns the complete schema for the module's settings, including
    field types, ranges, defaults, and descriptions.
    """
    controller: APIController = request.app["controller"]
    name = request.match_info["name"]

    result = await controller.get_module_settings_schema(name)

    if not result.get("success"):
        error = result.get("error", "unknown_error")
        if error == "module_not_found":
            return create_error_response(
                "MODULE_NOT_FOUND",
                f"Module '{name}' not found",
                status=404,
            )
        elif error == "no_schema":
            return create_error_response(
                "NO_SCHEMA",
                f"No settings schema available for module '{name}'",
                status=404,
            )
        return web.json_response(result, status=500)

    return web.json_response(result)


# =============================================================================
# Global Settings Handlers
# =============================================================================

async def get_global_settings_handler(request: web.Request) -> web.Response:
    """GET /api/v1/settings - Get all global settings.

    Returns application-wide settings including output paths,
    logging configuration, and enabled features.
    """
    controller: APIController = request.app["controller"]
    result = await controller.get_global_settings()
    return web.json_response(result)


async def update_global_settings_handler(request: web.Request) -> web.Response:
    """PUT /api/v1/settings - Update global settings.

    Request body should be a JSON object with settings key-value pairs.

    Example:
        {
            "output_base_dir": "/data/logger",
            "log_level": "debug"
        }
    """
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
            "Request body must contain settings to update",
            status=400,
        )

    if not isinstance(body, dict):
        return create_error_response(
            "INVALID_BODY",
            "Request body must be a JSON object",
            status=400,
        )

    result = await controller.update_global_settings(body)

    if not result.get("success"):
        error = result.get("error", "unknown_error")
        if error == "validation_error":
            return create_error_response(
                "VALIDATION_ERROR",
                result.get("message", "Settings validation failed"),
                status=400,
                details={"errors": result.get("errors", [])},
            )
        return web.json_response(result, status=500)

    return web.json_response(result)


async def get_connection_types_handler(request: web.Request) -> web.Response:
    """GET /api/v1/settings/connection-types - Get enabled connection types.

    Returns a dictionary of connection types and their enabled status.

    Example response:
        {
            "success": true,
            "connection_types": {
                "usb": true,
                "serial": true,
                "bluetooth": false,
                "xbee": true
            }
        }
    """
    controller: APIController = request.app["controller"]
    result = await controller.get_connection_types()
    return web.json_response(result)


async def update_connection_types_handler(request: web.Request) -> web.Response:
    """PUT /api/v1/settings/connection-types - Update connection types.

    Request body should be a JSON object mapping connection types
    to their enabled status.

    Example:
        {
            "usb": true,
            "bluetooth": false
        }
    """
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
            "Request body must contain connection types to update",
            status=400,
        )

    if not isinstance(body, dict):
        return create_error_response(
            "INVALID_BODY",
            "Request body must be a JSON object",
            status=400,
        )

    # Validate that all values are booleans
    for key, value in body.items():
        if not isinstance(value, bool):
            return create_error_response(
                "INVALID_VALUE",
                f"Connection type '{key}' must be a boolean",
                status=400,
            )

    result = await controller.update_connection_types(body)

    if not result.get("success"):
        return web.json_response(result, status=500)

    return web.json_response(result)


async def get_window_geometries_handler(request: web.Request) -> web.Response:
    """GET /api/v1/settings/window-geometries - Get saved window positions.

    Returns saved window geometries for all modules and dialogs.

    Example response:
        {
            "success": true,
            "geometries": {
                "main_window": "1200x800+100+50",
                "audio": "400x300+500+200",
                "cameras": "800x600+100+100"
            }
        }
    """
    controller: APIController = request.app["controller"]
    result = await controller.get_window_geometries()
    return web.json_response(result)
