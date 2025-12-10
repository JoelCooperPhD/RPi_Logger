"""
DEPRECATED: Base GPS Transport

This module is deprecated. Use rpi_logger.core.devices.transports.BaseReadOnlyTransport instead.

This file is kept for backward compatibility only. All imports have been
redirected to the shared implementation in core.
"""

import warnings

warnings.warn(
    "Importing BaseGPSTransport from gps_core.transports.base_transport is deprecated. "
    "Use 'from rpi_logger.core.devices.transports import BaseReadOnlyTransport' "
    "or 'from rpi_logger.modules.GPS.gps_core.transports import BaseGPSTransport' instead.",
    DeprecationWarning,
    stacklevel=2
)

# Re-export from core for backward compatibility (aliased as BaseGPSTransport)
from rpi_logger.core.devices.transports import BaseReadOnlyTransport as BaseGPSTransport

__all__ = ["BaseGPSTransport"]
