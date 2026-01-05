"""
EyeTracker Routes - Neon EyeTracker module-specific API endpoints.

This module provides REST API endpoints for interacting with Pupil Labs Neon
eye tracking hardware. These endpoints are Phase 2 of the Automation API plan,
exposing module-specific functionality beyond the generic module routes.

Endpoints:
- GET  /api/v1/modules/eyetracker/devices       - List available eye trackers
- GET  /api/v1/modules/eyetracker/config        - Get eye tracker configuration
- PUT  /api/v1/modules/eyetracker/config        - Update configuration
- GET  /api/v1/modules/eyetracker/gaze          - Get current gaze data
- GET  /api/v1/modules/eyetracker/imu           - Get current IMU data
- GET  /api/v1/modules/eyetracker/events        - Get recent eye events
- POST /api/v1/modules/eyetracker/calibrate     - Start calibration
- GET  /api/v1/modules/eyetracker/calibration   - Get calibration status
- GET  /api/v1/modules/eyetracker/status        - Get module status
"""

from aiohttp import web

from ..controller import APIController
from ..middleware import create_error_response


# Module name constant for consistency
EYETRACKER_MODULE_NAME = "EyeTracker"


def setup_eyetracker_routes(app: web.Application, controller: APIController) -> None:
    """Register EyeTracker-specific routes."""
    # Device discovery and listing
    app.router.add_get(
        "/api/v1/modules/eyetracker/devices", list_eyetracker_devices_handler
    )

    # Configuration
    app.router.add_get(
        "/api/v1/modules/eyetracker/config", get_eyetracker_config_handler
    )
    app.router.add_put(
        "/api/v1/modules/eyetracker/config", update_eyetracker_config_handler
    )

    # Real-time data streams
    app.router.add_get("/api/v1/modules/eyetracker/gaze", get_gaze_data_handler)
    app.router.add_get("/api/v1/modules/eyetracker/imu", get_imu_data_handler)
    app.router.add_get("/api/v1/modules/eyetracker/events", get_eye_events_handler)

    # Calibration
    app.router.add_post(
        "/api/v1/modules/eyetracker/calibrate", start_calibration_handler
    )
    app.router.add_get(
        "/api/v1/modules/eyetracker/calibration", get_calibration_status_handler
    )

    # Module status
    app.router.add_get("/api/v1/modules/eyetracker/status", get_eyetracker_status_handler)

    # Stream controls
    app.router.add_get(
        "/api/v1/modules/eyetracker/streams", get_stream_settings_handler
    )
    app.router.add_put(
        "/api/v1/modules/eyetracker/streams/{stream_type}", set_stream_enabled_handler
    )

    # Preview control
    app.router.add_post(
        "/api/v1/modules/eyetracker/preview/start", start_preview_handler
    )
    app.router.add_post(
        "/api/v1/modules/eyetracker/preview/stop", stop_preview_handler
    )


async def list_eyetracker_devices_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/eyetracker/devices - List available eye trackers.

    Returns all discovered Pupil Labs Neon devices on the network.
    Device discovery is performed by the main logger's network scanner.
    """
    controller: APIController = request.app["controller"]
    result = await controller.list_eyetracker_devices()
    return web.json_response(result)


async def get_eyetracker_config_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/eyetracker/config - Get eye tracker configuration.

    Returns the current configuration for the EyeTracker module including
    capture settings, preview settings, overlay configuration, and stream states.
    """
    controller: APIController = request.app["controller"]
    result = await controller.get_eyetracker_config()

    if result is None:
        return create_error_response(
            "MODULE_NOT_FOUND",
            "EyeTracker module not found or has no configuration",
            status=404,
        )

    return web.json_response(result)


async def update_eyetracker_config_handler(request: web.Request) -> web.Response:
    """PUT /api/v1/modules/eyetracker/config - Update eye tracker configuration.

    Update one or more configuration settings for the EyeTracker module.
    Settings are applied immediately if the module is running.
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
            "Request body must contain configuration updates",
            status=400,
        )

    result = await controller.update_eyetracker_config(body)

    if not result.get("success"):
        status = 404 if result.get("error") == "module_not_found" else 500
        return web.json_response(result, status=status)

    return web.json_response(result)


async def get_gaze_data_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/eyetracker/gaze - Get current gaze data.

    Returns the most recent gaze data from the eye tracker including:
    - x, y coordinates (normalized 0-1)
    - timestamp
    - worn status (whether glasses are detected as worn)
    """
    controller: APIController = request.app["controller"]
    result = await controller.get_eyetracker_gaze_data()

    if result is None:
        return create_error_response(
            "NO_DATA",
            "No gaze data available - ensure EyeTracker module is running and connected",
            status=503,
        )

    return web.json_response(result)


