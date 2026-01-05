"""System Routes - Health, status, platform, shutdown endpoints."""

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
    return web.json_response(await request.app["controller"].health_check())


async def status_handler(request: web.Request) -> web.Response:
    """GET /api/v1/status - Full system status."""
    return web.json_response(await request.app["controller"].get_status())


async def platform_handler(request: web.Request) -> web.Response:
    """GET /api/v1/platform - Platform information."""
    return web.json_response(await request.app["controller"].get_platform_info())


async def system_info_handler(request: web.Request) -> web.Response:
    """GET /api/v1/info/system - Detailed system info (CPU, memory, disk)."""
    return web.json_response(await request.app["controller"].get_system_info())


async def shutdown_handler(request: web.Request) -> web.Response:
    """POST /api/v1/shutdown - Initiate graceful shutdown."""
    return web.json_response(await request.app["controller"].shutdown())
