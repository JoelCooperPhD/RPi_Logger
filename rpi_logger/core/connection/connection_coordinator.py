"""
Connection Coordinator - Unified connection lifecycle management.

This is the single source of truth for connection state. It coordinates:
- Command tracking with acknowledgments
- Retry policies for transient failures
- Heartbeat monitoring for health
- State machine transitions
- UI state derivation
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, TYPE_CHECKING

from rpi_logger.core.logging_utils import get_module_logger
from .command_tracker import CommandTracker
from .retry_policy import RetryPolicy
from .heartbeat_monitor import HeartbeatMonitor

if TYPE_CHECKING:
    from rpi_logger.core.module_manager import ModuleManager

logger = get_module_logger("ConnectionCoordinator")


class ConnectionState(Enum):
    """State of a module connection."""
    DISCONNECTED = "disconnected"
    STARTING = "starting"
    RUNNING = "running"       # Process running, no device
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTING = "disconnecting"
    STOPPING = "stopping"
    FAILED = "failed"


class ConnectionEvent(Enum):
    """Events that trigger state transitions."""
    START_REQUESTED = "start_requested"
    PROCESS_STARTED = "process_started"
    PROCESS_READY = "process_ready"
    CONNECT_REQUESTED = "connect_requested"
    DEVICE_READY = "device_ready"
    DEVICE_ERROR = "device_error"
    DISCONNECT_REQUESTED = "disconnect_requested"
    DEVICE_DISCONNECTED = "device_disconnected"
    STOP_REQUESTED = "stop_requested"
    PROCESS_STOPPED = "process_stopped"
    PROCESS_CRASHED = "process_crashed"
    HEARTBEAT_TIMEOUT = "heartbeat_timeout"
    RETRY_EXHAUSTED = "retry_exhausted"


# Valid state transitions: (current_state, event) -> new_state
STATE_TRANSITIONS: Dict[tuple[ConnectionState, ConnectionEvent], ConnectionState] = {
    # Starting flow
    (ConnectionState.DISCONNECTED, ConnectionEvent.START_REQUESTED): ConnectionState.STARTING,
    (ConnectionState.STARTING, ConnectionEvent.PROCESS_STARTED): ConnectionState.STARTING,
    (ConnectionState.STARTING, ConnectionEvent.PROCESS_READY): ConnectionState.RUNNING,
    (ConnectionState.STARTING, ConnectionEvent.PROCESS_CRASHED): ConnectionState.FAILED,

    # Connecting flow
    (ConnectionState.RUNNING, ConnectionEvent.CONNECT_REQUESTED): ConnectionState.CONNECTING,
    (ConnectionState.CONNECTING, ConnectionEvent.DEVICE_READY): ConnectionState.CONNECTED,
    (ConnectionState.CONNECTING, ConnectionEvent.DEVICE_ERROR): ConnectionState.RUNNING,
    (ConnectionState.CONNECTING, ConnectionEvent.RETRY_EXHAUSTED): ConnectionState.FAILED,

    # Disconnecting flow
    (ConnectionState.CONNECTED, ConnectionEvent.DISCONNECT_REQUESTED): ConnectionState.DISCONNECTING,
    (ConnectionState.DISCONNECTING, ConnectionEvent.DEVICE_DISCONNECTED): ConnectionState.RUNNING,

    # Stopping flow
    (ConnectionState.RUNNING, ConnectionEvent.STOP_REQUESTED): ConnectionState.STOPPING,
    (ConnectionState.CONNECTED, ConnectionEvent.STOP_REQUESTED): ConnectionState.STOPPING,
    (ConnectionState.CONNECTING, ConnectionEvent.STOP_REQUESTED): ConnectionState.STOPPING,
    (ConnectionState.STOPPING, ConnectionEvent.PROCESS_STOPPED): ConnectionState.DISCONNECTED,

    # Crash handling from any running state
    (ConnectionState.RUNNING, ConnectionEvent.PROCESS_CRASHED): ConnectionState.FAILED,
    (ConnectionState.CONNECTING, ConnectionEvent.PROCESS_CRASHED): ConnectionState.FAILED,
    (ConnectionState.CONNECTED, ConnectionEvent.PROCESS_CRASHED): ConnectionState.FAILED,
    (ConnectionState.DISCONNECTING, ConnectionEvent.PROCESS_CRASHED): ConnectionState.FAILED,
    (ConnectionState.STOPPING, ConnectionEvent.PROCESS_CRASHED): ConnectionState.DISCONNECTED,

    # Heartbeat timeout - treat as crash
    (ConnectionState.CONNECTED, ConnectionEvent.HEARTBEAT_TIMEOUT): ConnectionState.FAILED,

    # Recovery from failed
    (ConnectionState.FAILED, ConnectionEvent.START_REQUESTED): ConnectionState.STARTING,
    (ConnectionState.FAILED, ConnectionEvent.STOP_REQUESTED): ConnectionState.DISCONNECTED,
}


@dataclass
class ConnectionInfo:
    """Complete state of a connection."""
    instance_id: str
    module_id: str
    device_id: Optional[str] = None
    state: ConnectionState = ConnectionState.DISCONNECTED
    state_entered_at: float = field(default_factory=time.time)
    error_message: Optional[str] = None
    retry_count: int = 0
    last_heartbeat: float = 0.0

    def time_in_state(self) -> float:
        """Get time spent in current state (seconds)."""
        return time.time() - self.state_entered_at


# Callback types
StateChangeCallback = Callable[[str, ConnectionState, ConnectionState, Optional[str]], Awaitable[None]]
UIUpdateCallback = Callable[[str, bool, bool], Awaitable[None]]  # device_id, connected, connecting


class ConnectionCoordinator:
    """
    Centralized coordinator for module connections.

    This is the single source of truth for all connection state. It:
    1. Manages state machine transitions
    2. Tracks commands with correlation IDs
    3. Handles retries with exponential backoff
    4. Monitors heartbeats for health
    5. Provides UI state derivation

    All state changes go through this coordinator, ensuring consistency.

    Usage:
        coordinator = ConnectionCoordinator(module_manager)
        await coordinator.start()

        # Connect a device
        success = await coordinator.connect_device(
            instance_id="DRT:ACM0",
            module_id="DRT",
            device_id="ACM0",
            command_builder=lambda: build_assign_command(...),
        )

        if success:
            print("Connected!")
        else:
            print(f"Failed: {coordinator.get_error('DRT:ACM0')}")
    """

    def __init__(
        self,
        module_manager: ModuleManager,
        retry_policy: Optional[RetryPolicy] = None,
        command_timeout: float = 5.0,
        heartbeat_enabled: bool = True,
        heartbeat_interval: float = 2.0,
        heartbeat_timeout: float = 10.0,
    ):
        """
        Initialize connection coordinator.

        Args:
            module_manager: Manager for process control
            retry_policy: Policy for connection retries (default: 3 attempts)
            command_timeout: Timeout for individual commands (seconds)
            heartbeat_enabled: Whether to enable heartbeat monitoring
            heartbeat_interval: Expected heartbeat interval from modules
            heartbeat_timeout: Time without heartbeat before unhealthy
        """
        self._module_manager = module_manager
        self._retry_policy = retry_policy or RetryPolicy(
            max_attempts=3,
            base_delay=1.0,
            max_delay=10.0,
        )
        self._command_timeout = command_timeout

        # State tracking
        self._connections: Dict[str, ConnectionInfo] = {}
        self._lock = asyncio.Lock()

        # Command tracking
        self._command_tracker = CommandTracker()

        # Heartbeat monitoring
        self._heartbeat_enabled = heartbeat_enabled
        self._heartbeat_monitor: Optional[HeartbeatMonitor] = None
        if heartbeat_enabled:
            self._heartbeat_monitor = HeartbeatMonitor(
                interval=heartbeat_interval,
                timeout=heartbeat_timeout,
            )

        # Callbacks
        self._state_observers: List[StateChangeCallback] = []
        self._ui_callback: Optional[UIUpdateCallback] = None

        self._running = False

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def start(self) -> None:
        """Start the coordinator and its components."""
        self._running = True
        await self._command_tracker.start()

        if self._heartbeat_monitor:
            self._heartbeat_monitor.set_unhealthy_callback(self._on_heartbeat_unhealthy)
            self._heartbeat_monitor.set_recovered_callback(self._on_heartbeat_recovered)
            await self._heartbeat_monitor.start()

        logger.info("Connection coordinator started")

    async def stop(self) -> None:
        """Stop the coordinator and clean up."""
        self._running = False

        if self._heartbeat_monitor:
            await self._heartbeat_monitor.stop()

        await self._command_tracker.stop()

        logger.info("Connection coordinator stopped")

    # =========================================================================
    # Connection Operations
    # =========================================================================

    async def start_instance(
        self,
        instance_id: str,
        module_id: str,
        device_id: str,
        start_func: Callable[[], Awaitable[bool]],
    ) -> bool:
        """
        Start a module instance.

        Args:
            instance_id: Unique instance ID (e.g., "DRT:ACM0")
            module_id: Base module ID (e.g., "DRT")
            device_id: Device ID this instance will handle
            start_func: Async function to start the process

        Returns:
            True if instance started successfully
        """
        async with self._lock:
            # Create or reset connection info
            info = ConnectionInfo(
                instance_id=instance_id,
                module_id=module_id,
                device_id=device_id,
            )
            self._connections[instance_id] = info

        # Transition to STARTING
        await self._transition(instance_id, ConnectionEvent.START_REQUESTED)

        # Start the process
        try:
            success = await start_func()
            if success:
                await self._transition(instance_id, ConnectionEvent.PROCESS_STARTED)

                # Register for heartbeat monitoring
                if self._heartbeat_monitor:
                    self._heartbeat_monitor.register(instance_id)

                # Wait for ready status or timeout
                # Currently assumes ready after start - future enhancement could
                # wait for explicit "ready" status message from the module
                await self._transition(instance_id, ConnectionEvent.PROCESS_READY)
                return True
            else:
                await self._set_error(instance_id, "Failed to start process")
                await self._transition(instance_id, ConnectionEvent.PROCESS_CRASHED)
                return False
        except Exception as e:
            await self._set_error(instance_id, str(e))
            await self._transition(instance_id, ConnectionEvent.PROCESS_CRASHED)
            return False

    async def connect_device(
        self,
        instance_id: str,
        command_builder: Callable[[str], str],
        send_func: Callable[[str], Awaitable[None]],
    ) -> bool:
        """
        Connect a device to an instance with retries.

        Args:
            instance_id: The instance to connect
            command_builder: Function that takes command_id and returns command JSON
            send_func: Async function to send the command

        Returns:
            True if device connected successfully
        """
        info = self._connections.get(instance_id)
        if not info:
            logger.error("Instance %s not found", instance_id)
            return False

        if info.state not in {ConnectionState.RUNNING, ConnectionState.FAILED}:
            logger.warning(
                "Instance %s in state %s, expected RUNNING",
                instance_id, info.state.value
            )
            if info.state != ConnectionState.CONNECTING:
                return False

        # Transition to CONNECTING
        await self._transition(instance_id, ConnectionEvent.CONNECT_REQUESTED)

        async def attempt_connect() -> bool:
            """Single connection attempt."""
            command_id = self._command_tracker.generate_command_id()
            command_json = command_builder(command_id)

            result = await self._command_tracker.send_and_wait(
                send_func=send_func,
                command_type="assign_device",
                command_json=command_json,
                command_id=command_id,
                device_id=info.device_id,
                timeout=self._command_timeout,
            )

            return result.success

        # Execute with retries
        retry_result = await self._retry_policy.execute(
            operation=attempt_connect,
            on_retry=lambda attempt, error: logger.info(
                "Retry %d for %s: %s", attempt, instance_id, error
            ),
        )

        if retry_result.success:
            await self._transition(instance_id, ConnectionEvent.DEVICE_READY)
            logger.info(
                "Device connected for %s after %d attempts (%.1fms)",
                instance_id, retry_result.attempt_count, retry_result.total_duration_ms
            )
            return True
        else:
            await self._set_error(instance_id, retry_result.final_error or "Connection failed")
            await self._transition(instance_id, ConnectionEvent.RETRY_EXHAUSTED)
            logger.error(
                "Device connection failed for %s after %d attempts: %s",
                instance_id, retry_result.attempt_count, retry_result.final_error
            )
            return False

    async def disconnect_device(
        self,
        instance_id: str,
        command_json: str,
        send_func: Callable[[str], Awaitable[None]],
        timeout: float = 3.0,
    ) -> bool:
        """
        Disconnect a device from an instance.

        Args:
            instance_id: The instance to disconnect
            command_json: The unassign command JSON
            send_func: Async function to send the command
            timeout: Timeout for sending the command

        Returns:
            True if disconnected successfully
        """
        info = self._connections.get(instance_id)
        if not info:
            return True  # Already disconnected

        if info.state != ConnectionState.CONNECTED:
            logger.warning("Instance %s not connected", instance_id)
            return True

        await self._transition(instance_id, ConnectionEvent.DISCONNECT_REQUESTED)

        try:
            await asyncio.wait_for(send_func(command_json), timeout=timeout)
            await self._transition(instance_id, ConnectionEvent.DEVICE_DISCONNECTED)
            return True
        except asyncio.TimeoutError:
            logger.warning("Disconnect command timed out for %s", instance_id)
            await self._transition(instance_id, ConnectionEvent.DEVICE_DISCONNECTED)
            return True
        except Exception as e:
            logger.error("Disconnect error for %s: %s", instance_id, e)
            await self._transition(instance_id, ConnectionEvent.DEVICE_DISCONNECTED)
            return True

    async def stop_instance(
        self,
        instance_id: str,
        stop_func: Callable[[], Awaitable[bool]],
    ) -> bool:
        """
        Stop a module instance.

        Args:
            instance_id: The instance to stop
            stop_func: Async function to stop the process

        Returns:
            True if stopped successfully
        """
        info = self._connections.get(instance_id)
        if not info:
            return True  # Already stopped

        if info.state == ConnectionState.DISCONNECTED:
            return True

        # Unregister from heartbeat monitoring
        if self._heartbeat_monitor:
            self._heartbeat_monitor.unregister(instance_id)

        await self._transition(instance_id, ConnectionEvent.STOP_REQUESTED)

        try:
            await stop_func()
            await self._transition(instance_id, ConnectionEvent.PROCESS_STOPPED)
            return True
        except Exception as e:
            logger.error("Stop error for %s: %s", instance_id, e)
            await self._transition(instance_id, ConnectionEvent.PROCESS_STOPPED)
            return True

    # =========================================================================
    # Status Message Handling
    # =========================================================================

    def on_device_ready(self, instance_id: str, device_id: str, data: Optional[Dict] = None) -> None:
        """
        Handle device_ready status from module.

        This is called when a module sends device_ready, either as a response
        to assign_device or spontaneously.
        """
        # Try to resolve pending command first
        resolved = self._command_tracker.on_device_ready(device_id, data)

        if not resolved:
            # No pending command - this might be a spontaneous device_ready
            # (e.g., device reconnected on its own)
            info = self._connections.get(instance_id)
            if info and info.state == ConnectionState.CONNECTING:
                asyncio.create_task(
                    self._transition(instance_id, ConnectionEvent.DEVICE_READY)
                )

    def on_device_error(
        self,
        instance_id: str,
        device_id: str,
        error: str,
        data: Optional[Dict] = None,
    ) -> None:
        """Handle device_error status from module."""
        # Try to resolve pending command
        self._command_tracker.on_device_error(device_id, error, data)

    def on_heartbeat(self, instance_id: str, data: Optional[Dict] = None) -> None:
        """Handle heartbeat status from module."""
        if self._heartbeat_monitor:
            self._heartbeat_monitor.on_heartbeat(instance_id, data)

        # Update last heartbeat time in connection info
        info = self._connections.get(instance_id)
        if info:
            info.last_heartbeat = time.time()

    def on_process_exit(self, instance_id: str, crashed: bool = False) -> None:
        """Handle process termination."""
        if self._heartbeat_monitor:
            self._heartbeat_monitor.unregister(instance_id)

        event = ConnectionEvent.PROCESS_CRASHED if crashed else ConnectionEvent.PROCESS_STOPPED
        asyncio.create_task(self._transition(instance_id, event))

    # =========================================================================
    # State Queries
    # =========================================================================

    def get_state(self, instance_id: str) -> ConnectionState:
        """Get current state of an instance."""
        info = self._connections.get(instance_id)
        return info.state if info else ConnectionState.DISCONNECTED

    def get_info(self, instance_id: str) -> Optional[ConnectionInfo]:
        """Get full connection info for an instance."""
        return self._connections.get(instance_id)

    def get_error(self, instance_id: str) -> Optional[str]:
        """Get error message for an instance."""
        info = self._connections.get(instance_id)
        return info.error_message if info else None

    def is_connected(self, instance_id: str) -> bool:
        """Check if an instance is connected."""
        return self.get_state(instance_id) == ConnectionState.CONNECTED

    def is_transitional(self, instance_id: str) -> bool:
        """Check if an instance is in a transitional state (show amber)."""
        state = self.get_state(instance_id)
        return state in {
            ConnectionState.STARTING,
            ConnectionState.CONNECTING,
            ConnectionState.DISCONNECTING,
            ConnectionState.STOPPING,
        }

    def get_ui_state(self, device_id: str) -> tuple[bool, bool]:
        """
        Get UI state for a device.

        Returns:
            Tuple of (connected, connecting) for the device
        """
        # Find connection by device_id
        for info in self._connections.values():
            if info.device_id == device_id:
                connected = info.state == ConnectionState.CONNECTED
                connecting = info.state in {
                    ConnectionState.STARTING,
                    ConnectionState.CONNECTING,
                    ConnectionState.DISCONNECTING,
                    ConnectionState.STOPPING,
                }
                return (connected, connecting)

        return (False, False)

    # =========================================================================
    # Observers
    # =========================================================================

    def add_state_observer(self, callback: StateChangeCallback) -> None:
        """Add an observer for state changes."""
        if callback not in self._state_observers:
            self._state_observers.append(callback)

    def remove_state_observer(self, callback: StateChangeCallback) -> None:
        """Remove a state observer."""
        if callback in self._state_observers:
            self._state_observers.remove(callback)

    def set_ui_callback(self, callback: UIUpdateCallback) -> None:
        """Set callback for UI updates."""
        self._ui_callback = callback

    # =========================================================================
    # Internal Methods
    # =========================================================================

    async def _transition(
        self,
        instance_id: str,
        event: ConnectionEvent,
    ) -> bool:
        """
        Attempt a state transition.

        Args:
            instance_id: The instance to transition
            event: The event triggering the transition

        Returns:
            True if transition was valid and performed
        """
        async with self._lock:
            info = self._connections.get(instance_id)
            if not info:
                logger.warning("Transition for unknown instance: %s", instance_id)
                return False

            old_state = info.state
            key = (old_state, event)

            new_state = STATE_TRANSITIONS.get(key)
            if new_state is None:
                logger.warning(
                    "Invalid transition for %s: %s + %s",
                    instance_id, old_state.value, event.value
                )
                return False

            # Perform transition
            info.state = new_state
            info.state_entered_at = time.time()

            # Clear error on successful transitions
            if new_state in {ConnectionState.RUNNING, ConnectionState.CONNECTED}:
                info.error_message = None
                info.retry_count = 0

            logger.info(
                "Instance %s: %s -> %s (event: %s)",
                instance_id, old_state.value, new_state.value, event.value
            )

        # Notify observers (outside lock)
        await self._notify_state_change(instance_id, old_state, new_state)
        await self._update_ui(instance_id)

        return True

    async def _set_error(self, instance_id: str, error: str) -> None:
        """Set error message for an instance."""
        async with self._lock:
            info = self._connections.get(instance_id)
            if info:
                info.error_message = error

    async def _notify_state_change(
        self,
        instance_id: str,
        old_state: ConnectionState,
        new_state: ConnectionState,
    ) -> None:
        """Notify observers of state change."""
        info = self._connections.get(instance_id)
        error = info.error_message if info else None

        for observer in self._state_observers:
            try:
                await observer(instance_id, old_state, new_state, error)
            except Exception as e:
                logger.error("State observer error: %s", e)

    async def _update_ui(self, instance_id: str) -> None:
        """Update UI for an instance."""
        if not self._ui_callback:
            return

        info = self._connections.get(instance_id)
        if not info or not info.device_id:
            return

        connected, connecting = self.get_ui_state(info.device_id)

        try:
            await self._ui_callback(info.device_id, connected, connecting)
        except Exception as e:
            logger.error("UI callback error: %s", e)

    async def _on_heartbeat_unhealthy(self, instance_id: str, heartbeat_info: Any) -> None:
        """Handle instance becoming unhealthy due to missed heartbeats."""
        logger.warning("Instance %s unhealthy (heartbeat timeout)", instance_id)
        await self._set_error(instance_id, "Heartbeat timeout - module unresponsive")
        await self._transition(instance_id, ConnectionEvent.HEARTBEAT_TIMEOUT)

    async def _on_heartbeat_recovered(self, instance_id: str, heartbeat_info: Any) -> None:
        """Handle instance recovering after heartbeat issues."""
        logger.info("Instance %s recovered (heartbeat received)", instance_id)
        # Clear the error - state machine will handle the rest
        info = self._connections.get(instance_id)
        if info:
            info.error_message = None
