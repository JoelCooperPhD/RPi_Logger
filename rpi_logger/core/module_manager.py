"""
Module Manager - Handles module discovery, selection, and lifecycle.

This module provides centralized management of logger modules including
discovery, selection state, and process lifecycle management.

The ModuleManager now delegates state tracking to ModuleStateManager and
acts primarily as a process manager that responds to state change events.
"""

import asyncio
from rpi_logger.core.logging_utils import get_module_logger
from pathlib import Path
from typing import Awaitable, Dict, List, Optional, Callable, Set

from .module_discovery import ModuleInfo, discover_modules
from .module_process import ModuleProcess, ModuleState
from .module_state_manager import (
    ModuleStateManager,
    StateChange,
    StateEvent,
    ActualState,
    DesiredState,
    RUNNING_STATES,
    STOPPED_STATES,
)
from .commands import StatusMessage
from .window_manager import WindowGeometry
from .config_manager import get_config_manager


class ModuleManager:
    """
    Manages module discovery, selection, and lifecycle.

    This class now integrates with ModuleStateManager for state tracking
    and acts as a process manager that responds to state change events.

    Responsibilities:
    - Discover available modules
    - Manage module processes (start, stop, status)
    - Respond to state manager events (START_REQUESTED, STOP_REQUESTED)
    - Report actual state changes back to state manager
    """

    def __init__(
        self,
        session_dir: Path,
        session_prefix: str = "session",
        log_level: str = "info",
        status_callback: Optional[Callable] = None,
        state_manager: Optional[ModuleStateManager] = None,
    ):
        self.logger = get_module_logger("ModuleManager")
        self.session_dir = Path(session_dir)
        self.session_prefix = session_prefix
        self.log_level = log_level
        self.status_callback = status_callback

        # State manager (can be injected or created)
        self.state_manager = state_manager or ModuleStateManager()

        # Process tracking
        self.available_modules: List[ModuleInfo] = []
        self.module_processes: Dict[str, ModuleProcess] = {}
        self.window_geometry_cache: Dict[str, Optional[WindowGeometry]] = {}

        # Locks for process operations
        self._process_locks: Dict[str, asyncio.Lock] = {}

        # Legacy compatibility (deprecated - use state_manager instead)
        self._legacy_state_changing: Dict[str, bool] = {}
        self._legacy_callbacks: List[Callable] = []

        # Track forcefully stopped modules
        self.forcefully_stopped_modules: Set[str] = set()

        self.config_manager = get_config_manager()

        # Health check task
        self._health_check_task: Optional[asyncio.Task] = None
        self._shutdown = False

        # Discover modules and register with state manager
        self._discover_modules()

        # Register as observer for state manager events
        self.state_manager.add_observer(
            self._handle_state_event,
            events={StateEvent.START_REQUESTED, StateEvent.STOP_REQUESTED}
        )

    def _discover_modules(self) -> None:
        """Discover all available modules and register with state manager."""
        self.logger.info("Discovering modules...")
        self.available_modules = discover_modules()
        self.logger.info("Found %d modules: %s",
                        len(self.available_modules),
                        [m.name for m in self.available_modules])

        # Register each module with state manager
        for module_info in self.available_modules:
            self.state_manager.register_module(module_info.name)

    def _get_process_lock(self, module_name: str) -> asyncio.Lock:
        """Get or create a lock for a module's process operations."""
        lock = self._process_locks.get(module_name)
        if lock is None:
            lock = asyncio.Lock()
            self._process_locks[module_name] = lock
        return lock

    # =========================================================================
    # State Manager Event Handler
    # =========================================================================

    async def _handle_state_event(self, change: StateChange) -> None:
        """Handle events from the state manager."""
        if change.event == StateEvent.START_REQUESTED:
            await self._start_module_process(change.module_name)

        elif change.event == StateEvent.STOP_REQUESTED:
            await self._stop_module_process(change.module_name)

    # =========================================================================
    # Module State Queries (delegate to state manager)
    # =========================================================================

    def is_module_enabled(self, module_name: str) -> bool:
        """Check if a module is enabled (user's desired state)."""
        return self.state_manager.is_module_enabled(module_name)

    def is_module_running(self, module_name: str) -> bool:
        """Check if a module process is currently running."""
        # Check both state manager and actual process
        process = self.module_processes.get(module_name)
        return process is not None and process.is_running()

    def get_module_state(self, module_name: str) -> Optional[ModuleState]:
        """Get the current state of a module process."""
        process = self.module_processes.get(module_name)
        if process:
            return process.get_state()
        return None

    def is_module_state_changing(self, module_name: str) -> bool:
        """Check if a module is currently transitioning state."""
        actual = self.state_manager.get_actual_state(module_name)
        return actual in (ActualState.STARTING, ActualState.STOPPING)

    def get_module_enabled_states(self) -> Dict[str, bool]:
        """Get all module enabled states."""
        return self.state_manager.get_desired_states()

    def get_selected_modules(self) -> List[str]:
        """Get list of currently enabled module names."""
        return self.state_manager.get_enabled_modules()

    def get_running_modules(self) -> List[str]:
        """Get list of currently running module names."""
        return [
            name for name, proc in self.module_processes.items()
            if proc.is_running()
        ]

    def get_available_modules(self) -> List[ModuleInfo]:
        """Get list of all discovered modules."""
        return self.available_modules

    def get_module(self, module_name: str) -> Optional[ModuleProcess]:
        """Get the ModuleProcess instance for a module if it exists."""
        return self.module_processes.get(module_name)

    # =========================================================================
    # Module State Setters
    # =========================================================================

    async def set_module_enabled(self, module_name: str, enabled: bool) -> bool:
        """
        Set module enabled state (central entry point).

        This sets the desired state in the state manager, which will
        trigger START_REQUESTED or STOP_REQUESTED events that this
        manager responds to.

        Args:
            module_name: Name of the module
            enabled: True to enable/start, False to disable/stop

        Returns:
            True if state change succeeded, False otherwise
        """
        # Set desired state - this triggers reconciliation which will
        # call _start_module_process or _stop_module_process
        # Note: Don't hold the lock here as the event handlers need it
        await self.state_manager.set_desired_state(module_name, enabled)

        # Wait for actual state to match (with timeout)
        try:
            await asyncio.wait_for(
                self._wait_for_state_consistency(module_name),
                timeout=30.0
            )
            return True
        except asyncio.TimeoutError:
            self.logger.error(
                "Timeout waiting for module %s to reach state: enabled=%s",
                module_name, enabled
            )
            return False

    async def _wait_for_state_consistency(self, module_name: str) -> None:
        """Wait for a module's actual state to match its desired state."""
        while not self.state_manager.is_state_consistent(module_name):
            await asyncio.sleep(0.1)

    async def toggle_module_enabled(self, module_name: str, enabled: bool) -> bool:
        """
        Update a module's enabled state in its config file.

        Note: This is now handled by ConfigPersistenceObserver automatically
        when desired state changes. This method exists for explicit config updates.
        """
        module_info = next(
            (m for m in self.available_modules if m.name == module_name),
            None
        )
        if not module_info or not module_info.config_path:
            self.logger.warning("Cannot update enabled state - no config for %s", module_name)
            return False

        success = await self.config_manager.write_config_async(
            module_info.config_path,
            {'enabled': enabled}
        )

        if success:
            self.logger.info("Updated %s enabled state to %s", module_name, enabled)
        else:
            self.logger.error("Failed to update %s enabled state", module_name)

        return success

    # =========================================================================
    # Config Loading
    # =========================================================================

    async def load_enabled_modules(self) -> None:
        """Load module enabled state from configs (sets desired state)."""
        for module_info in self.available_modules:
            if not module_info.config_path:
                # No config - default to disabled
                await self.state_manager.set_desired_state(
                    module_info.name, False, reconcile=False
                )
                self.logger.debug(
                    "Module %s has no config, defaulting to disabled",
                    module_info.name
                )
                continue

            config = await self.config_manager.read_config_async(module_info.config_path)
            enabled = self.config_manager.get_bool(config, 'enabled', default=False)

            await self.state_manager.set_desired_state(
                module_info.name, enabled, reconcile=False
            )

            if enabled:
                self.logger.info("Module %s enabled in config", module_info.name)
            else:
                self.logger.debug("Module %s disabled in config", module_info.name)

    # =========================================================================
    # Module Info Queries
    # =========================================================================

    def is_internal_module(self, module_id: str) -> bool:
        """Check if a module is internal (software-only, no hardware).

        Args:
            module_id: Module ID or instance ID (e.g., "Notes" or "Notes:default")

        Returns:
            True if the module is marked as internal in its config
        """
        # Extract base module ID from instance ID (e.g., "Notes" from "Notes:default")
        base_id = module_id.split(":")[0] if ":" in module_id else module_id

        module_info = next(
            (m for m in self.available_modules
             if m.name.lower() == base_id.lower() or m.module_id == base_id.lower()),
            None
        )
        return module_info.is_internal if module_info else False

    # =========================================================================
    # Process Management
    # =========================================================================

    async def start_module(self, module_name: str) -> bool:
        """Start a module (routes through state machine)."""
        return await self.set_module_enabled(module_name, True)

    async def stop_module(self, module_name: str) -> bool:
        """Stop a module (routes through state machine)."""
        return await self.set_module_enabled(module_name, False)

    async def start_module_instance(
        self,
        module_id: str,
        instance_id: str,
        window_geometry: Optional[WindowGeometry] = None
    ) -> bool:
        """Start a module instance with a specific instance ID.

        This allows multiple instances of the same module to run simultaneously,
        each with a unique instance ID (e.g., "DRT:ACM0", "DRT:ACM1").

        Args:
            module_id: Base module ID (e.g., "DRT") - used to find ModuleInfo
            instance_id: Unique instance ID (e.g., "DRT:ACM0") - used as process key
            window_geometry: Optional window geometry for the instance

        Returns:
            True if the instance started successfully
        """
        self.logger.info(
            "Starting module instance: %s (base module: %s)",
            instance_id, module_id
        )

        # Find module info using the base module ID
        # Module names in available_modules use folder names (e.g., "DRT", "VOG")
        module_info = next(
            (m for m in self.available_modules
             if m.name.lower() == module_id.lower() or m.module_id == module_id.lower()),
            None
        )
        if not module_info:
            self.logger.error("Module info not found for: %s", module_id)
            return False

        # Cache geometry for this instance
        if window_geometry:
            self.window_geometry_cache[instance_id] = window_geometry

        # Start the process with the instance ID as the key
        return await self._start_module_process_for_instance(
            module_info, instance_id
        )

    async def stop_module_instance(self, instance_id: str) -> bool:
        """Stop a specific module instance.

        Args:
            instance_id: The instance ID to stop (e.g., "DRT:ACM0")

        Returns:
            True if the instance was stopped successfully
        """
        self.logger.info("Stopping module instance: %s", instance_id)

        lock = self._get_process_lock(instance_id)

        async with lock:
            process = self.module_processes.get(instance_id)

            if not process:
                self.logger.debug("Instance %s already stopped (no process)", instance_id)
                return True

            if not process.is_running():
                self.logger.debug("Instance %s already stopped", instance_id)
                self.module_processes.pop(instance_id, None)
                return True

            try:
                await process.stop()
                self.module_processes.pop(instance_id, None)
                self.logger.info("Instance %s stopped successfully", instance_id)
                return True

            except Exception as e:
                self.logger.error(
                    "Exception stopping instance %s: %s",
                    instance_id, e, exc_info=True
                )
                return False

    async def kill_module_instance(self, instance_id: str) -> bool:
        """Force kill a module instance.

        Args:
            instance_id: The instance ID to kill (e.g., "DRT:ACM0")

        Returns:
            True if the instance was killed successfully
        """
        self.logger.warning("Force killing module instance: %s", instance_id)

        lock = self._get_process_lock(instance_id)

        async with lock:
            process = self.module_processes.get(instance_id)

            if not process:
                self.logger.debug("Instance %s not found for kill", instance_id)
                return True

            if not process.is_running():
                self.logger.debug("Instance %s already stopped", instance_id)
                self.module_processes.pop(instance_id, None)
                return True

            try:
                await process.kill()
                self.module_processes.pop(instance_id, None)
                self.logger.info("Instance %s killed", instance_id)
                return True

            except Exception as e:
                self.logger.error(
                    "Exception killing instance %s: %s",
                    instance_id, e, exc_info=True
                )
                return False

    async def _start_module_process_for_instance(
        self,
        module_info: ModuleInfo,
        instance_id: str
    ) -> bool:
        """Internal: Start a module process for a specific instance.

        This is similar to _start_module_process but uses an instance_id
        as the key instead of the module name, allowing multiple instances.

        Args:
            module_info: The module info (entry point, config, etc.)
            instance_id: The unique instance ID (e.g., "DRT:ACM0")

        Returns:
            True if the process started successfully
        """
        lock = self._get_process_lock(instance_id)

        async with lock:
            # Clean up any existing process with this instance ID
            if instance_id in self.module_processes:
                process = self.module_processes[instance_id]
                if process.is_running():
                    self.logger.info(
                        "Instance %s still running, stopping first...",
                        instance_id
                    )
                    await process.stop()
                    await asyncio.sleep(0.1)
                self.module_processes.pop(instance_id, None)

            self.logger.info(
                "Starting instance %s (module: %s) with session dir: %s",
                instance_id, module_info.name, self.session_dir
            )

            # Get cached geometry for this instance
            window_geometry = self.window_geometry_cache.get(instance_id)

            # Create and start process
            process = ModuleProcess(
                module_info,
                self.session_dir,
                session_prefix=self.session_prefix,
                status_callback=self._make_instance_status_callback(instance_id),
                log_level=self.log_level,
                window_geometry=window_geometry,
                instance_id=instance_id,
            )

            try:
                success = await process.start()

                if success:
                    self.module_processes[instance_id] = process
                    self.forcefully_stopped_modules.discard(instance_id)
                    self.logger.info("Instance %s started successfully", instance_id)
                else:
                    self.logger.error("Instance %s failed to start", instance_id)

                return success

            except Exception as e:
                self.logger.error(
                    "Exception starting instance %s: %s",
                    instance_id, e, exc_info=True
                )
                return False

    def _make_instance_status_callback(
        self,
        instance_id: str
    ) -> Callable[[ModuleProcess, Optional[StatusMessage]], Awaitable[None]]:
        """Create a status callback for a module instance.

        The callback wraps the process to include the instance ID so the
        main status callback can route it correctly.
        """
        async def callback(process: ModuleProcess, status: Optional[StatusMessage]) -> None:
            # Forward to the main process status callback with instance tracking
            await self._process_status_callback_for_instance(instance_id, process, status)

        return callback

    async def _process_status_callback_for_instance(
        self,
        instance_id: str,
        process: ModuleProcess,
        status: Optional[StatusMessage]
    ) -> None:
        """Handle status updates from module instance processes.

        Similar to _process_status_callback but uses instance_id for tracking
        instead of module_info.name.
        """
        module_name = process.module_info.name

        if status:
            self.logger.debug(
                "Instance %s (module %s) status: %s",
                instance_id, module_name, status.get_status_type()
            )

            # Handle quitting status
            if status.get_status_type() == "quitting":
                self.logger.info("Instance %s quitting gracefully", instance_id)
                # Clean up the instance from our tracking
                self.module_processes.pop(instance_id, None)

        # Check for unexpected process termination
        if not process.is_running():
            if instance_id in self.module_processes:
                self.logger.warning("Instance %s stopped unexpectedly", instance_id)
                self.module_processes.pop(instance_id, None)

        # Forward to external callback with instance_id
        if self.status_callback:
            # Pass instance_id as module_name so LoggerSystem can route correctly
            await self.status_callback(process, status, instance_id=instance_id)

    async def _start_module_process(self, module_name: str) -> bool:
        """
        Internal: Start a module process.

        Called in response to START_REQUESTED event.
        """
        lock = self._get_process_lock(module_name)

        async with lock:
            # Update actual state to STARTING
            await self.state_manager.set_actual_state(
                module_name, ActualState.STARTING
            )

            # Clean up any existing process
            if module_name in self.module_processes:
                process = self.module_processes[module_name]
                if process.is_running():
                    self.logger.info(
                        "Module %s still running, stopping first...",
                        module_name
                    )
                    await process.stop()
                    await asyncio.sleep(0.1)
                self.module_processes.pop(module_name, None)

            # Find module info
            module_info = next(
                (m for m in self.available_modules if m.name == module_name),
                None
            )
            if not module_info:
                self.logger.error("Module info not found: %s", module_name)
                await self.state_manager.set_actual_state(
                    module_name,
                    ActualState.ERROR,
                    error_message="Module not found"
                )
                return False

            self.logger.info(
                "Starting module %s with session dir: %s",
                module_name, self.session_dir
            )

            # Get cached geometry
            window_geometry = self.window_geometry_cache.get(module_name)

            # Create and start process
            process = ModuleProcess(
                module_info,
                self.session_dir,
                session_prefix=self.session_prefix,
                status_callback=self._process_status_callback,
                log_level=self.log_level,
                window_geometry=window_geometry,
            )

            try:
                success = await process.start()

                if success:
                    self.module_processes[module_name] = process
                    self.forcefully_stopped_modules.discard(module_name)

                    # Update actual state to IDLE (running)
                    await self.state_manager.set_actual_state(
                        module_name, ActualState.IDLE
                    )
                    self.logger.info("Module %s started successfully", module_name)
                else:
                    await self.state_manager.set_actual_state(
                        module_name,
                        ActualState.ERROR,
                        error_message="Failed to start"
                    )
                    self.logger.error("Module %s failed to start", module_name)

                return success

            except Exception as e:
                self.logger.error(
                    "Exception starting %s: %s",
                    module_name, e, exc_info=True
                )
                await self.state_manager.set_actual_state(
                    module_name,
                    ActualState.ERROR,
                    error_message=str(e)
                )
                return False

    async def _stop_module_process(self, module_name: str) -> bool:
        """
        Internal: Stop a module process.

        Called in response to STOP_REQUESTED event.
        """
        lock = self._get_process_lock(module_name)

        async with lock:
            process = self.module_processes.get(module_name)

            if not process:
                self.logger.debug(
                    "Module %s already stopped (no process)",
                    module_name
                )
                await self.state_manager.set_actual_state(
                    module_name, ActualState.STOPPED
                )
                return True

            if not process.is_running():
                self.logger.debug("Module %s already stopped", module_name)
                self._handle_process_stopped(module_name, process)
                return True

            # Update actual state to STOPPING
            await self.state_manager.set_actual_state(
                module_name, ActualState.STOPPING
            )

            try:
                # Pause recording if active
                if process.is_recording():
                    await process.pause()

                # Stop the process
                await process.stop()

                # Handle cleanup
                self._handle_process_stopped(module_name, process)

                self.logger.info("Module %s stopped successfully", module_name)
                return True

            except Exception as e:
                self.logger.error(
                    "Error stopping %s: %s",
                    module_name, e, exc_info=True
                )
                self.forcefully_stopped_modules.add(module_name)
                await self.state_manager.set_actual_state(
                    module_name, ActualState.STOPPED
                )
                return False

    def _handle_process_stopped(self, module_name: str, process: ModuleProcess) -> None:
        """Handle cleanup when a process stops."""
        if process.was_forcefully_stopped:
            self.forcefully_stopped_modules.add(module_name)
        else:
            self.forcefully_stopped_modules.discard(module_name)

        self.module_processes.pop(module_name, None)

        # Update state manager (don't await in sync context)
        asyncio.create_task(
            self.state_manager.set_actual_state(module_name, ActualState.STOPPED)
        )

    async def _process_status_callback(
        self,
        process: ModuleProcess,
        status: Optional[StatusMessage]
    ) -> None:
        """Handle status updates from module processes."""
        module_name = process.module_info.name

        # Update actual state based on process state
        process_state = process.get_state()
        actual_state = self._convert_process_state(process_state)

        if actual_state:
            current = self.state_manager.get_actual_state(module_name)
            if current != actual_state:
                await self.state_manager.set_actual_state(module_name, actual_state)

        # Handle process death
        if not process.is_running():
            current = self.state_manager.get_actual_state(module_name)
            if current in RUNNING_STATES:
                self.logger.warning(
                    "Module %s process died unexpectedly",
                    module_name
                )
                await self.state_manager.set_actual_state(
                    module_name, ActualState.CRASHED
                )
                # Also update desired state to disabled
                await self.state_manager.set_desired_state(
                    module_name, False, reconcile=False
                )

        # Forward to external callback
        if self.status_callback:
            await self.status_callback(process, status)

    def _convert_process_state(self, process_state: ModuleState) -> Optional[ActualState]:
        """Convert ModuleProcess state to ActualState."""
        mapping = {
            ModuleState.STOPPED: ActualState.STOPPED,
            ModuleState.STARTING: ActualState.STARTING,
            ModuleState.INITIALIZING: ActualState.INITIALIZING,
            ModuleState.IDLE: ActualState.IDLE,
            ModuleState.RECORDING: ActualState.RECORDING,
            ModuleState.STOPPING: ActualState.STOPPING,
            ModuleState.ERROR: ActualState.ERROR,
            ModuleState.CRASHED: ActualState.CRASHED,
        }
        return mapping.get(process_state)

    # =========================================================================
    # Bulk Operations
    # =========================================================================

    async def stop_all(self) -> None:
        """Stop all running module processes."""
        import time
        self.logger.info("Stopping all modules")

        # Disable reconciliation during bulk stop
        self.state_manager.disable_reconciliation()

        stop_tasks = []
        for module_name, process in list(self.module_processes.items()):
            if process.is_running():
                async def stop_module_task(name: str, proc: ModuleProcess):
                    try:
                        module_start = time.time()
                        await self.state_manager.set_actual_state(
                            name, ActualState.STOPPING
                        )
                        await proc.stop()
                        module_duration = time.time() - module_start
                        self.logger.info(
                            "Module %s stopped in %.3fs",
                            name, module_duration
                        )
                        if proc.was_forcefully_stopped:
                            self.forcefully_stopped_modules.add(name)
                        else:
                            self.forcefully_stopped_modules.discard(name)
                        await self.state_manager.set_actual_state(
                            name, ActualState.STOPPED
                        )
                    except Exception as e:
                        self.logger.error("Error stopping %s: %s", name, e)
                        self.forcefully_stopped_modules.add(name)
                        await self.state_manager.set_actual_state(
                            name, ActualState.STOPPED
                        )

                stop_tasks.append(stop_module_task(module_name, process))

        if stop_tasks:
            await asyncio.gather(*stop_tasks, return_exceptions=True)

        self.module_processes.clear()

        # Re-enable reconciliation
        self.state_manager.enable_reconciliation()

        self.logger.info("All modules stopped")

    # =========================================================================
    # Health Check
    # =========================================================================

    async def start_health_check(self, interval: float = 5.0) -> None:
        """Start the health check loop."""
        if self._health_check_task is not None:
            return

        self._shutdown = False
        self._health_check_task = asyncio.create_task(
            self._health_check_loop(interval)
        )
        self.logger.info("Health check started (interval: %.1fs)", interval)

    async def stop_health_check(self) -> None:
        """Stop the health check loop."""
        self._shutdown = True
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
            self._health_check_task = None
        self.logger.info("Health check stopped")

    async def _health_check_loop(self, interval: float) -> None:
        """Periodically verify module processes are healthy."""
        while not self._shutdown:
            await asyncio.sleep(interval)

            for module_name, process in list(self.module_processes.items()):
                if not process.is_running():
                    actual = self.state_manager.get_actual_state(module_name)
                    if actual in RUNNING_STATES:
                        self.logger.warning(
                            "Health check: module %s died unexpectedly",
                            module_name
                        )
                        await self.state_manager.set_actual_state(
                            module_name, ActualState.CRASHED
                        )
                        # Update desired state
                        await self.state_manager.set_desired_state(
                            module_name, False, reconcile=False
                        )

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def set_window_geometry(
        self,
        module_name: str,
        geometry: Optional[WindowGeometry]
    ) -> None:
        """Cache window geometry for a module to use on next start."""
        self.window_geometry_cache[module_name] = geometry

    def set_session_dir(self, session_dir: Path) -> None:
        """Update the base session directory used for new module launches."""
        self.session_dir = Path(session_dir)
        self.logger.info("ModuleManager session directory set to: %s", self.session_dir)

    async def send_command(self, module_name: str, command: str) -> bool:
        """Send a raw command string to a running module process."""
        process = self.module_processes.get(module_name)
        if not process or not process.is_running():
            self.logger.warning(
                "Cannot send command to %s - process not running",
                module_name
            )
            return False
        try:
            await process.send_command(command)
            return True
        except Exception as exc:
            self.logger.error("Failed to send command to %s: %s", module_name, exc)
            return False

    # Alias for compatibility with robust connection patterns
    send_command_raw = send_command

    def cleanup_stopped_process(self, module_name: str) -> None:
        """Remove a stopped process from tracking."""
        if module_name in self.module_processes:
            process = self.module_processes[module_name]
            if not process.is_running():
                self.module_processes.pop(module_name, None)
                if process.was_forcefully_stopped:
                    self.forcefully_stopped_modules.add(module_name)
                else:
                    self.forcefully_stopped_modules.discard(module_name)
                self.logger.debug("Cleaned up stopped process: %s", module_name)

    # =========================================================================
    # Legacy Compatibility (deprecated)
    # =========================================================================

    @property
    def module_enabled_state(self) -> Dict[str, bool]:
        """Legacy property - use state_manager.get_desired_states() instead."""
        return self.state_manager.get_desired_states()

    @module_enabled_state.setter
    def module_enabled_state(self, value: Dict[str, bool]) -> None:
        """Legacy setter - sets desired states without reconciliation."""
        for name, enabled in value.items():
            # Set state without reconciliation (sync context)
            self.state_manager._desired_state[name] = (
                DesiredState.ENABLED if enabled else DesiredState.DISABLED
            )

    @property
    def module_state_changing(self) -> Dict[str, bool]:
        """Legacy property for state changing check."""
        return {
            name: self.is_module_state_changing(name)
            for name in self.state_manager.get_registered_modules()
        }

    def register_state_change_callback(self, callback: Callable) -> None:
        """Legacy: Register a callback for state changes."""
        self._legacy_callbacks.append(callback)
