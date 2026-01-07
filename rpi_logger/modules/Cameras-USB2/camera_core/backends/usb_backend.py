# USB camera backend - probe and control
# Task: P1.3

from ..types import CameraCapabilities, CapabilityMode, ControlInfo, CameraId


class ProbeError(Exception):
    def __init__(self, device_path: str, reason: str):
        self.device_path = device_path
        self.reason = reason
        super().__init__(f"Probe failed for {device_path}: {reason}")


class DeviceLost(Exception):
    def __init__(self, camera_id: CameraId):
        self.camera_id = camera_id
        super().__init__(f"Device lost: {camera_id}")


async def probe(device_path: str) -> CameraCapabilities:
    # TODO: Implement - Task P1.3
    raise NotImplementedError("See docs/tasks/phase1_foundation.md P1.3")


async def set_control(device_path: str, control: str, value: int) -> None:
    # TODO: Implement - Task P1.3
    raise NotImplementedError("See docs/tasks/phase1_foundation.md P1.3")


async def get_control(device_path: str, control: str) -> int:
    # TODO: Implement - Task P1.3
    raise NotImplementedError("See docs/tasks/phase1_foundation.md P1.3")
