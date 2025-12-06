"""
VOG Transports Package

Contains transport layer implementations:
- BaseTransport: Abstract base class
- USBTransport: USB Serial transport
- XBeeProxyTransport: Proxy transport for XBee via command protocol
- XBeeTransport: XBee wireless transport (from core, for direct XBee access)
"""

from .base_transport import BaseTransport
from .usb_transport import USBTransport
from .xbee_proxy_transport import XBeeProxyTransport

# Also export XBeeTransport from core for backwards compatibility
try:
    from rpi_logger.core.devices.transports import XBeeTransport
except ImportError:
    XBeeTransport = None

__all__ = [
    'BaseTransport',
    'USBTransport',
    'XBeeProxyTransport',
    'XBeeTransport',
]
