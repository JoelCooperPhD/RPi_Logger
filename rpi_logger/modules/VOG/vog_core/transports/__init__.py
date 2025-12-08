"""VOG Transports Package.

Transport layer implementations:
- BaseTransport: Abstract base class
- USBTransport: USB Serial transport
- XBeeProxyTransport: Proxy transport for XBee via command protocol (shared)
"""

from .base_transport import BaseTransport
from .usb_transport import USBTransport

# Import shared XBeeProxyTransport from core
from rpi_logger.core.devices.transports import XBeeProxyTransport

__all__ = [
    'BaseTransport',
    'USBTransport',
    'XBeeProxyTransport',
]
