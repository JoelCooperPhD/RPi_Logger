"""
DEPRECATED: Base Transport

This module is deprecated. Use rpi_logger.core.devices.transports.BaseTransport instead.

This file is kept for backward compatibility only. All imports have been
redirected to the shared implementation in core.
"""

import warnings

warnings.warn(
    "Importing BaseTransport from vog_core.transports.base_transport is deprecated. "
    "Use 'from rpi_logger.core.devices.transports import BaseTransport' instead.",
    DeprecationWarning,
    stacklevel=2
)

# Re-export from core for backward compatibility
from rpi_logger.core.devices.transports import BaseTransport

__all__ = ["BaseTransport"]
