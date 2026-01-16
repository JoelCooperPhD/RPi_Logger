"""
API Middleware - Security and error handling for REST API.

Provides:
- Localhost-only access enforcement
- Unified error response formatting
- Request logging
- Debug mode with verbose errors
"""

import time
import traceback
from typing import Callable, Optional

from aiohttp import web

from rpi_logger.core.logging_utils import get_module_logger


logger = get_module_logger("APIMiddleware")

# Debug mode flag - set via APIServer or environment
_debug_mode: bool = False


def set_debug_mode(enabled: bool) -> None:
    """Enable or disable debug mode for verbose error responses."""
    global _debug_mode
    _debug_mode = enabled
    logger.info("API debug mode %s", "enabled" if enabled else "disabled")


def is_debug_mode() -> bool:
    """Check if debug mode is enabled."""
    return _debug_mode


@web.middleware
async def localhost_only_middleware(request: web.Request, handler: Callable) -> web.Response:
    """
    Middleware to restrict API access to localhost only.

    Rejects requests from any IP other than 127.0.0.1 or ::1.
    """
    # Get the peer IP address
    peername = request.transport.get_extra_info("peername")
    if peername:
        remote_ip = peername[0]

        # Allow localhost IPv4 and IPv6
        localhost_ips = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}

        if remote_ip not in localhost_ips:
            logger.warning("Rejected request from non-localhost IP: %s", remote_ip)
            return web.json_response(
                {
                    "error": {
                        "code": "ACCESS_DENIED",
                        "message": "API access is restricted to localhost only",
                    },
                    "status": 403,
                },
                status=403,
            )

    return await handler(request)


@web.middleware
async def request_logging_middleware(request: web.Request, handler: Callable) -> web.Response:
    """
    Middleware to log all API requests and responses for debugging.

    Logs:
    - Request method, path, query params
    - Response status and timing
    - Request body (in debug mode)
    """
    start_time = time.perf_counter()
    method = request.method
    path = request.path
    query = dict(request.query) if request.query else None


    try:
        response = await handler(request)
        return response
    except Exception:
        raise


@web.middleware
async def error_handling_middleware(request: web.Request, handler: Callable) -> web.Response:
    """
    Middleware to catch and format all errors as JSON responses.

    Provides unified error response format:
    {
        "error": {
            "code": "ERROR_CODE",
            "message": "Human-readable message",
            "details": { ... }  # Optional
        },
        "status": 500
    }
    """
    try:
        return await handler(request)
    except web.HTTPException as e:
        # aiohttp HTTP exceptions (404, 400, etc.)
        return web.json_response(
            {
                "error": {
                    "code": e.reason.upper().replace(" ", "_") if e.reason else "HTTP_ERROR",
                    "message": e.text or str(e),
                },
                "status": e.status,
            },
            status=e.status,
        )
    except ValueError as e:
        # Validation errors
        logger.warning("Validation error: %s", e)
        return web.json_response(
            {
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": str(e),
                },
                "status": 400,
            },
            status=400,
        )
    except KeyError as e:
        # Missing required fields
        logger.warning("Missing field: %s", e)
        return web.json_response(
            {
                "error": {
                    "code": "MISSING_FIELD",
                    "message": f"Missing required field: {e}",
                },
                "status": 400,
            },
            status=400,
        )
    except Exception as e:
        # Unexpected errors
        tb = traceback.format_exc()
        logger.error("Unexpected error: %s\n%s", e, tb)

        error_response = {
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
                "details": {
                    "type": type(e).__name__,
                    "message": str(e),
                },
            },
            "status": 500,
        }

        # In debug mode, include full stack trace
        if _debug_mode:
            error_response["error"]["details"]["traceback"] = tb.split("\n")
            error_response["error"]["details"]["request"] = {
                "method": request.method,
                "path": request.path,
                "query": dict(request.query) if request.query else None,
            }

        return web.json_response(error_response, status=500)


def create_json_response(data: dict, status: int = 200) -> web.Response:
    """Create JSON response with proper content type."""
    return web.json_response(data, status=status)


def create_error_response(code: str, message: str, status: int = 400, details: dict = None) -> web.Response:
    """Create standardized error response."""
    error = {"error": {"code": code, "message": message}, "status": status}
    if details:
        error["error"]["details"] = details
    return web.json_response(error, status=status)


async def parse_json_body(request: web.Request, required: bool = True):
    """Parse JSON body with error handling. Returns (body, error_response)."""
    try:
        body = await request.json()
    except Exception:
        if required:
            return None, create_error_response("INVALID_BODY", "Request body must be valid JSON", status=400)
        return {}, None
    if required and not body:
        return None, create_error_response("EMPTY_BODY", "Request body must contain data", status=400)
    return body, None


def result_to_response(result, not_found_code: str = "NOT_FOUND", not_found_msg: str = "Resource not found"):
    """Convert controller result dict to response, handling success/error patterns."""
    if result is None:
        return create_error_response(not_found_code, not_found_msg, status=404)
    if isinstance(result, dict) and result.get("error"):
        return create_error_response(result.get("error_code", "ERROR"), result["error"], status=400)
    if isinstance(result, dict) and "success" in result:
        return web.json_response(result, status=200 if result["success"] else 400)
    return web.json_response(result)
