"""
Testing Module Routes - Testing and Verification API endpoints.

Provides endpoints for running tests, hardware detection, and data validation.

Endpoints:
- POST /api/v1/test/record-cycle               - Run complete record cycle test
- POST /api/v1/test/module/{name}              - Run module-specific tests
- GET  /api/v1/test/hardware-matrix            - Get hardware availability matrix
- POST /api/v1/test/validate-session/{path}    - Validate recorded session data
- GET  /api/v1/test/schemas                    - Get all data validation schemas
- POST /api/v1/test/schema/{module}            - Validate data against schema
- GET  /api/v1/test/status                     - Get test runner status
- POST /api/v1/test/cancel                     - Cancel running test
"""

from aiohttp import web

from ..controller import APIController
from ..middleware import create_error_response


def setup_testing_routes(app: web.Application, controller: APIController) -> None:
    """Register testing and verification routes."""
    # Record cycle test
    app.router.add_post("/api/v1/test/record-cycle", run_record_cycle_test_handler)

    # Module-specific tests
    app.router.add_post("/api/v1/test/module/{name}", run_module_test_handler)

    # Hardware detection
    app.router.add_get("/api/v1/test/hardware-matrix", get_hardware_matrix_handler)

    # Session validation
    app.router.add_post(
        "/api/v1/test/validate-session/{path:.*}", validate_session_handler
    )

    # Schema endpoints
    app.router.add_get("/api/v1/test/schemas", get_validation_schemas_handler)
    app.router.add_post("/api/v1/test/schema/{module}", validate_against_schema_handler)

    # Test runner status/control
    app.router.add_get("/api/v1/test/status", get_test_status_handler)
    app.router.add_post("/api/v1/test/cancel", cancel_test_handler)


async def run_record_cycle_test_handler(request: web.Request) -> web.Response:
    """POST /api/v1/test/record-cycle - Run a complete record cycle test."""
    controller: APIController = request.app["controller"]

    # Parse optional config from body
    config = {}
    try:
        body = await request.json()
        if body:
            config = body
    except Exception:
        pass  # Empty body is OK, use defaults

    # Validate config parameters
    if "duration_seconds" in config:
        try:
            duration = float(config["duration_seconds"])
            if duration <= 0 or duration > 300:
                return create_error_response(
                    "INVALID_PARAMETER",
                    "duration_seconds must be between 0 and 300",
                    status=400,
                )
            config["duration_seconds"] = duration
        except (TypeError, ValueError):
            return create_error_response(
                "INVALID_PARAMETER",
                "duration_seconds must be a number",
                status=400,
            )

    if "modules" in config:
        if not isinstance(config["modules"], list):
            return create_error_response(
                "INVALID_PARAMETER",
                "modules must be a list of module names",
                status=400,
            )

    result = await controller.run_record_cycle_test(config)

    if not result.get("success"):
        status = 500
        if result.get("error") == "test_already_running":
            status = 409
        elif result.get("error") in ("session_already_active", "invalid_config"):
            status = 400
        return web.json_response(result, status=status)

    return web.json_response(result)


async def run_module_test_handler(request: web.Request) -> web.Response:
    """POST /api/v1/test/module/{name} - Run module-specific tests."""
    controller: APIController = request.app["controller"]
    module_name = request.match_info["name"]

    # Parse optional test type from body
    test_type = "basic"
    try:
        body = await request.json()
        if body and "test_type" in body:
            test_type = body["test_type"]
            if test_type not in ("basic", "connection", "recording", "full"):
                return create_error_response(
                    "INVALID_PARAMETER",
                    "test_type must be one of: basic, connection, recording, full",
                    status=400,
                )
    except Exception:
        pass  # Empty body is OK, use default

    result = await controller.run_module_test(module_name, test_type)

    if not result.get("success"):
        status = 500
        if result.get("error") == "module_not_found":
            status = 404
        elif result.get("error") == "test_already_running":
            status = 409
        elif result.get("error") == "hardware_not_available":
            status = 503
        return web.json_response(result, status=status)

    return web.json_response(result)


async def get_hardware_matrix_handler(request: web.Request) -> web.Response:
    """GET /api/v1/test/hardware-matrix - Get hardware availability matrix."""
    controller: APIController = request.app["controller"]
    result = await controller.get_hardware_matrix()
    return web.json_response(result)


async def validate_session_handler(request: web.Request) -> web.Response:
    """POST /api/v1/test/validate-session/{path} - Validate recorded session data."""
    controller: APIController = request.app["controller"]
    session_path = "/" + request.match_info["path"]

    # Validate the path exists
    from pathlib import Path

    if not Path(session_path).exists():
        return create_error_response(
            "PATH_NOT_FOUND",
            f"Session path does not exist: {session_path}",
            status=404,
        )

    if not Path(session_path).is_dir():
        return create_error_response(
            "INVALID_PATH",
            "Session path must be a directory",
            status=400,
        )

    result = await controller.validate_session(session_path)

    if not result.get("success"):
        status = 500
        if result.get("error") == "path_not_found":
            status = 404
        elif result.get("error") == "invalid_path":
            status = 400
        return web.json_response(result, status=status)

    return web.json_response(result)


async def get_validation_schemas_handler(request: web.Request) -> web.Response:
    """GET /api/v1/test/schemas - Get all data validation schemas."""
    controller: APIController = request.app["controller"]
    result = await controller.get_validation_schemas()
    return web.json_response(result)


async def validate_against_schema_handler(request: web.Request) -> web.Response:
    """POST /api/v1/test/schema/{module} - Validate data against module schema."""
    controller: APIController = request.app["controller"]
    module_name = request.match_info["module"]

    # Parse body for data path
    try:
        body = await request.json()
    except Exception:
        return create_error_response(
            "INVALID_BODY",
            "Request body must be valid JSON",
            status=400,
        )

    if not body or "data_path" not in body:
        return create_error_response(
            "MISSING_FIELD",
            "Request body must include 'data_path' field",
            status=400,
        )

    data_path = body["data_path"]

    # Validate the path exists
    from pathlib import Path

    if not Path(data_path).exists():
        return create_error_response(
            "FILE_NOT_FOUND",
            f"Data file does not exist: {data_path}",
            status=404,
        )

    if not Path(data_path).is_file():
        return create_error_response(
            "INVALID_PATH",
            "data_path must be a file",
            status=400,
        )

    result = await controller.validate_against_schema(module_name, data_path)

    if not result.get("success"):
        status = 500
        if result.get("error") == "module_not_found":
            status = 404
        elif result.get("error") == "schema_not_found":
            status = 404
        elif result.get("error") == "file_not_found":
            status = 404
        return web.json_response(result, status=status)

    return web.json_response(result)


async def get_test_status_handler(request: web.Request) -> web.Response:
    """GET /api/v1/test/status - Get test runner status."""
    controller: APIController = request.app["controller"]
    result = await controller.get_test_status()
    return web.json_response(result)


async def cancel_test_handler(request: web.Request) -> web.Response:
    """POST /api/v1/test/cancel - Cancel a running test."""
    controller: APIController = request.app["controller"]
    result = await controller.cancel_test()

    if not result.get("success"):
        status = 500
        if result.get("error") == "no_test_running":
            status = 400
        elif result.get("error") == "cannot_cancel":
            status = 409
        return web.json_response(result, status=status)

    return web.json_response(result)
