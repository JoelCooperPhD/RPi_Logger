"""GPS module API specification."""

from rpi_logger.core.api.module_api_loader import ModuleApiSpec


API_SPEC = ModuleApiSpec(
    module_id="gps",
    version="v1",
    description="GPS module API - position, satellites, fix quality, and NMEA data",
)
