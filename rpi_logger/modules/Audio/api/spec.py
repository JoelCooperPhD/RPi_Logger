"""Audio module API specification."""

from rpi_logger.core.api.module_api_loader import ModuleApiSpec


API_SPEC = ModuleApiSpec(
    module_id="audio",
    version="v1",
    description="Audio module API - device management, recording, and levels",
)
