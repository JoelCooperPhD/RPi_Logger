"""
System Routes - Health, status, platform, shutdown endpoints.
"""

from aiohttp import web

from ..controller import APIController


def setup_system_routes(app: web.Application, controller: APIController) -> None:
    """Register system routes."""
    app.router.add_get("/api/v1/health", health_handler)
    app.router.add_get("/api/v1/status", status_handler)
    app.router.add_get("/api/v1/platform", platform_handler)
    app.router.add_get("/api/v1/info/system", system_info_handler)
    app.router.add_post("/api/v1/shutdown", shutdown_handler)


async def health_handler(request: web.Request) -> web.Response:
    """GET /api/v1/health - Health check."""
    controller: APIController = request.app["controller"]
    result = await controller.health_check()
    return web.json_response(result)


async def status_handler(request: web.Request) -> web.Response:
    """GET /api/v1/status - Full system status."""
    controller: APIController = request.app["controller"]
    result = await controller.get_status()
    return web.json_response(result)


async def platform_handler(request: web.Request) -> web.Response:
    """GET /api/v1/platform - Platform information."""
    controller: APIController = request.app["controller"]
    result = await controller.get_platform_info()
    return web.json_response(result)


async def system_info_handler(request: web.Request) -> web.Response:
    """GET /api/v1/info/system - Detailed system info (CPU, memory, disk)."""
    controller: APIController = request.app["controller"]
    result = await controller.get_system_info()
    return web.json_response(result)


async def shutdown_handler(request: web.Request) -> web.Response:
    """POST /api/v1/shutdown - Initiate graceful shutdown."""
    controller: APIController = request.app["controller"]
    result = await controller.shutdown()
    return web.json_response(result)
