"""
Debug Routes - API endpoints for debugging and introspection.

Provides endpoints for inspecting internal state during development:
- GET  /api/v1/debug/mode              - Get/check debug mode status
- POST /api/v1/debug/mode              - Toggle debug mode at runtime
- GET  /api/v1/debug/modules           - Detailed module state dump
- GET  /api/v1/debug/devices           - Detailed device/connection state
- GET  /api/v1/debug/events            - Recent event log entries
- GET  /api/v1/debug/config            - Full config dump (all sources)
- GET  /api/v1/debug/memory            - Memory usage by component
"""

from aiohttp import web

from ..controller import APIController
from ..middleware import is_debug_mode, set_debug_mode


def setup_debug_routes(app: web.Application, controller: APIController) -> None:
    """Register debug routes."""
    app.router.add_get("/api/v1/debug/mode", get_debug_mode_handler)
    app.router.add_post("/api/v1/debug/mode", set_debug_mode_handler)
    app.router.add_get("/api/v1/debug/modules", debug_modules_handler)
    app.router.add_get("/api/v1/debug/devices", debug_devices_handler)
    app.router.add_get("/api/v1/debug/events", debug_events_handler)
    app.router.add_get("/api/v1/debug/config", debug_config_handler)
    app.router.add_get("/api/v1/debug/memory", debug_memory_handler)
    app.router.add_get("/api/v1/debug/routes", debug_routes_handler)


async def get_debug_mode_handler(request: web.Request) -> web.Response:
    """GET /api/v1/debug/mode - Check if debug mode is enabled."""
    return web.json_response({
        "debug_mode": is_debug_mode(),
        "description": "Debug mode enables verbose error responses and request body logging",
    })


async def set_debug_mode_handler(request: web.Request) -> web.Response:
    """POST /api/v1/debug/mode - Toggle debug mode at runtime."""
    try:
        body = await request.json()
        enabled = body.get("enabled", not is_debug_mode())
    except Exception:
        enabled = not is_debug_mode()

    set_debug_mode(enabled)
    return web.json_response({
        "debug_mode": is_debug_mode(),
        "message": f"Debug mode {'enabled' if enabled else 'disabled'}",
    })


async def debug_modules_handler(request: web.Request) -> web.Response:
    """GET /api/v1/debug/modules - Detailed module state dump."""
    controller: APIController = request.app["controller"]
    ls = controller.logger_system

    modules_debug = []
    for module_info in ls.get_available_modules():
        name = module_info.name
        state = ls.get_module_state(name)
        process = ls._processes.get(name)

        module_data = {
            "name": name,
            "display_name": module_info.display_name,
            "module_id": module_info.module_id,
            "state": state.value if state else "unknown",
            "enabled": ls.is_module_enabled(name),
            "running": ls.is_module_running(name),
            "entry_point": str(module_info.entry_point),
            "config_path": str(module_info.config_path) if module_info.config_path else None,
        }

        if process:
            module_data["process"] = {
                "pid": process.process.pid if process.process else None,
                "alive": process.process.is_alive() if process.process else False,
                "start_time": process._start_time.isoformat() if hasattr(process, '_start_time') and process._start_time else None,
            }

        modules_debug.append(module_data)

    return web.json_response({
        "modules": modules_debug,
        "total": len(modules_debug),
        "running_count": sum(1 for m in modules_debug if m.get("running")),
        "enabled_count": sum(1 for m in modules_debug if m.get("enabled")),
    })


async def debug_devices_handler(request: web.Request) -> web.Response:
    """GET /api/v1/debug/devices - Detailed device and connection state."""
    controller: APIController = request.app["controller"]
    ls = controller.logger_system
    ds = ls.device_system

    devices_debug = {
        "scanning_enabled": ds._scanning_enabled,
        "discovered_devices": [],
        "connected_devices": [],
        "scanners": {},
    }

    # Get discovered devices
    for device in ds.get_discovered_devices():
        devices_debug["discovered_devices"].append({
            "id": device.id,
            "name": device.name,
            "family": device.family.value if hasattr(device.family, 'value') else str(device.family),
            "interface": device.interface.value if hasattr(device.interface, 'value') else str(device.interface),
            "address": device.address,
            "connected": device.connected,
            "metadata": device.metadata if hasattr(device, 'metadata') else {},
        })

    # Scanner status
    for name, scanner in ds._scanners.items():
        devices_debug["scanners"][name] = {
            "type": type(scanner).__name__,
            "running": getattr(scanner, '_running', False),
        }

    return web.json_response(devices_debug)


