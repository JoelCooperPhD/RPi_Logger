"""VOG module API specification."""

from rpi_logger.core.api.module_api_loader import ModuleApiSpec


API_SPEC = ModuleApiSpec(
    module_id="vog",
    version="v1",
    description="VOG (Video Oculography Goggles) module API - devices, lens control, eye position",
)