async def get_imu_data_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/eyetracker/imu - Get current IMU data.

    Returns the most recent IMU (Inertial Measurement Unit) data including:
    - Accelerometer readings (x, y, z)
    - Gyroscope readings (x, y, z)
    - Timestamp
    """
    controller: APIController = request.app["controller"]
    result = await controller.get_eyetracker_imu_data()

    if result is None:
        return create_error_response(
            "NO_DATA",
            "No IMU data available - ensure EyeTracker module is running and IMU stream is enabled",
            status=503,
        )

    return web.json_response(result)


async def get_eye_events_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/eyetracker/events - Get recent eye events.

    Returns recent eye tracking events including:
    - Blinks
    - Fixations
    - Saccades
    - Other eye movement events

    Query parameters:
    - limit: Maximum number of events to return (default: 10)
    """
    controller: APIController = request.app["controller"]

    # Get optional limit parameter
    limit = request.query.get("limit", "10")
    try:
        limit = int(limit)
        limit = max(1, min(limit, 100))  # Clamp between 1 and 100
    except ValueError:
        limit = 10

    result = await controller.get_eyetracker_events(limit=limit)

    if result is None:
        return create_error_response(
            "NO_DATA",
            "No eye events available - ensure EyeTracker module is running and events stream is enabled",
            status=503,
        )

    return web.json_response(result)


async def start_calibration_handler(request: web.Request) -> web.Response:
    """POST /api/v1/modules/eyetracker/calibrate - Start calibration.

    Initiates the eye tracker calibration process. Calibration is performed
    on the Neon device itself - this endpoint triggers the calibration workflow.

    Note: Calibration requires user interaction on the Neon Companion app.
    """
    controller: APIController = request.app["controller"]
    result = await controller.start_eyetracker_calibration()

    status = 200 if result.get("success") else 500
    return web.json_response(result, status=status)


async def get_calibration_status_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/eyetracker/calibration - Get calibration status.

    Returns the current calibration status of the eye tracker including:
    - is_calibrated: Whether the device has a valid calibration
    - calibration_time: Timestamp of last calibration
    - calibration_quality: Quality score if available
    """
    controller: APIController = request.app["controller"]
    result = await controller.get_eyetracker_calibration_status()

    if result is None:
        return create_error_response(
            "NO_STATUS",
            "Cannot retrieve calibration status - ensure EyeTracker module is running",
            status=503,
        )

    return web.json_response(result)


async def get_eyetracker_status_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/eyetracker/status - Get module status.

    Returns comprehensive status information for the EyeTracker module:
    - Module state (running, stopped, error)
    - Device connection status
    - Current streaming status
    - Recording status
    - FPS metrics (capture, display, record)
    """
    controller: APIController = request.app["controller"]
    result = await controller.get_eyetracker_status()
    return web.json_response(result)


async def get_stream_settings_handler(request: web.Request) -> web.Response:
    """GET /api/v1/modules/eyetracker/streams - Get stream enable states.

    Returns the enable/disable state for each stream type:
    - video: World camera video stream
    - gaze: Gaze position data stream
    - eyes: Eye camera video stream
    - imu: IMU sensor data stream
    - events: Eye events stream (blinks, fixations)
    - audio: Audio stream from scene microphone
    """
    controller: APIController = request.app["controller"]
    result = await controller.get_eyetracker_stream_settings()

    if result is None:
        return create_error_response(
            "MODULE_NOT_FOUND",
            "EyeTracker module not found",
            status=404,
        )

    return web.json_response(result)


async def set_stream_enabled_handler(request: web.Request) -> web.Response:
    """PUT /api/v1/modules/eyetracker/streams/{stream_type} - Enable/disable stream.

    Enable or disable a specific data stream. Valid stream types:
    - video, gaze, eyes, imu, events, audio

    Request body: {"enabled": true/false}
    """
    controller: APIController = request.app["controller"]
    stream_type = request.match_info["stream_type"]

    valid_streams = {"video", "gaze", "eyes", "imu", "events", "audio"}
    if stream_type not in valid_streams:
        return create_error_response(
            "INVALID_STREAM_TYPE",
            f"Invalid stream type '{stream_type}'. Valid types: {', '.join(sorted(valid_streams))}",
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

    enabled = body.get("enabled")
    if enabled is None:
        return create_error_response(
            "MISSING_ENABLED",
            "Request body must include 'enabled' field (boolean)",
            status=400,
        )

    result = await controller.set_eyetracker_stream_enabled(stream_type, bool(enabled))

    status = 200 if result.get("success") else 500
    return web.json_response(result, status=status)


async def start_preview_handler(request: web.Request) -> web.Response:
    """POST /api/v1/modules/eyetracker/preview/start - Start preview stream.

    Starts the video preview stream from the eye tracker. The preview shows
    the world camera view with optional gaze overlay.
    """
    controller: APIController = request.app["controller"]
    result = await controller.start_eyetracker_preview()

    status = 200 if result.get("success") else 500
    return web.json_response(result, status=status)


async def stop_preview_handler(request: web.Request) -> web.Response:
    """POST /api/v1/modules/eyetracker/preview/stop - Stop preview stream.

    Stops the video preview stream. This can reduce CPU usage when
    preview is not needed but tracking should continue.
    """
    controller: APIController = request.app["controller"]
    result = await controller.stop_eyetracker_preview()

    status = 200 if result.get("success") else 500
    return web.json_response(result, status=status)
