# Capability normalization and defaults
# Task: P1.4

from .types import CameraCapabilities, CapabilityMode


def build_capabilities(raw_modes: list[CapabilityMode]) -> CameraCapabilities:
    # TODO: Implement - Task P1.4
    raise NotImplementedError("See docs/tasks/phase1_foundation.md P1.4")


def normalize_modes(modes: list[CapabilityMode]) -> list[CapabilityMode]:
    # TODO: Implement - Task P1.4
    raise NotImplementedError("See docs/tasks/phase1_foundation.md P1.4")


def select_default_preview(modes: list[CapabilityMode]) -> CapabilityMode | None:
    # TODO: Implement - Task P1.4
    raise NotImplementedError("See docs/tasks/phase1_foundation.md P1.4")


def select_default_record(modes: list[CapabilityMode]) -> CapabilityMode | None:
    # TODO: Implement - Task P1.4
    raise NotImplementedError("See docs/tasks/phase1_foundation.md P1.4")
