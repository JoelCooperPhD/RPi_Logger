"""Cameras module API specification."""

from rpi_logger.core.api.module_api_loader import ModuleApiSpec


API_SPEC = ModuleApiSpec(
    module_id="cameras",
    version="v1",
    description="Cameras (USB webcam) module API - device listing, preview, snapshots, resolution/fps control",
)
