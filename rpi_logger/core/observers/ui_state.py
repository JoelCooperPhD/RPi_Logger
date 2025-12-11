"""
UI State Observer - Updates UI elements to reflect module state changes.

This observer listens for state changes and updates the corresponding
UI elements (checkboxes, status indicators, etc.) to keep the display
in sync with the actual module state.
"""

import tkinter as tk
from typing import Dict, Optional, Callable, Any

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.core.module_state_manager import (
    StateChange,
    StateEvent,
    DesiredState,
    ActualState,
    RUNNING_STATES,
    STOPPED_STATES,
)


class UIStateObserver:
    """
    Updates UI elements to reflect module state changes.

    This observer maintains references to UI elements (checkboxes, labels)
    and updates them when the corresponding module state changes.
    """

    def __init__(self, root: Optional[tk.Tk] = None):
        """
        Initialize the observer.

        Args:
            root: The Tk root window (for thread-safe updates)
        """
        self.logger = get_module_logger("UIStateObserver")
        self._root = root

        # Module checkbox variables
        self._checkbox_vars: Dict[str, tk.BooleanVar] = {}

        # Optional status label callback
        self._status_callback: Optional[Callable[[str, ActualState], None]] = None

        # Optional module state change callback (for MainController)
        self._module_state_callback: Optional[
            Callable[[str, ActualState, Optional[Any]], Any]
        ] = None

        # Flag to disable updates during shutdown
        self._shutdown = False

    def set_root(self, root: tk.Tk) -> None:
        """Set the Tk root window."""
        self._root = root

    def register_checkbox(self, module_name: str, var: tk.BooleanVar) -> None:
        """Register a checkbox variable for a module."""
        self._checkbox_vars[module_name] = var
        self.logger.debug("Registered checkbox for module %s", module_name)

    def unregister_checkbox(self, module_name: str) -> None:
        """Unregister a checkbox variable."""
        self._checkbox_vars.pop(module_name, None)

    def shutdown(self) -> None:
        """Disable updates during shutdown to prevent Tcl errors."""
        self._shutdown = True
        self._checkbox_vars.clear()

    def set_status_callback(
        self,
        callback: Callable[[str, ActualState], None]
    ) -> None:
        """Set a callback for status updates."""
        self._status_callback = callback

    def set_module_state_callback(
        self,
        callback: Callable[[str, ActualState, Optional[Any]], Any]
    ) -> None:
        """Set a callback for module state changes (for MainController compatibility)."""
        self._module_state_callback = callback

    async def __call__(self, change: StateChange) -> None:
        """Handle state change events."""
        if change.event == StateEvent.DESIRED_STATE_CHANGED:
            self._update_checkbox(change.module_name, change.new_value)

        elif change.event == StateEvent.ACTUAL_STATE_CHANGED:
            self._handle_actual_state_change(change)

    def _update_checkbox(
        self,
        module_name: str,
        desired_state: DesiredState
    ) -> None:
        """Update a checkbox to reflect desired state."""
        if self._shutdown:
            return

        var = self._checkbox_vars.get(module_name)
        if not var:
            return

        new_value = desired_state == DesiredState.ENABLED

        def do_update():
            try:
                current = var.get()
                if current != new_value:
                    var.set(new_value)
                    self.logger.debug(
                        "Updated checkbox for %s: %s -> %s",
                        module_name, current, new_value
                    )
            except tk.TclError:
                # Widget may have been destroyed
                pass

        if self._root:
            try:
                if self._root.winfo_exists():
                    self._root.after(0, do_update)
            except tk.TclError:
                # Root window already destroyed
                pass
        else:
            do_update()

    def _handle_actual_state_change(self, change: StateChange) -> None:
        """Handle actual state changes - sync checkbox with running state."""
        if self._shutdown:
            return

        module_name = change.module_name
        new_state: ActualState = change.new_value

        var = self._checkbox_vars.get(module_name)
        if var:
            # Sync checkbox with actual state
            # If module crashed/stopped unexpectedly, uncheck it
            # If module started successfully, ensure it's checked

            def do_update():
                try:
                    current = var.get()
                    if new_state in STOPPED_STATES and current:
                        # Module stopped but checkbox is checked - uncheck it
                        var.set(False)
                        self.logger.info(
                            "Unchecking %s (state: %s)",
                            module_name, new_state.value
                        )
                    elif new_state in RUNNING_STATES and not current:
                        # Module running but checkbox unchecked - check it
                        var.set(True)
                        self.logger.info(
                            "Checking %s (state: %s)",
                            module_name, new_state.value
                        )
                except tk.TclError:
                    pass

            if self._root:
                try:
                    if self._root.winfo_exists():
                        self._root.after(0, do_update)
                except tk.TclError:
                    # Root window already destroyed
                    pass
            else:
                do_update()

        # Call status callback if registered
        if self._status_callback:
            try:
                self._status_callback(module_name, new_state)
            except Exception as e:
                self.logger.error(
                    "Status callback error: %s", e, exc_info=True
                )

        # Call module state callback if registered (for MainController)
        if self._module_state_callback:
            try:
                # Convert ActualState to ModuleState for compatibility
                from rpi_logger.core.module_process import ModuleState
                module_state = self._convert_to_module_state(new_state)
                self._module_state_callback(module_name, module_state, None)
            except Exception as e:
                self.logger.error(
                    "Module state callback error: %s", e, exc_info=True
                )

    def _convert_to_module_state(self, actual_state: ActualState):
        """Convert ActualState to ModuleState for compatibility."""
        from rpi_logger.core.module_process import ModuleState

        mapping = {
            ActualState.STOPPED: ModuleState.STOPPED,
            ActualState.STARTING: ModuleState.STARTING,
            ActualState.INITIALIZING: ModuleState.INITIALIZING,
            ActualState.IDLE: ModuleState.IDLE,
            ActualState.RECORDING: ModuleState.RECORDING,
            ActualState.STOPPING: ModuleState.STOPPING,
            ActualState.ERROR: ModuleState.ERROR,
            ActualState.CRASHED: ModuleState.CRASHED,
        }
        return mapping.get(actual_state, ModuleState.STOPPED)

    def sync_all_checkboxes(self, desired_states: Dict[str, bool]) -> None:
        """Synchronize all checkboxes with desired states."""
        if self._shutdown:
            return

        for module_name, enabled in desired_states.items():
            var = self._checkbox_vars.get(module_name)
            if var:
                def do_update(v=var, e=enabled):
                    try:
                        v.set(e)
                    except tk.TclError:
                        pass

                if self._root:
                    try:
                        if self._root.winfo_exists():
                            self._root.after(0, do_update)
                    except tk.TclError:
                        pass
                else:
                    do_update()
