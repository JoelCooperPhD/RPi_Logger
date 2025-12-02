"""VOG protocol implementations for different device variants."""

from .base_protocol import BaseVOGProtocol, VOGDataPacket, VOGResponse
from .svog_protocol import SVOGProtocol
from .wvog_protocol import WVOGProtocol

__all__ = [
    'BaseVOGProtocol',
    'VOGDataPacket',
    'VOGResponse',
    'SVOGProtocol',
    'WVOGProtocol',
]
