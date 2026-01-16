"""
Instance State Manager - Centralized lifecycle management for module instances.

This manager is the single source of truth for module instance state.
It uses an event-driven approach for reliable connections:
- Commands are sent and state transitions to CONNECTING
- Module responses (device_ready/device_error) trigger state changes
- Timeout monitor handles unresponsive modules
- No blocking waits - everything is async event-driven
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, TYPE_CHECKING

from rpi_logger.core.asyncio_utils import create_logged_task
from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.core.instance_state import InstanceState, InstanceInfo, STATE_TIMEOUTS

if TYPE_CHECKING:
    from rpi_logger.core.module_manager import ModuleManager

logger = get_module_logger("InstanceStateManager")

# Type aliases
StateChangeCallback = Callable[[str, InstanceState, InstanceState], None]
UIUpdateCallback = Callable[[str, bool, bool], Awaitable[None]]  # device_id, connected, connecting


@dataclass
class PendingConnection:
    """Tracks a pending device connection attempt."""
    instance_id: str
    device_id: str
    command_builder: Callable[[str], str]
    attempts: int = 0
    max_attempts: int = 3
    last_attempt_at: float = 0.0
    retry_delay: float = 1.0  # seconds between retries
    timeout_per_attempt: float = 3.0  # seconds to wait for ack


class InstanceStateManager:
    """Manages lifecycle state for all module instances.

    This is the single source of truth for instance state. All state
    changes go through this manager, which then notifies observers.

    Uses event-driven pattern:
    - send_assign_device() sends command and returns immediately
    - on_status_message() handles responses and transitions state
    - timeout monitor retries or fails connections
    """

    def __init__(
        self,
        module_manager: ModuleManager,
        ui_update_callback: Optional[UIUpdateCallback] = None,
        connect_timeout: float = 3.0,
        connect_max_attempts: int = 3,
        connect_retry_delay: float = 1.0,
    ):
        """Initialize the instance state manager.

        Args:
            module_manager: The module manager for process control
            ui_update_callback: Callback to update UI state
            connect_timeout: Timeout per connection attempt (seconds)
            connect_max_attempts: Max connection attempts before failure
            connect_retry_delay: Delay between retry attempts (seconds)
        """
        self._module_manager = module_manager
        self._ui_update_callback = ui_update_callback
        self._instances: Dict[str, InstanceInfo] = {}
        self._state_observers: List[StateChangeCallback] = []
        self._monitor_task: Optional[asyncio.Task] = None
        self._running = False

        # Connection settings
        self._connect_timeout = connect_timeout
        self._connect_max_attempts = connect_max_attempts
        self._connect_retry_delay = connect_retry_delay

        # Pending connections awaiting acknowledgment
        self._pending_connections: Dict[str, PendingConnection] = {}

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def start(self) -> None:
        """Start the instance manager."""
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("Instance state manager started")

    async def stop(self) -> None:
        """Stop the instance manager."""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        self._pending_connections.clear()
        logger.info("Instance state manager stopped")

    # =========================================================================
    # Instance Lifecycle Operations
    # =========================================================================

    async def start_instance(
        self,
        instance_id: str,
        module_id: str,
        device_id: str,
        window_geometry: Optional[Any] = None,
        camera_index: Optional[int] = None,
    ) -> bool:
        """Start a module instance.

        Args:
            instance_id: Unique instance ID (e.g., "DRT:ACM0")
            module_id: Base module ID (e.g., "DRT")
            device_id: Device ID this instance will handle
            window_geometry: Optional window geometry
            camera_index: Optional camera index for CSI cameras (enables direct init)

        Returns:
            True if instance started successfully (process launched)
        """
        logger.info("Starting instance %s for device %s", instance_id, device_id)

        # Check if instance already exists
        existing = self._instances.get(instance_id)
        if existing:
            if existing.state == InstanceState.STOPPING:
                # Wait for it to finish stopping
                logger.info("Instance %s is stopping, waiting...", instance_id)
                if not await self._wait_for_state(instance_id, InstanceState.STOPPED, timeout=5.0):
                    logger.error("Instance %s failed to stop in time", instance_id)
                    return False
            elif existing.state != InstanceState.STOPPED:
                # Already starting/running/connected - reject duplicate
                logger.info(
                    "Instance %s already exists in state %s, ignoring duplicate start",
                    instance_id, existing.state.value
                )
                return False

        # Create or reset instance info
        info = InstanceInfo(
            instance_id=instance_id,
            module_id=module_id,
            device_id=device_id,
            state=InstanceState.STOPPED,
        )
        self._instances[instance_id] = info

        # Transition to STARTING
        self._set_state(instance_id, InstanceState.STARTING)

        # Start the process
        success = await self._module_manager.start_module_instance(
            module_id, instance_id, window_geometry, camera_index=camera_index
        )

        if not success:
            logger.error("Failed to start process for instance %s", instance_id)
            self._set_state(instance_id, InstanceState.STOPPED, error="Failed to start process")
            return False

        logger.info("Instance %s process launched, waiting for 'ready' status", instance_id)
        return True

    async def wait_for_ready(self, instance_id: str, timeout: float = 10.0) -> bool:
        """Wait for an instance to become ready for commands.

        After start_instance() returns, the instance is in STARTING state.
        This method waits for the module to send its "ready" status,
        which transitions the instance to RUNNING (or CONNECTED for internal modules).

        Args:
            instance_id: The instance to wait for
            timeout: Maximum time to wait in seconds

        Returns:
            True if instance reached RUNNING/CONNECTED state, False on timeout
        """
        info = self._instances.get(instance_id)
        if not info:
            logger.error("Instance %s not found for wait_for_ready", instance_id)
            return False

        # Internal modules go directly to CONNECTED
        if self._module_manager.is_internal_module(info.module_id):
            target_states = {InstanceState.CONNECTED}
        else:
            target_states = {InstanceState.RUNNING, InstanceState.CONNECTED}

        elapsed = 0.0
        interval = 0.1

        while elapsed < timeout:
            info = self._instances.get(instance_id)
            if not info:
                return False
            if info.state in target_states:
                logger.info("Instance %s ready after %.1fs", instance_id, elapsed)
                return True
            if info.state == InstanceState.STOPPED:
                logger.error("Instance %s stopped while waiting for ready", instance_id)
                return False
            await asyncio.sleep(interval)
            elapsed += interval

        logger.error("Timeout waiting for instance %s to become ready (state: %s)", instance_id, info.state.value)
        return False

    async def connect_device(
        self,
        instance_id: str,
        command_builder: Callable[[str], str],
    ) -> bool:
        """Initiate device connection (non-blocking).

        This sends the assign_device command and returns immediately.
        The actual connection result comes via on_status_message().

        Args:
            instance_id: The instance to send the command to
            command_builder: Function that takes command_id and returns command JSON

        Returns:
            True if command was sent successfully
        """
        info = self._instances.get(instance_id)
        if not info:
            logger.error("Instance %s not found", instance_id)
            return False

        if info.state not in {InstanceState.RUNNING, InstanceState.CONNECTING}:
            logger.info(
                "Instance %s in state %s, expected RUNNING",
                instance_id, info.state.value
            )
            return False

        # Create pending connection tracker
        pending = PendingConnection(
            instance_id=instance_id,
            device_id=info.device_id,
            command_builder=command_builder,
            max_attempts=self._connect_max_attempts,
            retry_delay=self._connect_retry_delay,
            timeout_per_attempt=self._connect_timeout,
        )
        self._pending_connections[instance_id] = pending

        # Transition to CONNECTING and send first attempt
        self._set_state(instance_id, InstanceState.CONNECTING)
        await self._send_connection_attempt(pending)

        return True

    async def _send_connection_attempt(self, pending: PendingConnection) -> None:
        """Send a connection attempt."""
        pending.attempts += 1
        pending.last_attempt_at = time.time()

        # Generate command with unique ID for this attempt
        command_id = f"{pending.instance_id}:{pending.attempts}"
        command_json = pending.command_builder(command_id)

        logger.info(
            "Connection attempt %d/%d for %s",
            pending.attempts, pending.max_attempts, pending.instance_id
        )

        success = await self._module_manager.send_command_raw(
            pending.instance_id, command_json
        )

        if not success:
            logger.error("Failed to send assign_device to %s", pending.instance_id)
            # Will be retried by monitor loop

    async def stop_instance(self, instance_id: str) -> bool:
        """Stop a module instance.

        Args:
            instance_id: The instance to stop

        Returns:
            True if instance stopped successfully
        """
        info = self._instances.get(instance_id)
        if not info:
            logger.debug("Instance %s not found for stop", instance_id)
            return True

        if info.state == InstanceState.STOPPED:
            return True

        if info.state == InstanceState.STOPPING:
            return await self._wait_for_state(instance_id, InstanceState.STOPPED, timeout=5.0)

        logger.info("Stopping instance %s (current state: %s)", instance_id, info.state.value)

        # Remove from pending connections
        self._pending_connections.pop(instance_id, None)

        # Transition to STOPPING
        self._set_state(instance_id, InstanceState.STOPPING)

        # Send quit command
        success = await self._module_manager.stop_module_instance(instance_id)
        if not success:
            logger.warning("Failed to send quit to %s, forcing stop", instance_id)
            self._set_state(instance_id, InstanceState.STOPPED)
            return True

        # Wait for STOPPED state
        stopped = await self._wait_for_state(instance_id, InstanceState.STOPPED, timeout=5.0)
        if not stopped:
            logger.warning("Instance %s didn't stop gracefully, forcing", instance_id)
            await self._module_manager.kill_module_instance(instance_id)
            self._set_state(instance_id, InstanceState.STOPPED)

        return True

    # =========================================================================
    # Status Message Handling
    # =========================================================================

    def on_status_message(self, instance_id: str, status_type: str, data: Dict[str, Any]) -> None:
        """Handle a status message from a module.

        This is the event-driven handler that processes module responses.

        Args:
            instance_id: The instance that sent the message
            status_type: The status type (e.g., "device_ready", "quitting")
            data: Additional data from the status message
        """
        info = self._instances.get(instance_id)
        if not info:
            logger.debug(
                "Status from unknown instance %s: %s (known instances: %s)",
                instance_id, status_type, list(self._instances.keys())
            )
            return

        logger.debug(
            "Instance %s status: %s (state: %s, pending: %s)",
            instance_id, status_type, info.state.value,
            instance_id in self._pending_connections
        )

        if status_type == "ready":
            # Module is ready for commands
            if info.state == InstanceState.STARTING:
                # Check if this is an internal (software-only) module
                # Internal modules go directly to CONNECTED since they have no hardware
                if self._module_manager.is_internal_module(info.module_id):
                    logger.info("Internal module %s ready, transitioning to CONNECTED", instance_id)
                    self._set_state(instance_id, InstanceState.CONNECTED)
                else:
                    self._set_state(instance_id, InstanceState.RUNNING)

        elif status_type == "device_ack":
            # Phase 1: Module acknowledged the assignment, now initializing
            device_id = data.get("device_id")
            logger.info(
                "device_ack received: device=%s, instance=%s, current_state=%s",
                device_id, instance_id, info.state.value
            )

            # Remove from pending connections - no more timeout/retry needed
            pending = self._pending_connections.pop(instance_id, None)
            if pending:
                logger.info(
                    "ACK received for %s after %d attempt(s), waiting for device_ready",
                    instance_id, pending.attempts
                )

            # Transition to INITIALIZING (waits indefinitely for device_ready)
            if info.state == InstanceState.CONNECTING:
                logger.info("Transitioning %s to INITIALIZING", instance_id)
                self._set_state(instance_id, InstanceState.INITIALIZING)

        elif status_type == "device_ready":
            # Device successfully connected - this is the ACK we're waiting for
            device_id = data.get("device_id")
            logger.info(
                "device_ready received: device=%s, instance=%s, current_state=%s",
                device_id, instance_id, info.state.value
            )

            # Remove from pending - connection succeeded
            pending = self._pending_connections.pop(instance_id, None)
            if pending:
                logger.info(
                    "Connection succeeded for %s after %d attempt(s)",
                    instance_id, pending.attempts
                )
            else:
                logger.info("No pending connection found for %s (may have already completed)", instance_id)

            # Transition to CONNECTED from CONNECTING, INITIALIZING, or RUNNING
            if info.state in {InstanceState.CONNECTING, InstanceState.INITIALIZING, InstanceState.RUNNING}:
                logger.info("Transitioning %s to CONNECTED", instance_id)
                self._set_state(instance_id, InstanceState.CONNECTED)
            else:
                logger.warning(
                    "Cannot transition to CONNECTED: instance %s is in state %s",
                    instance_id, info.state.value
                )

        elif status_type == "device_error":
            # Device connection failed
            device_id = data.get("device_id")
            error = data.get("error", "Unknown error")
            logger.error("Device %s error on instance %s: %s", device_id, instance_id, error)

            # Check if we should retry
            pending = self._pending_connections.get(instance_id)
            if pending and pending.attempts < pending.max_attempts:
                # Will retry on next monitor loop tick
                logger.info(
                    "Will retry connection for %s (attempt %d/%d)",
                    instance_id, pending.attempts + 1, pending.max_attempts
                )
            else:
                # No more retries - fail the connection
                self._pending_connections.pop(instance_id, None)
                if info.state in {InstanceState.CONNECTING, InstanceState.INITIALIZING}:
                    self._set_state(instance_id, InstanceState.RUNNING, error=error)

        elif status_type == "device_unassigned":
            if info.state == InstanceState.DISCONNECTING:
                self._set_state(instance_id, InstanceState.RUNNING)

        elif status_type == "quitting":
            if info.state != InstanceState.STOPPED:
                self._pending_connections.pop(instance_id, None)
                self._set_state(instance_id, InstanceState.STOPPING)

    def on_process_exit(self, instance_id: str) -> None:
        """Handle process termination."""
        info = self._instances.get(instance_id)
        if not info:
            return

        self._pending_connections.pop(instance_id, None)

        previous_state = info.state
        self._set_state(instance_id, InstanceState.STOPPED)

        if previous_state not in {InstanceState.STOPPING, InstanceState.STOPPED}:
            logger.warning(
                "Instance %s exited unexpectedly from state %s",
                instance_id, previous_state.value
            )

    # =========================================================================
    # Monitor Loop - Handles timeouts and retries
    # =========================================================================

    async def _monitor_loop(self) -> None:
        """Background task to monitor connections and handle retries."""
        while self._running:
            try:
                await asyncio.sleep(0.5)  # Check every 500ms
                await self._check_pending_connections()
                await self._check_state_timeouts()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Monitor loop error: %s", e)

    async def _check_pending_connections(self) -> None:
        """Check pending connections for timeouts and retries."""
        now = time.time()

        for instance_id, pending in list(self._pending_connections.items()):
            elapsed = now - pending.last_attempt_at

            if elapsed < pending.timeout_per_attempt:
                # Still waiting for response
                continue

            # Timeout - check if we should retry
            if pending.attempts < pending.max_attempts:
                # Retry after delay
                if elapsed >= pending.timeout_per_attempt + pending.retry_delay:
                    logger.info(
                        "Retrying connection for %s (attempt %d/%d)",
                        instance_id, pending.attempts + 1, pending.max_attempts
                    )
                    await self._send_connection_attempt(pending)
            else:
                # All attempts exhausted - fail
                logger.error(
                    "Connection failed for %s after %d attempts",
                    instance_id, pending.attempts
                )
                self._pending_connections.pop(instance_id, None)

                info = self._instances.get(instance_id)
                if info and info.state == InstanceState.CONNECTING:
                    self._set_state(
                        instance_id,
                        InstanceState.RUNNING,
                        error=f"Connection timed out after {pending.attempts} attempts"
                    )

    async def _check_state_timeouts(self) -> None:
        """Check for instances stuck in transitional states."""
        for instance_id, info in list(self._instances.items()):
            # Skip if there's a pending connection (handled separately)
            if instance_id in self._pending_connections:
                continue

            if not info.is_timed_out():
                continue

            state = info.state
            logger.warning(
                "Instance %s timed out in state %s after %.1fs",
                instance_id, state.value, info.time_in_state()
            )

            if state == InstanceState.STARTING:
                logger.error("Instance %s failed to start, killing", instance_id)
                await self._module_manager.kill_module_instance(instance_id)
                self._set_state(instance_id, InstanceState.STOPPED, error="Startup timeout")

            elif state == InstanceState.DISCONNECTING:
                logger.warning("Instance %s disconnect timeout, assuming done", instance_id)
                self._set_state(instance_id, InstanceState.RUNNING)

            elif state == InstanceState.STOPPING:
                logger.warning("Instance %s stop timeout, force killing", instance_id)
                await self._module_manager.kill_module_instance(instance_id)
                self._set_state(instance_id, InstanceState.STOPPED)

    # =========================================================================
    # State Queries
    # =========================================================================

    def get_instance(self, instance_id: str) -> Optional[InstanceInfo]:
        """Get instance info by ID."""
        return self._instances.get(instance_id)

    def get_state(self, instance_id: str) -> InstanceState:
        """Get the current state of an instance."""
        info = self._instances.get(instance_id)
        return info.state if info else InstanceState.STOPPED

    def is_instance_running(self, instance_id: str) -> bool:
        """Check if an instance is running (not stopped or stopping)."""
        info = self._instances.get(instance_id)
        if not info:
            return False
        return info.state not in {InstanceState.STOPPED, InstanceState.STOPPING}

    def is_instance_connected(self, instance_id: str) -> bool:
        """Check if an instance has a connected device."""
        info = self._instances.get(instance_id)
        return info.is_connected() if info else False

    def is_instance_transitional(self, instance_id: str) -> bool:
        """Check if an instance is in a transitional state."""
        info = self._instances.get(instance_id)
        return info.is_transitional() if info else False

    def get_device_id(self, instance_id: str) -> Optional[str]:
        """Get the device ID for an instance."""
        info = self._instances.get(instance_id)
        return info.device_id if info else None

    def get_instance_for_device(self, device_id: str) -> Optional[str]:
        """Get the instance ID for a device."""
        for instance_id, info in self._instances.items():
            if info.device_id == device_id:
                return instance_id
        return None

    def get_error(self, instance_id: str) -> Optional[str]:
        """Get error message for an instance."""
        info = self._instances.get(instance_id)
        return info.error_message if info else None

    def get_instances_for_module(self, module_id: str) -> List[str]:
        """Get all instance IDs for a given module."""
        return [
            instance_id for instance_id, info in self._instances.items()
            if info.module_id == module_id
        ]

    def has_running_instances(self, module_id: str) -> bool:
        """Check if any instances of a module are running."""
        for info in self._instances.values():
            if info.module_id == module_id and info.state not in {
                InstanceState.STOPPED, InstanceState.STOPPING
            }:
                return True
        return False

    async def stop_all_instances_for_module(self, module_id: str) -> bool:
        """Stop all instances of a module.

        Args:
            module_id: Base module ID (e.g., "Cameras", "DRT")

        Returns:
            True if all instances were stopped successfully
        """
        instance_ids = self.get_instances_for_module(module_id)
        if not instance_ids:
            logger.debug("No instances found for module %s", module_id)
            return True

        logger.info("Stopping %d instances of module %s", len(instance_ids), module_id)
        results = await asyncio.gather(
            *(self.stop_instance(iid) for iid in instance_ids),
            return_exceptions=True
        )

        all_success = all(r is True for r in results if not isinstance(r, Exception))
        if not all_success:
            logger.warning("Some instances of %s failed to stop", module_id)

        return all_success

    # =========================================================================
    # UI State
    # =========================================================================

    def get_ui_state(self, device_id: str) -> tuple[bool, bool]:
        """Get the UI state for a device.

        Returns:
            Tuple of (connected, connecting) for the device
        """
        instance_id = self.get_instance_for_device(device_id)
        if not instance_id:
            return (False, False)

        info = self._instances.get(instance_id)
        if not info:
            return (False, False)

        connected = info.state == InstanceState.CONNECTED
        connecting = info.is_transitional()

        return (connected, connecting)

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

    # =========================================================================
    # Internal Methods
    # =========================================================================

    def _set_state(
        self,
        instance_id: str,
        new_state: InstanceState,
        error: Optional[str] = None,
    ) -> None:
        """Set the state of an instance and notify observers."""
        info = self._instances.get(instance_id)
        if not info:
            return

        old_state = info.state
        if old_state == new_state:
            return

        # Validate transition (but allow it with warning)
        if not info.transition_to(new_state):
            logger.warning(
                "Invalid transition for %s: %s -> %s (forcing)",
                instance_id, old_state.value, new_state.value
            )
            info.force_transition_to(new_state)

        if error:
            info.error_message = error
        elif new_state == InstanceState.CONNECTED:
            # Clear error on successful connection
            info.error_message = None

        logger.info(
            "Instance %s: %s -> %s%s",
            instance_id, old_state.value, new_state.value,
            f" (error: {error})" if error else ""
        )

        # Notify state observers
        for observer in self._state_observers:
            try:
                observer(instance_id, old_state, new_state)
            except Exception as e:
                logger.error("State observer error: %s", e)

        # Update UI
        self._update_ui(instance_id)

    def _update_ui(self, instance_id: str) -> None:
        """Update UI state for an instance's device."""
        if not self._ui_update_callback:
            return

        info = self._instances.get(instance_id)
        if not info or not info.device_id:
            return

        connected, connecting = self.get_ui_state(info.device_id)

        try:
            loop = asyncio.get_running_loop()
            create_logged_task(
                self._ui_update_callback(info.device_id, connected, connecting),
                loop=loop,
                logger=logger,
                context=f"InstanceManager.ui_update({info.device_id})",
            )
        except RuntimeError:
            pass

    async def _wait_for_state(
        self,
        instance_id: str,
        target_state: InstanceState,
        timeout: float,
    ) -> bool:
        """Wait for an instance to reach a target state."""
        elapsed = 0.0
        interval = 0.1

        while elapsed < timeout:
            info = self._instances.get(instance_id)
            if not info or info.state == target_state:
                return True
            await asyncio.sleep(interval)
            elapsed += interval

        return False
