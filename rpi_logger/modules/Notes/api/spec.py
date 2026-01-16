"""Notes module API specification."""

from rpi_logger.core.api.module_api_loader import ModuleApiSpec


API_SPEC = ModuleApiSpec(
    module_id="notes",
    version="v1",
    description="Notes module API - manage session notes and annotations",
)
