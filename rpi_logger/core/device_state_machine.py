"""
Device State Machine - Manages device connection and window visibility as a unified state.

A device has one of two states:
- OFF: Disconnected, module not running, window not visible
- ON: Connected, module running, window visible

All UI controls (dot, Connect/Disconnect button, Show/Hide button, window X)
manipulate this single state.
"""

from enum import Enum
from typing import Callable, Dict, Optional, Awaitable
from dataclasses import dataclass

from rpi_logger.core.logging_utils import get_module_logger


class DeviceState(Enum):
    """The two possible states for a device."""
    OFF = "off"  # Disconnected, no window
    ON = "on"    # Connected, window visible


@dataclass
class DeviceUIState:
    """UI representation of device state."""
    dot_active: bool      # Green dot on/off
    connect_text: str     # "Connect" or "Disconnect"
    show_text: str        # "Show" or "Hide"

    @classmethod
    def from_state(cls, state: DeviceState) -> 'DeviceUIState':
        """Create UI state from device state."""
        if state == DeviceState.ON:
            return cls(
                dot_active=True,
                connect_text="Disconnect",
                show_text="Hide"
            )
        else:
            return cls(
                dot_active=False,
                connect_text="Connect",
                show_text="Show"
            )


# Callback types
StateChangeCallback = Callable[[str, DeviceState], Awaitable[None]]
UIUpdateCallback = Callable[[str, DeviceUIState], None]


class DeviceStateMachine:
    """
    Manages the state of all devices.

    This is the single source of truth for device state. All UI elements
    and actions go through this state machine.

    State transitions:
    - OFF -> ON: connect_device() succeeds, module starts, window opens
    - ON -> OFF: disconnect requested OR window closed OR module crashes

    UI triggers that cause OFF -> ON:
    - Click green dot (when off)
    - Click "Connect" button
    - Click "Show" button

    UI triggers that cause ON -> OFF:
    - Click green dot (when on)
    - Click "Disconnect" button
    - Click "Hide" button
    - Click X on module window
    - Module crashes
    - Device physically disconnected
    """

    def __init__(self):
        self.logger = get_module_logger("DeviceStateMachine")

        # Current state for each device
        self._states: Dict[str, DeviceState] = {}

        # Callback to actually perform state change (connect/disconnect)
        self._state_change_callback: Optional[StateChangeCallback] = None

        # Callback to update UI
        self._ui_update_callback: Optional[UIUpdateCallback] = None

    def set_state_change_callback(self, callback: StateChangeCallback) -> None:
        """Set callback that performs the actual connect/disconnect."""
        self._state_change_callback = callback

    def set_ui_update_callback(self, callback: UIUpdateCallback) -> None:
        """Set callback that updates the UI."""
        self._ui_update_callback = callback

    def register_device(self, device_id: str, initial_state: DeviceState = DeviceState.OFF) -> None:
        """Register a device with initial state."""
        self._states[device_id] = initial_state
        self.logger.debug("Registered device %s with state %s", device_id, initial_state.value)

    def unregister_device(self, device_id: str) -> None:
        """Unregister a device."""
        self._states.pop(device_id, None)

    def get_state(self, device_id: str) -> DeviceState:
        """Get current state of a device."""
        return self._states.get(device_id, DeviceState.OFF)

    def get_ui_state(self, device_id: str) -> DeviceUIState:
        """Get UI representation of device state."""
        state = self.get_state(device_id)
        return DeviceUIState.from_state(state)

    # =========================================================================
    # State Transition Requests (from UI)
    # =========================================================================

    async def request_on(self, device_id: str) -> bool:
        """
        Request transition to ON state.

        Called when user clicks:
        - Green dot (when off)
        - Connect button
        - Show button

        Returns True if transition succeeded.
        """
        current = self.get_state(device_id)
        if current == DeviceState.ON:
            self.logger.debug("Device %s already ON", device_id)
            return True

        self.logger.info("Device %s: requesting ON", device_id)

        if self._state_change_callback:
            try:
                await self._state_change_callback(device_id, DeviceState.ON)
                # State change callback will call set_state() on success
                return self.get_state(device_id) == DeviceState.ON
            except Exception as e:
                self.logger.error("Failed to turn ON device %s: %s", device_id, e)
                return False

        return False

    async def request_off(self, device_id: str) -> bool:
        """
        Request transition to OFF state.

        Called when user clicks:
        - Green dot (when on)
        - Disconnect button
        - Hide button
        - X on module window

        Returns True if transition succeeded.
        """
        current = self.get_state(device_id)
        if current == DeviceState.OFF:
            self.logger.debug("Device %s already OFF", device_id)
            return True

        self.logger.info("Device %s: requesting OFF", device_id)

        if self._state_change_callback:
            try:
                await self._state_change_callback(device_id, DeviceState.OFF)
                # State change callback will call set_state() on success
                return self.get_state(device_id) == DeviceState.OFF
            except Exception as e:
                self.logger.error("Failed to turn OFF device %s: %s", device_id, e)
                return False

        return False

    async def request_toggle(self, device_id: str) -> bool:
        """Toggle device state (for dot click)."""
        current = self.get_state(device_id)
        if current == DeviceState.ON:
            return await self.request_off(device_id)
        else:
            return await self.request_on(device_id)

    # =========================================================================
    # State Updates (from system events)
    # =========================================================================

    def set_state(self, device_id: str, state: DeviceState) -> None:
        """
        Set device state directly.

        Called by LoggerSystem when:
        - Device connection succeeds/fails
        - Module starts/stops
        - Window opens/closes
        - Device physically disconnected
        - Module crashes
        """
        old_state = self._states.get(device_id, DeviceState.OFF)

        if old_state == state:
            return

        self._states[device_id] = state
        self.logger.info("Device %s: %s -> %s", device_id, old_state.value, state.value)

        # Update UI
        self._notify_ui(device_id)

    def set_on(self, device_id: str) -> None:
        """Convenience method to set state to ON."""
        self.set_state(device_id, DeviceState.ON)

    def set_off(self, device_id: str) -> None:
        """Convenience method to set state to OFF."""
        self.set_state(device_id, DeviceState.OFF)

    def _notify_ui(self, device_id: str) -> None:
        """Notify UI of state change."""
        if self._ui_update_callback:
            ui_state = self.get_ui_state(device_id)
            try:
                self._ui_update_callback(device_id, ui_state)
            except Exception as e:
                self.logger.error("UI update callback error: %s", e)


# Singleton instance
_device_state_machine: Optional[DeviceStateMachine] = None


def get_device_state_machine() -> DeviceStateMachine:
    """Get the singleton DeviceStateMachine instance."""
    global _device_state_machine
    if _device_state_machine is None:
        _device_state_machine = DeviceStateMachine()
    return _device_state_machine
