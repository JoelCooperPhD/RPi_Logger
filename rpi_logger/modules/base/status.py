"""
Standard status reporting for all RPi Logger modules.

Defines consistent JSON status format for module communication.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict, Any


class ModuleState(Enum):
    """Standard module states"""
    STARTING = "starting"           # Module initializing
    IDLE = "idle"                   # Ready, not recording
    RECORDING = "recording"         # Actively recording
    PAUSED = "paused"              # Recording or processing paused
    STOPPING = "stopping"           # Shutting down
    ERROR = "error"                # Error state
    CRASHED = "crashed"            # Unexpected termination


class StatusType(Enum):
    """Type of status message"""
    READY = "ready"                    # Module ready
    STATUS_REPORT = "status_report"    # Response to get_status
    RECORDING_STARTED = "recording_started"
    RECORDING_STOPPED = "recording_stopped"
    RECORDING_PAUSED = "recording_paused"
    RECORDING_RESUMED = "recording_resumed"
    SNAPSHOT_TAKEN = "snapshot_taken"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    SHUTDOWN = "shutdown"


@dataclass
class ModuleStatus:
    """
    Standard status report for all modules.

    This is the canonical status format returned by all modules
    in response to commands or async events.
    """
    # === Message Type ===
    type: str                              # "status"
    status: StatusType                     # StatusType enum value
    timestamp: str                         # ISO-8601 timestamp

    # === Module Identity ===
    module_name: str                       # "EyeTracker", "Cameras", etc.
    module_version: str = "1.0.0"

    # === State ===
    state: ModuleState = ModuleState.IDLE

    # === Performance Metrics ===
    fps_current: Optional[float] = None
    fps_target: Optional[float] = None
    frames_captured: int = 0
    frames_dropped: int = 0

    # === Recording Info ===
    recording_active: bool = False
    recording_duration: Optional[float] = None  # Seconds
    recording_path: Optional[str] = None

    # === Errors and Warnings ===
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    # === Command-Specific Data ===
    data: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict:
        """Convert to JSON-serializable dictionary"""
        result = asdict(self)

        # Convert enums to strings
        result['status'] = self.status.value
        result['state'] = self.state.value

        # Convert timestamp to ISO format if datetime object
        if isinstance(self.timestamp, datetime):
            result['timestamp'] = self.timestamp.isoformat()

        return result

    @classmethod
    def from_json(cls, data: dict) -> 'ModuleStatus':
        """Create from JSON dictionary"""
        data = data.copy()

        # Convert strings to enums
        if 'status' in data and isinstance(data['status'], str):
            data['status'] = StatusType(data['status'])
        if 'state' in data and isinstance(data['state'], str):
            data['state'] = ModuleState(data['state'])

        return cls(**data)

    def to_json_string(self) -> str:
        """Convert to JSON string for stdout"""
        import json
        return json.dumps(self.to_json())


# === Convenience Constructors ===

def create_ready_status(module_name: str) -> ModuleStatus:
    """Create 'ready' status message"""
    return ModuleStatus(
        type="status",
        status=StatusType.READY,
        timestamp=datetime.now().isoformat(),
        module_name=module_name,
        state=ModuleState.IDLE,
    )


def create_error_status(module_name: str, error_message: str,
                       current_state: ModuleState = ModuleState.ERROR) -> ModuleStatus:
    """Create 'error' status message"""
    return ModuleStatus(
        type="status",
        status=StatusType.ERROR,
        timestamp=datetime.now().isoformat(),
        module_name=module_name,
        state=current_state,
        errors=[error_message],
    )


def create_recording_started_status(module_name: str, recording_path: Path,
                                   fps_target: float) -> ModuleStatus:
    """Create 'recording started' status message"""
    return ModuleStatus(
        type="status",
        status=StatusType.RECORDING_STARTED,
        timestamp=datetime.now().isoformat(),
        module_name=module_name,
        state=ModuleState.RECORDING,
        recording_active=True,
        recording_path=str(recording_path),
        fps_target=fps_target,
        data={'message': 'Recording started successfully'}
    )


def create_recording_stopped_status(module_name: str, recording_path: Path,
                                   duration: float, frames_written: int,
                                   frames_dropped: int) -> ModuleStatus:
    """Create 'recording stopped' status message"""
    return ModuleStatus(
        type="status",
        status=StatusType.RECORDING_STOPPED,
        timestamp=datetime.now().isoformat(),
        module_name=module_name,
        state=ModuleState.IDLE,
        recording_active=False,
        recording_path=str(recording_path),
        recording_duration=duration,
        frames_captured=frames_written,
        frames_dropped=frames_dropped,
        data={
            'message': 'Recording stopped',
            'output_files': [str(recording_path)],
        }
    )
