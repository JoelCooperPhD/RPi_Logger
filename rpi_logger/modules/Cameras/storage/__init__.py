"""Storage utilities for Cameras and compatible modules."""

from .pipeline import CameraStoragePipeline, StorageWriteResult
from .consumer import StorageConsumer, StorageHooks

__all__ = [
    'CameraStoragePipeline',
    'StorageWriteResult',
    'StorageConsumer',
    'StorageHooks',
]