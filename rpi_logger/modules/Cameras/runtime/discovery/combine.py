"""Combine discovery results from multiple backends."""

from __future__ import annotations

from typing import Dict, Iterable, List

from rpi_logger.modules.Cameras.runtime import CameraDescriptor, CameraId


def merge_descriptors(
    usb: Iterable[CameraDescriptor],
    picam: Iterable[CameraDescriptor],
) -> List[CameraDescriptor]:
    """Merge descriptors, preferring picam when stable_id clashes."""

    combined: Dict[str, CameraDescriptor] = {}
    for desc in usb:
        combined[desc.camera_id.key] = desc
    for desc in picam:
        combined[desc.camera_id.key] = desc
    return list(combined.values())


__all__ = ["merge_descriptors"]
