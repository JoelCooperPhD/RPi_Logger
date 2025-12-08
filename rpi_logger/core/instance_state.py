"""
Instance State - Lifecycle state tracking for module instances.

This module defines the state machine for module instance lifecycle,
providing a single source of truth for instance state that can be
used to derive UI state.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import time


class InstanceState(Enum):
    """Lifecycle state of a module instance."""
    STOPPED = "stopped"           # Not running
    STARTING = "starting"         # Process spawned, waiting for ready
    RUNNING = "running"           # Process running, no device assigned
    CONNECTING = "connecting"     # Device assignment sent, waiting for ack
    CONNECTED = "connected"       # Device connected and ready
    DISCONNECTING = "disconnecting"  # Unassign sent, waiting for ack
    STOPPING = "stopping"         # Quit sent, waiting for exit


# Valid state transitions
VALID_TRANSITIONS = {
    InstanceState.STOPPED: {InstanceState.STARTING},
    InstanceState.STARTING: {InstanceState.RUNNING, InstanceState.CONNECTED, InstanceState.STOPPED},  # CONNECTED for internal modules
    InstanceState.RUNNING: {InstanceState.CONNECTING, InstanceState.STOPPING, InstanceState.STOPPED},
    InstanceState.CONNECTING: {InstanceState.CONNECTED, InstanceState.RUNNING, InstanceState.STOPPING, InstanceState.STOPPED},
    InstanceState.CONNECTED: {InstanceState.DISCONNECTING, InstanceState.STOPPING, InstanceState.STOPPED},
    InstanceState.DISCONNECTING: {InstanceState.RUNNING, InstanceState.STOPPING, InstanceState.STOPPED},
    InstanceState.STOPPING: {InstanceState.STOPPED},
}

# Timeouts for each state (seconds) - how long we wait before taking action
STATE_TIMEOUTS = {
    InstanceState.STARTING: 5.0,      # Wait for process to be ready
    InstanceState.CONNECTING: 3.0,    # Wait for device_ready
    InstanceState.DISCONNECTING: 2.0, # Wait for device_unassigned
    InstanceState.STOPPING: 5.0,      # Wait for process exit
}


@dataclass
class InstanceInfo:
    """Tracks the complete state of a module instance."""
    instance_id: str
    module_id: str
    device_id: Optional[str] = None
    state: InstanceState = InstanceState.STOPPED
    state_entered_at: float = field(default_factory=time.time)
    error_message: Optional[str] = None

    def transition_to(self, new_state: InstanceState) -> bool:
        """Transition to a new state if valid.

        Args:
            new_state: The state to transition to

        Returns:
            True if transition was valid and performed, False otherwise
        """
        if new_state in VALID_TRANSITIONS.get(self.state, set()):
            self.state = new_state
            self.state_entered_at = time.time()
            self.error_message = None
            return True
        return False

    def force_transition_to(self, new_state: InstanceState) -> None:
        """Force transition to a new state (for error recovery).

        Use sparingly - this bypasses validation.
        """
        self.state = new_state
        self.state_entered_at = time.time()

    def time_in_state(self) -> float:
        """Get time spent in current state (seconds)."""
        return time.time() - self.state_entered_at

    def is_timed_out(self) -> bool:
        """Check if current state has exceeded its timeout."""
        timeout = STATE_TIMEOUTS.get(self.state)
        if timeout is None:
            return False
        return self.time_in_state() > timeout

    def is_transitional(self) -> bool:
        """Check if instance is in a transitional state (should show yellow)."""
        return self.state in {
            InstanceState.STARTING,
            InstanceState.CONNECTING,
            InstanceState.DISCONNECTING,
            InstanceState.STOPPING,
        }

    def is_connected(self) -> bool:
        """Check if instance has a connected device."""
        return self.state == InstanceState.CONNECTED

    def is_stopped(self) -> bool:
        """Check if instance is stopped."""
        return self.state == InstanceState.STOPPED
