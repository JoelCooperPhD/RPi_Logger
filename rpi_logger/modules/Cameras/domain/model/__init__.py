"""Model package for the Cameras runtime."""

from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger(__name__)
logger.debug("Domain.model package initialized")

from .runtime_state import (
    CameraModel,
    CapturedFrame,
    FrameGate,
    FramePayload,
)
from ..pipelines import ImagePipeline, PipelineMetrics, RollingFpsCounter

__all__ = [
    "CameraModel",
    "CapturedFrame",
    "FrameGate",
    "FramePayload",
    "ImagePipeline",
    "PipelineMetrics",
    "RollingFpsCounter",
]
