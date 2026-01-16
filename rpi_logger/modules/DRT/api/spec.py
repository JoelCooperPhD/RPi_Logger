"""DRT module API specification."""

from rpi_logger.core.api.module_api_loader import ModuleApiSpec


API_SPEC = ModuleApiSpec(
    module_id="drt",
    version="v1",
    description="DRT (Detection Response Task) module API - devices, stimulus, responses, statistics",
)