async def debug_events_handler(request: web.Request) -> web.Response:
    """GET /api/v1/debug/events - Recent event log entries."""
    controller: APIController = request.app["controller"]
    ls = controller.logger_system

    limit_str = request.query.get("limit", "50")
    try:
        limit = min(500, max(1, int(limit_str)))
    except ValueError:
        limit = 50

    events = []
    if ls.event_logger and hasattr(ls.event_logger, '_recent_events'):
        events = list(ls.event_logger._recent_events)[-limit:]
    elif ls.event_logger and ls.event_logger.event_log_path:
        try:
            with open(ls.event_logger.event_log_path, 'r') as f:
                lines = f.readlines()
                events = [line.strip() for line in lines[-limit:]]
        except Exception:
            pass

    return web.json_response({
        "events": events,
        "count": len(events),
        "limit": limit,
    })


async def debug_config_handler(request: web.Request) -> web.Response:
    """GET /api/v1/debug/config - Full configuration dump."""
    controller: APIController = request.app["controller"]
    cm = controller.config_manager

    config_debug = {
        "global": {},
        "modules": {},
        "paths": {},
    }

    # Global config
    try:
        config_debug["global"] = cm.get_all() if hasattr(cm, 'get_all') else dict(cm._config) if hasattr(cm, '_config') else {}
    except Exception as e:
        config_debug["global"] = {"error": str(e)}

    # Module configs
    for module_info in controller.logger_system.get_available_modules():
        name = module_info.name
        try:
            config = await controller.get_module_config(name)
            config_debug["modules"][name] = config
        except Exception as e:
            config_debug["modules"][name] = {"error": str(e)}

    # Important paths
    from rpi_logger.core.paths import PROJECT_ROOT, DATA_DIR, LOGS_DIR, CONFIG_PATH
    config_debug["paths"] = {
        "project_root": str(PROJECT_ROOT),
        "data_dir": str(DATA_DIR) if DATA_DIR else None,
        "logs_dir": str(LOGS_DIR),
        "config_path": str(CONFIG_PATH),
    }

    return web.json_response(config_debug)


async def debug_memory_handler(request: web.Request) -> web.Response:
    """GET /api/v1/debug/memory - Memory usage information."""
    import psutil
    import os

    process = psutil.Process(os.getpid())
    mem_info = process.memory_info()

    memory_debug = {
        "process": {
            "pid": os.getpid(),
            "rss_mb": round(mem_info.rss / (1024 * 1024), 2),
            "vms_mb": round(mem_info.vms / (1024 * 1024), 2),
            "percent": round(process.memory_percent(), 2),
        },
        "system": {
            "total_gb": round(psutil.virtual_memory().total / (1024**3), 2),
            "available_gb": round(psutil.virtual_memory().available / (1024**3), 2),
            "percent": psutil.virtual_memory().percent,
        },
    }

    # Try to get per-module memory if possible
    controller: APIController = request.app["controller"]
    ls = controller.logger_system
    module_memory = {}

    for name, proc in ls._processes.items():
        if proc.process and proc.process.is_alive():
            try:
                mp = psutil.Process(proc.process.pid)
                mi = mp.memory_info()
                module_memory[name] = {
                    "pid": proc.process.pid,
                    "rss_mb": round(mi.rss / (1024 * 1024), 2),
                }
            except Exception:
                module_memory[name] = {"error": "Could not read memory"}

    memory_debug["modules"] = module_memory

    return web.json_response(memory_debug)


async def debug_routes_handler(request: web.Request) -> web.Response:
    """GET /api/v1/debug/routes - List all registered API routes."""
    routes = []
    for resource in request.app.router.resources():
        for route in resource:
            routes.append({
                "method": route.method,
                "path": resource.canonical,
            })

    # Sort by path then method
    routes.sort(key=lambda r: (r["path"], r["method"]))

    return web.json_response({
        "routes": routes,
        "total": len(routes),
    })
