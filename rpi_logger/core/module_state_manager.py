"""
Module State Manager - Single source of truth for all module states.

This module provides centralized state management for logger modules using
an observer pattern. All state changes flow through this manager, ensuring
consistency across UI, config files, and process management.
"""

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Callable, Awaitable, Set, Any
from datetime import datetime

from rpi_logger.core.logging_utils import get_module_logger


class DesiredState(Enum):
    """User's desired state for a module."""
    DISABLED = "disabled"
    ENABLED = "enabled"


class ActualState(Enum):
    """Actual runtime state of a module process."""
    STOPPED = "stopped"          # Not running
    STARTING = "starting"        # Process launching
    INITIALIZING = "initializing"  # Process started, initializing
    IDLE = "idle"                # Running, ready
    RECORDING = "recording"      # Running, recording data
    STOPPING = "stopping"        # Shutting down
    ERROR = "error"              # Recoverable error
    CRASHED = "crashed"          # Unexpected termination


# States that indicate the module is "running" in some form
RUNNING_STATES = {
    ActualState.STARTING,
    ActualState.INITIALIZING,
    ActualState.IDLE,
    ActualState.RECORDING,
}

# States that indicate the module is "stopped" in some form
STOPPED_STATES = {
    ActualState.STOPPED,
    ActualState.CRASHED,
    ActualState.ERROR,
}


class StateEvent(Enum):
    """Events emitted by the state manager."""
    # Desired state changes
    DESIRED_STATE_CHANGED = "desired_state_changed"

    # Actual state changes
    ACTUAL_STATE_CHANGED = "actual_state_changed"

    # Action requests (for process manager)
    START_REQUESTED = "start_requested"
    STOP_REQUESTED = "stop_requested"

    # Special events
    CRASH_DETECTED = "crash_detected"
    STARTUP_COMPLETE = "startup_complete"
    ALL_MODULES_STOPPED = "all_modules_stopped"


@dataclass
class ModuleStateSnapshot:
    """Snapshot of a module's complete state."""
    name: str
    desired: DesiredState
    actual: ActualState
    last_desired_change: Optional[datetime] = None
    last_actual_change: Optional[datetime] = None
    error_message: Optional[str] = None
    crash_count: int = 0


@dataclass
class StateChange:
    """Represents a state change event."""
    event: StateEvent
    module_name: str
    old_value: Any = None
    new_value: Any = None
    timestamp: datetime = field(default_factory=datetime.now)


# Type alias for observer callbacks
StateObserver = Callable[[StateChange], Awaitable[None]]


