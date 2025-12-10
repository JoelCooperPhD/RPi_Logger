"""
Core Device Transports Package

Contains shared transport implementations and base classes for device communication.

Base Classes:
    BaseTransport: For bidirectional communication (DRT, VOG)
    BaseReadOnlyTransport: For read-only devices (GPS)

Implementations:
    XBeeTransport: Direct XBee serial communication
    XBeeProxyTransport: XBee communication via command protocol proxy
"""

from .base_transport import BaseTransport, BaseReadOnlyTransport
from .xbee_transport import XBeeTransport
from .xbee_proxy_transport import XBeeProxyTransport

__all__ = [
    "BaseTransport",
    "BaseReadOnlyTransport",
    "XBeeTransport",
    "XBeeProxyTransport",
]
