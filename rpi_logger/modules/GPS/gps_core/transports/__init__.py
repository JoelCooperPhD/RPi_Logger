"""GPS transport implementations.

BaseGPSTransport is an alias for BaseReadOnlyTransport from core,
provided for backward compatibility with GPS-specific code.
"""

# Import base class directly from base_transport to avoid triggering XBee imports
from rpi_logger.core.devices.transports.base_transport import BaseReadOnlyTransport as BaseGPSTransport

from .serial_transport import SerialGPSTransport

__all__ = ["BaseGPSTransport", "SerialGPSTransport"]
