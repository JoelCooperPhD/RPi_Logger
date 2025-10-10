#!/usr/bin/env python3
"""Modern web-based dashboard for RPi Logger.

Provides a Flask web server with REST API and real-time video streaming.
"""

import asyncio
import cv2
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Flask, jsonify, render_template, request, Response
from flask_cors import CORS
import numpy as np

from ui.backend import (
    AudioConfig,
    AudioRecorderService,
    CameraConfig,
    CameraProcessService,
    DashboardBackend,
    DashboardConfig,
    EyeTrackerConfig,
    EyeTrackerService,
    ModuleSupervisor,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger("WebDashboard")

# Initialize Flask app
app = Flask(__name__, template_folder="ui/templates", static_folder="ui/static")
CORS(app)

# Global backend instance
backend: Optional[DashboardBackend] = None
event_loop: Optional[asyncio.AbstractEventLoop] = None
loop_thread: Optional[threading.Thread] = None


def run_async_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Run the asyncio event loop in a separate thread."""
    asyncio.set_event_loop(loop)
    loop.run_forever()


async def initialize_backend() -> DashboardBackend:
    """Initialize the backend with default configuration."""
    config = DashboardConfig(
        camera=CameraConfig(
            resolution=(1280, 720),
            target_fps=25.0,
            discovery_timeout=5.0,
            min_cameras=2,
            allow_partial=True,
            output_dir=Path("recordings/camera"),
        ),
        eye_tracker=EyeTrackerConfig(
            output_dir=Path("recordings/eye_tracker"),
            auto_connect=True,
            discovery_timeout=10.0,
            reconnect_interval=5.0,
        ),
        audio=AudioConfig(
            sample_rate=48000,
            output_dir=Path("recordings/audio"),
            auto_select_new=True,
        ),
    )

    dashboard = DashboardBackend(config)
    await dashboard.setup()

    # Auto-start camera module to detect available cameras
    logger.info("Starting camera detection...")
    try:
        await dashboard.camera.start()
        logger.info("Camera module started for detection")
    except Exception as e:
        logger.warning(f"Failed to start camera module: {e}")

    # Auto-start audio module to detect microphones
    logger.info("Starting audio detection...")
    try:
        await dashboard.audio.start()
        logger.info("Audio module started for detection")
    except Exception as e:
        logger.warning(f"Failed to start audio module: {e}")

    logger.info("Backend initialized successfully")
    return dashboard


def get_backend() -> DashboardBackend:
    """Get the global backend instance."""
    if backend is None:
        raise RuntimeError("Backend not initialized")
    return backend


def run_coroutine(coro):
    """Run a coroutine in the event loop from a sync context."""
    if event_loop is None:
        raise RuntimeError("Event loop not initialized")
    future = asyncio.run_coroutine_threadsafe(coro, event_loop)
    return future.result(timeout=30)


def generate_placeholder_frame(text: str, width: int = 640, height: int = 480):
    """Generate a placeholder frame with text."""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:] = (26, 42, 82)  # Dark blue background

    # Add text
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.7
    thickness = 2
    text_size = cv2.getTextSize(text, font, font_scale, thickness)[0]
    text_x = (width - text_size[0]) // 2
    text_y = (height + text_size[1]) // 2
    cv2.putText(frame, text, (text_x, text_y), font, font_scale, (158, 173, 255), thickness)

    return frame


def generate_eye_tracker_frames():
    """Generate frames from the eye tracker scene camera."""
    while True:
        try:
            b = get_backend()
            eye_tracker = b.eye_tracker._controller.eye_tracker if b.eye_tracker._controller else None

            if eye_tracker and eye_tracker._last_frame is not None:
                frame = eye_tracker._last_frame.copy()

                # Draw gaze overlay if available
                if eye_tracker._last_gaze:
                    gaze = eye_tracker._last_gaze
                    height, width = frame.shape[:2]
                    x = int(gaze.x * width)
                    y = int(gaze.y * height)

                    # Draw crosshair
                    cv2.circle(frame, (x, y), 20, (0, 255, 0), 2)
                    cv2.line(frame, (x - 30, y), (x + 30, y), (0, 255, 0), 2)
                    cv2.line(frame, (x, y - 30), (x, y + 30), (0, 255, 0), 2)

                    # Draw status text
                    status_text = f"Gaze: ({gaze.x:.2f}, {gaze.y:.2f})"
                    cv2.putText(frame, status_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            else:
                frame = generate_placeholder_frame("Eye Tracker Not Connected", 640, 480)

            # Encode frame as JPEG
            ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if not ret:
                continue

            frame_bytes = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

            time.sleep(0.033)  # ~30 FPS

        except Exception as e:
            logger.error(f"Error in eye tracker frame generation: {e}")
            frame = generate_placeholder_frame("Eye Tracker Error", 640, 480)
            ret, buffer = cv2.imencode('.jpg', frame)
            if ret:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            time.sleep(1)


# ============================================================================
# API Routes
# ============================================================================

@app.route("/")
def index():
    """Serve the main dashboard page."""
    return render_template("dashboard.html")


@app.route("/api/status")
def get_status():
    """Get status of all modules."""
    try:
        b = get_backend()
        status = {}

        for name, service in b.modules.items():
            # Get latest status from each module
            module_status = {
                "name": name,
                "state": service._state.value,
                "recording": service._recording,
                "summary": service._summary,
                "details": service._details,
            }
            status[name] = module_status

        return jsonify({"success": True, "modules": status})
    except Exception as e:
        logger.exception("Failed to get status")
        return jsonify({"success": False, "error": str(e)}), 500


def generate_camera_frames(camera_id: int):
    """Generate frames from a specific camera."""
    while True:
        try:
            b = get_backend()

            # Get the latest frame from the camera subprocess
            frame_bytes = run_coroutine(b.camera.get_preview_frame(camera_id))

            if frame_bytes:
                # Frame is already JPEG-encoded, send directly
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            else:
                # No frame available, show placeholder
                frame = generate_placeholder_frame(f"Camera {camera_id} - Waiting for Frame", 640, 480)
                ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if ret:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

            time.sleep(0.033)  # ~30 FPS

        except Exception as e:
            logger.error(f"Error in camera {camera_id} frame generation: {e}")
            frame = generate_placeholder_frame(f"Camera {camera_id} Error", 640, 480)
            ret, buffer = cv2.imencode('.jpg', frame)
            if ret:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            time.sleep(1)


@app.route("/video/eye_tracker")
def video_eye_tracker():
    """Stream video from eye tracker."""
    return Response(generate_eye_tracker_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route("/video/camera/<int:camera_id>")
def video_camera(camera_id: int):
    """Stream video from a specific camera."""
    return Response(generate_camera_frames(camera_id),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route("/api/module/<module_name>/start", methods=["POST"])
def start_module(module_name: str):
    """Start a specific module."""
    try:
        b = get_backend()
        service = b.modules.get(module_name)

        if not service:
            return jsonify({"success": False, "error": f"Module '{module_name}' not found"}), 404

        run_coroutine(service.start())
        return jsonify({"success": True, "message": f"Module '{module_name}' started"})
    except Exception as e:
        logger.exception(f"Failed to start module {module_name}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/module/<module_name>/stop", methods=["POST"])
def stop_module(module_name: str):
    """Stop a specific module."""
    try:
        b = get_backend()
        service = b.modules.get(module_name)

        if not service:
            return jsonify({"success": False, "error": f"Module '{module_name}' not found"}), 404

        run_coroutine(service.stop())
        return jsonify({"success": True, "message": f"Module '{module_name}' stopped"})
    except Exception as e:
        logger.exception(f"Failed to stop module {module_name}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/module/<module_name>/start_recording", methods=["POST"])
def start_recording(module_name: str):
    """Start recording on a specific module."""
    try:
        b = get_backend()
        service = b.modules.get(module_name)

        if not service:
            return jsonify({"success": False, "error": f"Module '{module_name}' not found"}), 404

        # Handle both JSON and empty body
        session_name = None
        if request.is_json:
            try:
                if request.json:
                    session_name = request.json.get("session_name")
            except:
                pass

        run_coroutine(service.start_recording(session_name))
        return jsonify({"success": True, "message": f"Recording started on '{module_name}'"})
    except Exception as e:
        logger.exception(f"Failed to start recording on {module_name}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/module/<module_name>/stop_recording", methods=["POST"])
def stop_recording(module_name: str):
    """Stop recording on a specific module."""
    try:
        b = get_backend()
        service = b.modules.get(module_name)

        if not service:
            return jsonify({"success": False, "error": f"Module '{module_name}' not found"}), 404

        run_coroutine(service.stop_recording())
        return jsonify({"success": True, "message": f"Recording stopped on '{module_name}'"})
    except Exception as e:
        logger.exception(f"Failed to stop recording on {module_name}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/start_all", methods=["POST"])
def start_all_modules():
    """Start all modules."""
    try:
        b = get_backend()
        run_coroutine(b.start_all())
        return jsonify({"success": True, "message": "All modules started"})
    except Exception as e:
        logger.exception("Failed to start all modules")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/stop_all", methods=["POST"])
def stop_all_modules():
    """Stop all modules."""
    try:
        b = get_backend()
        run_coroutine(b.stop_all())
        return jsonify({"success": True, "message": "All modules stopped"})
    except Exception as e:
        logger.exception("Failed to stop all modules")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/start_all_recording", methods=["POST"])
def start_all_recording():
    """Start recording on all modules."""
    try:
        b = get_backend()
        session_name = request.json.get("session_name") if request.json else None

        for name, service in b.modules.items():
            if service._state.value in ["ready", "reconnecting"]:
                try:
                    run_coroutine(service.start_recording(session_name))
                except Exception as e:
                    logger.error(f"Failed to start recording on {name}: {e}")

        return jsonify({"success": True, "message": "Recording started on all available modules"})
    except Exception as e:
        logger.exception("Failed to start recording on all modules")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/stop_all_recording", methods=["POST"])
def stop_all_recording():
    """Stop recording on all modules."""
    try:
        b = get_backend()

        for name, service in b.modules.items():
            if service._recording:
                try:
                    run_coroutine(service.stop_recording())
                except Exception as e:
                    logger.error(f"Failed to stop recording on {name}: {e}")

        return jsonify({"success": True, "message": "Recording stopped on all modules"})
    except Exception as e:
        logger.exception("Failed to stop recording on all modules")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/camera/preview/<int:camera_id>/toggle", methods=["POST"])
def toggle_camera_preview(camera_id: int):
    """Toggle preview streaming for a specific camera."""
    try:
        b = get_backend()

        # Get enabled state from request
        enabled = True
        if request.is_json and request.json:
            enabled = request.json.get("enabled", True)

        # Send toggle command to camera subprocess
        run_coroutine(b.camera.toggle_preview(camera_id, enabled))

        return jsonify({
            "success": True,
            "message": f"Camera {camera_id} preview {'enabled' if enabled else 'disabled'}"
        })
    except Exception as e:
        logger.exception(f"Failed to toggle preview for camera {camera_id}")
        return jsonify({"success": False, "error": str(e)}), 500


def main():
    """Main entry point."""
    global backend, event_loop, loop_thread

    # Create and start the event loop in a separate thread
    event_loop = asyncio.new_event_loop()
    loop_thread = threading.Thread(target=run_async_loop, args=(event_loop,), daemon=True)
    loop_thread.start()

    # Initialize backend
    logger.info("Initializing backend...")
    backend = run_coroutine(initialize_backend())

    # Start Flask server
    logger.info("Starting web server on http://0.0.0.0:5020")
    logger.info("Open your browser and navigate to http://localhost:5020")

    try:
        app.run(host="0.0.0.0", port=5020, debug=False, threaded=True)
    finally:
        # Cleanup
        logger.info("Shutting down...")
        if backend:
            run_coroutine(backend.shutdown())
        if event_loop:
            event_loop.call_soon_threadsafe(event_loop.stop)


if __name__ == "__main__":
    main()
