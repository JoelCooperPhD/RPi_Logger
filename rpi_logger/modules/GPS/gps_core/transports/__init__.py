"""GPS transport implementations.

BaseGPSTransport is an alias for BaseReadOnlyTransport from core,
provided for backward compatibility with GPS-specific code.
"""

# Import base class from core - aliased as BaseGPSTransport for backward compatibility
from rpi_logger.core.devices.transports import BaseReadOnlyTransport as BaseGPSTransport

from .serial_transport import SerialGPSTransport

__all__ = ["BaseGPSTransport", "SerialGPSTransport"]
