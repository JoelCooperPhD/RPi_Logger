"""Pipeline consumers and hook contracts for USB Cameras."""

from .hooks import StorageHooks
from .preview import PreviewConsumer
from .storage import StorageConsumer

__all__ = ["PreviewConsumer", "StorageConsumer", "StorageHooks"]
