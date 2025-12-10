"""VOG device handler for serial communication with protocol abstraction.

Implements self-healing circuit breaker via ReconnectingMixin - instead of
permanently exiting after N consecutive errors, the handler will attempt
reconnection with exponential backoff.
"""

import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, Callable

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.core.commands import StatusMessage
from rpi_logger.core.connection import ReconnectingMixin, ReconnectConfig
from .transports import BaseTransport

from .protocols import BaseVOGProtocol, VOGDataPacket, VOGResponse
from .protocols.base_protocol import ResponseType
from .constants import COMMAND_DELAY
from .data_logger import VOGDataLogger


class VOGHandler(ReconnectingMixin):
    """Per-device handler for VOG serial communication.

    Uses protocol abstraction to support both sVOG (wired) and wVOG (wireless) devices.
    Protocol is provided by the runtime based on device type from main logger.

    Inherits ReconnectingMixin to provide self-healing circuit breaker behavior.
    Instead of permanently exiting after consecutive errors, the handler will
    attempt to reconnect with exponential backoff.
    """

    def __init__(
        self,
        device: BaseTransport,
        port: str,
        output_dir: Path,
        system: Optional[Any] = None,
        protocol: BaseVOGProtocol = None
    ):
        if protocol is None:
            raise ValueError("Protocol must be provided")

        self.device = device
        self.port = port
        self._output_dir = output_dir
        self.system = system
        self.protocol = protocol
        self._read_task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._running = False
        self._data_callback: Optional[Callable[[str, str, Dict[str, Any]], None]] = None

        # Device state
        self._config: Dict[str, Any] = {}
        self._battery_percent: int = 0
        self._config_callback: Optional[Callable[[Dict[str, Any]], None]] = None

        self.logger = get_module_logger(f"VOGHandler[{self.protocol.device_type}]")

        # Circuit breaker error tracking (used by ReconnectingMixin)
        self._consecutive_errors = 0

        # Initialize reconnection mixin for self-healing circuit breaker
        self._init_reconnect(
            device_id=port,
            config=ReconnectConfig.default(),
        )

        # Data logger for CSV output
        self._data_logger = VOGDataLogger(
            output_dir=self._output_dir,
            port=port,
            protocol=self.protocol,
            event_callback=self._on_data_logged,
        )

    @property
    def output_dir(self) -> Path:
        """Return the current output directory."""
        return self._output_dir

    @output_dir.setter
    def output_dir(self, value: Path) -> None:
        """Update output directory for both handler and data logger."""
        self._output_dir = value
        self._data_logger.output_dir = value

    @property
    def device_type(self) -> str:
        """Return device type identifier (legacy string format)."""
        return self.protocol.device_type

    @property
    def supports_dual_lens(self) -> bool:
        """Return True if device supports dual lens control."""
        return self.protocol.supports_dual_lens

    @property
    def supports_battery(self) -> bool:
        """Return True if device reports battery status."""
        return self.protocol.supports_battery

    def get_config(self) -> Dict[str, Any]:
        """Return a copy of the current device configuration.

        Returns:
            Dict containing configuration values received from device.
        """
        return dict(self._config)

    def set_data_callback(self, callback: Callable[[str, str, Dict[str, Any]], None]):
        """Set callback for data events."""
        self._data_callback = callback

    def set_config_callback(self, callback: Callable[[Dict[str, Any]], None]):
        """Set callback for config updates.

        The callback is invoked whenever a CONFIG response is received from the device.
        This allows the config window to receive real-time updates without polling.
        """
        self._config_callback = callback

    def clear_config_callback(self):
        """Clear the config callback (e.g., when config window closes)."""
        self._config_callback = None

    async def start(self):
        """Start the async read loop."""
        if self._running:
            self.logger.debug("start() called but already running for %s", self.port)
            return

        self._running = True
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError as e:
            self.logger.error("No running event loop! Cannot start read loop: %s", e)
            self._running = False
            return

        self._loop = loop

        try:
            self._read_task = loop.create_task(self._read_loop())
        except Exception as e:
            self.logger.error("Failed to create read loop task: %s", e, exc_info=True)
            self._running = False
            return

        # Give the task a chance to start
        await asyncio.sleep(0)
        self.logger.info("Started VOG handler (%s) for %s", self.device_type, self.port)

    async def stop(self):
        """Stop the async read loop."""
        if not self._running and not self._read_task:
            return

        self._running = False

        task = self._read_task
        self._read_task = None

        if task:
            origin_loop = self._loop
            try:
                current_loop = asyncio.get_running_loop()
            except RuntimeError:
                current_loop = None

            if origin_loop and origin_loop is not current_loop:
                if origin_loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(
                        self._cancel_read_task(task), origin_loop
                    )
                    try:
                        await asyncio.wrap_future(future)
                    except RuntimeError as exc:
                        self.logger.warning(
                            "Failed to await read loop task for %s: %s",
                            self.port, exc
                        )
                else:
                    task.cancel()
            else:
                await self._cancel_read_task(task)

        self._loop = None
        self.logger.info("Stopped VOG handler for %s", self.port)

    async def _cancel_read_task(self, task: asyncio.Task):
        """Cancel the read task gracefully."""
        try:
            task.cancel()
            await task
        except asyncio.CancelledError:
            pass

    async def send_command(self, command: str, value: Optional[str] = None) -> bool:
        """Send a command to the VOG device.

        Args:
            command: Command key (e.g., 'exp_start', 'get_config')
            value: Optional value for set commands

        Returns:
            True if command was sent successfully
        """
        if not self.protocol.has_command(command):
            self.logger.warning("Unknown %s command: %s", self.device_type, command)
            return False

        data = self.protocol.format_command(command, value)

        if not data:
            self.logger.warning("Failed to format command: %s", command)
            return False

        self.logger.debug("Sending to %s: %r", self.port, data)
        success = await self.device.write(data)

        if success:
            self.logger.debug("Command sent to %s: %s", self.port, command)
            # Small delay to let firmware process the command
            await asyncio.sleep(COMMAND_DELAY)
        else:
            self.logger.error("Failed to send command to %s: %s", self.port, command)

        return success

    async def initialize_device(self) -> bool:
        """Initialize the VOG device."""
        self.logger.debug("Initializing %s device on %s", self.device_type.upper(), self.port)
        return True

    async def start_experiment(self) -> bool:
        """Send experiment start command.

        For wVOG: sends exp>1 to initialize experiment.
        For sVOG: sends do_expStart.

        Note: This only initializes the experiment. To start cycling/trial,
        call start_trial() separately. Trial number is managed by VOGSystem.
        """
        self._data_logger.start_recording()
        self.logger.info("Starting experiment on %s", self.port)

        return await self.send_command('exp_start')

    async def stop_experiment(self) -> bool:
        """Send experiment stop command.

        For wVOG: sends exp>0 to close experiment.
        For sVOG: sends do_expStop.

        Note: This only stops the experiment. To stop the trial/cycling first,
        call stop_trial() separately before this.
        """
        self.logger.info("Stopping experiment on %s", self.port)

        self._data_logger.stop_recording()
        return await self.send_command('exp_stop')

    async def start_trial(self) -> bool:
        """Send trial start command.

        Note: Trial number is managed by VOGSystem.active_trial_number,
        not tracked in the handler.
        """
        self.logger.info("Starting trial on %s", self.port)
        return await self.send_command('trial_start')

    async def stop_trial(self) -> bool:
        """Send trial stop command."""
        self.logger.info("Stopping trial on %s", self.port)
        return await self.send_command('trial_stop')

    async def peek_open(self, lens: str = 'x') -> bool:
        """Send peek/lens open command.

        Args:
            lens: 'a', 'b', or 'x' (both) - only used for wVOG
        """
        if self.supports_dual_lens:
            return await self.send_command(f'lens_open_{lens.lower()}')
        return await self.send_command('peek_open')

    async def peek_close(self, lens: str = 'x') -> bool:
        """Send peek/lens close command.

        Args:
            lens: 'a', 'b', or 'x' (both) - only used for wVOG
        """
        if self.supports_dual_lens:
            return await self.send_command(f'lens_close_{lens.lower()}')
        return await self.send_command('peek_close')

    async def get_device_config(self) -> Dict[str, Any]:
        """Request configuration from device.

        For sVOG: Sends individual get commands rapidly (no delay between commands,
        matching RS_Logger behavior).
        For wVOG: Sends single get_config command which returns all values.
        """
        config_commands = self.protocol.get_config_commands()
        self.logger.debug("Requesting configuration from %s", self.port)

        # Use protocol's config commands (polymorphic - handles sVOG vs wVOG)
        for cmd in config_commands:
            await self.send_command(cmd)
            # No delay - RS_Logger sends commands in rapid succession

        return self._config

    async def set_config_value(self, param: str, value: str) -> bool:
        """Set a configuration value on the device.

        Args:
            param: Parameter name
            value: Value to set

        Returns:
            True if command was sent successfully
        """
        # Use protocol's set config formatting (polymorphic - handles sVOG vs wVOG)
        command, cmd_value = self.protocol.format_set_config(param, value)
        if command is None:
            self.logger.warning("Unknown config parameter: %s", param)
            return False
        return await self.send_command(command, cmd_value)

    async def _read_loop(self):
        """Main async read loop for incoming data.

        Implements self-healing circuit breaker - instead of permanently exiting
        after N consecutive errors, attempts reconnection with exponential backoff.
        """
        self.logger.debug("Read loop started for %s", self.port)
        self._consecutive_errors = 0

        while self._running:
            # Check connection status - attempt reconnect if disconnected
            if not self.device.is_connected:
                self.logger.warning("VOG device %s disconnected, attempting reconnect", self.port)
                should_continue = await self._on_circuit_breaker_triggered()
                if not should_continue:
                    self.logger.error("Reconnection failed for %s - exiting read loop", self.port)
                    break
                continue

            try:
                line = await self.device.read_line()

                if line:
                    # Reset error counter on successful read
                    self._consecutive_errors = 0
                    self.logger.debug("Read line from %s: %r", self.port, line)
                    await self._process_response(line)

                await asyncio.sleep(0.001)  # 1ms for responsiveness

            except asyncio.CancelledError:
                self.logger.debug("Read loop cancelled for %s", self.port)
                break
            except Exception as e:
                self._consecutive_errors += 1
                config = self._reconnect_config
                backoff = min(
                    config.error_backoff * (2 ** (self._consecutive_errors - 1)),
                    config.max_error_backoff
                )
                self.logger.error(
                    "Error in VOG read loop for %s (%d/%d): %s",
                    self.port,
                    self._consecutive_errors,
                    config.max_consecutive_errors,
                    e
                )

                # Self-healing circuit breaker: attempt reconnection instead of hard exit
                if self._consecutive_errors >= config.max_consecutive_errors:
                    self.logger.warning(
                        "Circuit breaker triggered for %s - attempting reconnection",
                        self.port
                    )
                    should_continue = await self._on_circuit_breaker_triggered()
                    if not should_continue:
                        self.logger.error("Reconnection failed for %s - exiting read loop", self.port)
                        break
                    # Reconnected successfully, continue loop
                    continue

                await asyncio.sleep(backoff)

        self.logger.debug(
            "Read loop ended for %s (running=%s, connected=%s, errors=%d, reconnect_state=%s)",
            self.port,
            self._running,
            self.device.is_connected if self.device else False,
            self._consecutive_errors,
            self._reconnect_state.value if hasattr(self, '_reconnect_state') else 'N/A'
        )

    async def _attempt_reconnect(self) -> bool:
        """Attempt to reconnect the transport.

        This is called by ReconnectingMixin when circuit breaker triggers.
        Disconnects the transport and attempts to reconnect.

        Returns:
            True if reconnection succeeded, False otherwise
        """
        try:
            # First disconnect cleanly
            if self.device:
                await self.device.disconnect()

            # Brief delay to let the OS release the port
            await asyncio.sleep(0.2)

            # Attempt to reconnect
            if self.device:
                success = await self.device.connect()
                if success:
                    self.logger.info("VOG transport reconnected for %s", self.port)
                    return True
                else:
                    self.logger.warning("VOG transport reconnect failed for %s", self.port)
                    return False

            return False

        except Exception as e:
            self.logger.error("Error during VOG reconnect attempt for %s: %s", self.port, e)
            return False

    async def _process_response(self, response: str):
        """Process a response line from the device."""
        self.logger.debug("Response from %s: %s", self.port, repr(response))

        try:
            parsed = self.protocol.parse_response(response)

            if parsed is None:
                self.logger.debug("Unrecognized response: %s", response)
                return

            data = {
                'keyword': parsed.keyword,
                'value': parsed.value,
                'raw': parsed.raw,
                'event': parsed.response_type.value,
            }
            data.update(parsed.data)

            # Process by response type
            if parsed.response_type == ResponseType.VERSION:
                self._config['deviceVer'] = parsed.value

            elif parsed.response_type == ResponseType.CONFIG:
                # Use protocol's config update method (polymorphic)
                self.protocol.update_config_from_response(parsed, self._config)
                self.logger.debug("Config updated: %s", self._config)
                # Notify config callback if registered
                if self._config_callback:
                    try:
                        self._config_callback(dict(self._config))
                    except Exception as e:
                        self.logger.error("Error in config callback: %s", e)

            elif parsed.response_type == ResponseType.BATTERY:
                self._battery_percent = parsed.data.get('percent', 0)
                self._config['battery'] = self._battery_percent

            elif parsed.response_type == ResponseType.STIMULUS:
                data['state'] = parsed.data.get('state', 0)

            elif parsed.response_type == ResponseType.DATA:
                await self._process_data_response(parsed.value, data)

            # Dispatch event
            await self._dispatch_data_event(parsed.response_type.value, data)

            # Send status message if GUI commands enabled
            if self.system and getattr(self.system, 'enable_gui_commands', False):
                payload = {'port': self.port, 'device_type': self.device_type}
                payload.update(data)
                StatusMessage.send('vog_event', payload)

        except Exception as e:
            self.logger.error("Error processing response from %s: %s", self.port, e)

    async def _process_data_response(self, value: str, data: Dict[str, Any]):
        """Process a data response and log to CSV."""
        # Skip empty values (e.g., from 'end' marker)
        if not value or not value.strip():
            return

        port_clean = self.port.lstrip('/').replace('/', '_').replace('\\', '_')
        device_id = f"{self.device_type.upper()}_{port_clean}"

        packet = self.protocol.parse_data_response(value, device_id)

        if packet is None:
            self.logger.warning("Could not parse data response: %s", value)
            return

        # Update data dict with parsed values
        data['trial_number'] = packet.trial_number
        data['shutter_open'] = packet.shutter_open
        data['shutter_closed'] = packet.shutter_closed

        # Add device-specific extended data (polymorphic)
        data.update(self.protocol.get_extended_packet_data(packet))

        # Log to CSV via data logger
        trial_number = self._determine_trial_number(packet)
        label = self._get_trial_label(trial_number)
        await self._data_logger.log_trial_data(packet, trial_number, label)

    def _get_trial_label(self, trial_number: int) -> str:
        """Get trial label from system or use trial number."""
        if self.system and hasattr(self.system, 'trial_label') and self.system.trial_label:
            return self.system.trial_label
        return str(trial_number)

    async def _on_data_logged(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Callback from data logger when trial is logged."""
        await self._dispatch_data_event(event_type, payload)

    async def _dispatch_data_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Dispatch data event to callback."""
        self.logger.debug("Dispatch event: type=%s data=%s", event_type, data)
        if not self._data_callback:
            return

        try:
            if asyncio.iscoroutinefunction(self._data_callback):
                await self._data_callback(self.port, event_type, data)
            else:
                self._data_callback(self.port, event_type, data)
        except Exception as exc:
            self.logger.error("Error in data callback for %s: %s", self.port, exc)

    def _determine_trial_number(self, packet: VOGDataPacket) -> int:
        """Determine trial number from system or packet data.

        Priority order:
        1. VOGSystem.active_trial_number (primary source when running with system)
        2. VMC model.trial_number (when running in VMC context)
        3. packet.trial_number (device-reported, fallback for standalone)

        Returns at least 1 to ensure valid trial numbers.
        """
        candidate = 0

        # Try system's active_trial_number first
        if self.system is not None:
            candidate = getattr(self.system, "active_trial_number", 0) or 0

            # Fall back to VMC model if available
            if not candidate and hasattr(self.system, "model"):
                model = getattr(self.system, "model", None)
                if model:
                    candidate = getattr(model, "trial_number", 0) or 0

        # Final fallback: use packet's trial number (device-reported)
        if not candidate:
            candidate = packet.trial_number or 0

        return candidate if candidate > 0 else 1