class ModuleStateManager:
    """
    Single source of truth for all module states.

    This manager maintains two parallel state dictionaries:
    - desired_state: What the user wants (enabled/disabled)
    - actual_state: What's actually happening (stopped/starting/running/etc.)

    Observers can register to be notified of state changes. The manager
    also handles reconciliation - ensuring actual state moves toward
    desired state.
    """

    def __init__(self):
        self.logger = get_module_logger("ModuleStateManager")

        # Core state
        self._desired_state: Dict[str, DesiredState] = {}
        self._actual_state: Dict[str, ActualState] = {}

        # Metadata
        self._last_desired_change: Dict[str, datetime] = {}
        self._last_actual_change: Dict[str, datetime] = {}
        self._error_messages: Dict[str, Optional[str]] = {}
        self._crash_counts: Dict[str, int] = {}

        # Synchronization
        self._state_lock = asyncio.Lock()
        self._reconcile_lock = asyncio.Lock()

        # Observers
        self._observers: List[StateObserver] = []
        self._event_filters: Dict[StateObserver, Optional[Set[StateEvent]]] = {}

        # Startup tracking
        self._startup_modules: Set[str] = set()
        self._startup_complete = False

        # Reconciliation control
        self._reconciliation_enabled = True
        self._pending_reconciliations: Set[str] = set()

    # =========================================================================
    # Module Registration
    # =========================================================================

    def register_module(self, module_name: str) -> None:
        """Register a module with default states."""
        if module_name not in self._desired_state:
            self._desired_state[module_name] = DesiredState.DISABLED
            self._actual_state[module_name] = ActualState.STOPPED
            self._crash_counts[module_name] = 0
            self.logger.debug("Registered module: %s", module_name)

    def get_registered_modules(self) -> List[str]:
        """Get list of all registered module names."""
        return list(self._desired_state.keys())

    # =========================================================================
    # State Getters
    # =========================================================================

    def get_desired_state(self, module_name: str) -> DesiredState:
        """Get the user's desired state for a module."""
        return self._desired_state.get(module_name, DesiredState.DISABLED)

    def get_actual_state(self, module_name: str) -> ActualState:
        """Get the actual runtime state of a module."""
        return self._actual_state.get(module_name, ActualState.STOPPED)

    def is_module_enabled(self, module_name: str) -> bool:
        """Check if user wants module enabled."""
        return self.get_desired_state(module_name) == DesiredState.ENABLED

    def is_module_running(self, module_name: str) -> bool:
        """Check if module is actually running."""
        return self.get_actual_state(module_name) in RUNNING_STATES

    def is_module_stopped(self, module_name: str) -> bool:
        """Check if module is actually stopped."""
        return self.get_actual_state(module_name) in STOPPED_STATES

    def get_snapshot(self, module_name: str) -> Optional[ModuleStateSnapshot]:
        """Get a complete snapshot of a module's state."""
        if module_name not in self._desired_state:
            return None

        return ModuleStateSnapshot(
            name=module_name,
            desired=self._desired_state[module_name],
            actual=self._actual_state.get(module_name, ActualState.STOPPED),
            last_desired_change=self._last_desired_change.get(module_name),
            last_actual_change=self._last_actual_change.get(module_name),
            error_message=self._error_messages.get(module_name),
            crash_count=self._crash_counts.get(module_name, 0),
        )

    def get_all_snapshots(self) -> Dict[str, ModuleStateSnapshot]:
        """Get snapshots for all registered modules."""
        return {
            name: self.get_snapshot(name)
            for name in self._desired_state
            if self.get_snapshot(name) is not None
        }

    def get_enabled_modules(self) -> List[str]:
        """Get list of modules the user wants enabled."""
        return [
            name for name, state in self._desired_state.items()
            if state == DesiredState.ENABLED
        ]

    def get_running_modules(self) -> List[str]:
        """Get list of modules that are actually running."""
        return [
            name for name, state in self._actual_state.items()
            if state in RUNNING_STATES
        ]

    def get_desired_states(self) -> Dict[str, bool]:
        """Get all desired states as a bool dict (for compatibility)."""
        return {
            name: state == DesiredState.ENABLED
            for name, state in self._desired_state.items()
        }

    # =========================================================================
    # State Setters
    # =========================================================================

    async def set_desired_state(
        self,
        module_name: str,
        enabled: bool,
        *,
        reconcile: bool = True
    ) -> None:
        """
        Set the user's desired state for a module.

        Args:
            module_name: Name of the module
            enabled: True to enable, False to disable
            reconcile: If True, trigger reconciliation after state change
        """
        new_state = DesiredState.ENABLED if enabled else DesiredState.DISABLED
        state_changed = False

        async with self._state_lock:
            old_state = self._desired_state.get(module_name, DesiredState.DISABLED)

            if old_state == new_state:
                self.logger.debug(
                    "Module %s desired state unchanged: %s",
                    module_name, new_state.value
                )
            else:
                self._desired_state[module_name] = new_state
                self._last_desired_change[module_name] = datetime.now()
                state_changed = True

                self.logger.info(
                    "Module %s desired state: %s -> %s",
                    module_name, old_state.value, new_state.value
                )

        # Notify observers only if state changed
        if state_changed:
            change = StateChange(
                event=StateEvent.DESIRED_STATE_CHANGED,
                module_name=module_name,
                old_value=old_state,
                new_value=new_state,
            )
            await self._notify_observers(change)

        # Always trigger reconciliation if requested (even if state unchanged)
        # This ensures the module starts if desired=enabled but actual=stopped
        if reconcile and self._reconciliation_enabled:
            await self._request_reconciliation(module_name)

    async def set_actual_state(
        self,
        module_name: str,
        state: ActualState,
        *,
        error_message: Optional[str] = None
    ) -> None:
        """
        Update the actual runtime state of a module.

        This should be called by the process manager when module state changes.

        Args:
            module_name: Name of the module
            state: New actual state
            error_message: Optional error message (for ERROR/CRASHED states)
        """
        async with self._state_lock:
            old_state = self._actual_state.get(module_name, ActualState.STOPPED)

            if old_state == state:
                self.logger.debug(
                    "Module %s actual state unchanged: %s",
                    module_name, state.value
                )
                return

            self._actual_state[module_name] = state
            self._last_actual_change[module_name] = datetime.now()

            if error_message:
                self._error_messages[module_name] = error_message
            elif state not in (ActualState.ERROR, ActualState.CRASHED):
                self._error_messages[module_name] = None

            # Track crashes
            if state == ActualState.CRASHED:
                self._crash_counts[module_name] = self._crash_counts.get(module_name, 0) + 1

            self.logger.info(
                "Module %s actual state: %s -> %s",
                module_name, old_state.value, state.value
            )

        # Notify observers of state change
        change = StateChange(
            event=StateEvent.ACTUAL_STATE_CHANGED,
            module_name=module_name,
            old_value=old_state,
            new_value=state,
        )
        await self._notify_observers(change)

        # Special handling for crashes
        if state == ActualState.CRASHED:
            crash_change = StateChange(
                event=StateEvent.CRASH_DETECTED,
                module_name=module_name,
                new_value=self._crash_counts.get(module_name, 1),
            )
            await self._notify_observers(crash_change)

        # Check if all modules stopped (for shutdown)
        if state in STOPPED_STATES:
            all_stopped = all(
                s in STOPPED_STATES
                for s in self._actual_state.values()
            )
            if all_stopped and self._actual_state:
                await self._notify_observers(StateChange(
                    event=StateEvent.ALL_MODULES_STOPPED,
                    module_name="",
                ))

    async def clear_error(self, module_name: str) -> None:
        """Clear error state and message for a module."""
        async with self._state_lock:
            self._error_messages[module_name] = None
            if self._actual_state.get(module_name) == ActualState.ERROR:
                self._actual_state[module_name] = ActualState.STOPPED

    def reset_crash_count(self, module_name: str) -> None:
        """Reset the crash counter for a module."""
        self._crash_counts[module_name] = 0

    # =========================================================================
    # Bulk State Operations
    # =========================================================================

    async def set_all_desired_states(
        self,
        states: Dict[str, bool],
        *,
        reconcile: bool = True
    ) -> None:
        """Set desired states for multiple modules at once."""
        for module_name, enabled in states.items():
            await self.set_desired_state(module_name, enabled, reconcile=False)

        if reconcile and self._reconciliation_enabled:
            for module_name in states:
                await self._request_reconciliation(module_name)

    async def disable_all(self, *, reconcile: bool = True) -> None:
        """Disable all modules."""
        for module_name in self._desired_state:
            await self.set_desired_state(module_name, False, reconcile=False)

        if reconcile and self._reconciliation_enabled:
            for module_name in self._desired_state:
                await self._request_reconciliation(module_name)

    # =========================================================================
    # Observer Management
    # =========================================================================

    def add_observer(
        self,
        observer: StateObserver,
        *,
        events: Optional[Set[StateEvent]] = None
    ) -> None:
        """
        Register an observer for state changes.

        Args:
            observer: Async callback function
            events: Optional set of events to filter. If None, receives all events.
        """
        if observer not in self._observers:
            self._observers.append(observer)
            self._event_filters[observer] = events
            self.logger.debug(
                "Added observer %s (filter: %s)",
                observer.__name__ if hasattr(observer, '__name__') else str(observer),
                events
            )

    def remove_observer(self, observer: StateObserver) -> None:
        """Remove an observer."""
        if observer in self._observers:
            self._observers.remove(observer)
            self._event_filters.pop(observer, None)
            self.logger.debug(
                "Removed observer %s",
                observer.__name__ if hasattr(observer, '__name__') else str(observer)
            )

    async def _notify_observers(self, change: StateChange) -> None:
        """Notify all observers of a state change."""
        for observer in self._observers:
            # Check event filter
            event_filter = self._event_filters.get(observer)
            if event_filter is not None and change.event not in event_filter:
                continue

            try:
                await observer(change)
            except Exception as e:
                self.logger.error(
                    "Observer %s error handling %s: %s",
                    observer.__name__ if hasattr(observer, '__name__') else str(observer),
                    change.event.value,
                    e,
                    exc_info=True
                )

    # =========================================================================
    # Reconciliation
    # =========================================================================

    async def _request_reconciliation(self, module_name: str) -> None:
        """Request reconciliation for a module."""
        if not self._reconciliation_enabled:
            return

        desired = self.get_desired_state(module_name)
        actual = self.get_actual_state(module_name)

        # Determine what action is needed
        if desired == DesiredState.ENABLED and actual in STOPPED_STATES:
            # Need to start
            self.logger.info("Reconciliation: requesting start for %s", module_name)
            await self._notify_observers(StateChange(
                event=StateEvent.START_REQUESTED,
                module_name=module_name,
            ))

        elif desired == DesiredState.DISABLED and actual in RUNNING_STATES:
            # Need to stop
            self.logger.info("Reconciliation: requesting stop for %s", module_name)
            await self._notify_observers(StateChange(
                event=StateEvent.STOP_REQUESTED,
                module_name=module_name,
            ))

    async def reconcile_all(self) -> None:
        """Reconcile all modules."""
        for module_name in self._desired_state:
            await self._request_reconciliation(module_name)

    def enable_reconciliation(self) -> None:
        """Enable automatic reconciliation."""
        self._reconciliation_enabled = True

    def disable_reconciliation(self) -> None:
        """Disable automatic reconciliation (useful during bulk operations)."""
        self._reconciliation_enabled = False

    # =========================================================================
    # Startup Tracking
    # =========================================================================

    def mark_startup_module(self, module_name: str) -> None:
        """Mark a module as part of the startup set."""
        self._startup_modules.add(module_name)

    def clear_startup_modules(self) -> None:
        """Clear the startup module set."""
        self._startup_modules.clear()

    async def check_startup_complete(self) -> bool:
        """
        Check if all startup modules have successfully started.

        Returns True if startup is complete (all modules running or failed).
        """
        if self._startup_complete:
            return True

        if not self._startup_modules:
            return True

        for module_name in self._startup_modules:
            actual = self.get_actual_state(module_name)
            # Still waiting if module is starting
            if actual == ActualState.STARTING:
                return False

        # All startup modules have reached a stable state
        self._startup_complete = True

        # Check success
        failed = [
            name for name in self._startup_modules
            if self.get_actual_state(name) in STOPPED_STATES
        ]

        if failed:
            self.logger.warning(
                "Startup complete with failures: %s", failed
            )
        else:
            self.logger.info("Startup complete - all modules running")

        await self._notify_observers(StateChange(
            event=StateEvent.STARTUP_COMPLETE,
            module_name="",
            new_value=len(failed) == 0,
        ))

        return True

    @property
    def is_startup_complete(self) -> bool:
        """Check if startup phase is complete."""
        return self._startup_complete

    # =========================================================================
    # State Queries
    # =========================================================================

    def needs_start(self, module_name: str) -> bool:
        """Check if module should be started (enabled but not running)."""
        return (
            self.get_desired_state(module_name) == DesiredState.ENABLED and
            self.get_actual_state(module_name) in STOPPED_STATES
        )

    def needs_stop(self, module_name: str) -> bool:
        """Check if module should be stopped (disabled but running)."""
        return (
            self.get_desired_state(module_name) == DesiredState.DISABLED and
            self.get_actual_state(module_name) in RUNNING_STATES
        )

    def is_state_consistent(self, module_name: str) -> bool:
        """Check if desired and actual states are consistent."""
        desired = self.get_desired_state(module_name)
        actual = self.get_actual_state(module_name)

        if desired == DesiredState.ENABLED:
            return actual in RUNNING_STATES
        else:
            return actual in STOPPED_STATES

    def all_states_consistent(self) -> bool:
        """Check if all modules have consistent states."""
        return all(
            self.is_state_consistent(name)
            for name in self._desired_state
        )
