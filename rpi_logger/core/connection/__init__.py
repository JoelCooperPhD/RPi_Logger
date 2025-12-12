"""
Robust connection management for module communication.

This package provides reliable connection handling with:
- Command tracking with correlation IDs and acknowledgments
- Retry policies with exponential backoff
- Heartbeat monitoring for connection health
- Unified connection coordination
- ACK-based shutdown protocol
"""

from .command_tracker import CommandTracker, CommandResult, PendingCommand, CommandStatus
from .retry_policy import RetryPolicy, RetryResult
from .heartbeat_monitor import HeartbeatMonitor
from .connection_coordinator import ConnectionCoordinator, ConnectionState, ConnectionEvent
from .shutdown_coordinator import ShutdownCoordinator, ShutdownResult, ShutdownPhase
from .reconnect_handler import ReconnectingMixin, ReconnectConfig, ReconnectState

__all__ = [
    # Command tracking
    'CommandTracker',
    'CommandResult',
    'PendingCommand',
    'CommandStatus',
    # Retry
    'RetryPolicy',
    'RetryResult',
    # Heartbeat
    'HeartbeatMonitor',
    # Coordinator
    'ConnectionCoordinator',
    'ConnectionState',
    'ConnectionEvent',
    # Shutdown
    'ShutdownCoordinator',
    'ShutdownResult',
    'ShutdownPhase',
    # Reconnection
    'ReconnectingMixin',
    'ReconnectConfig',
    'ReconnectState',
]
