"""EyeTracker module API specification."""

from rpi_logger.core.api.module_api_loader import ModuleApiSpec


API_SPEC = ModuleApiSpec(
    module_id="eyetracker",
    version="v1",
    description="EyeTracker (Pupil Labs Neon) module API - gaze data, IMU, calibration, streams",
)
