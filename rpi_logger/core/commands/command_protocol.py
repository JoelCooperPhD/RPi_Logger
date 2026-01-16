
import datetime
import json
from typing import Any, Dict, Optional

from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger("CommandProtocol")


class CommandMessage:

    @staticmethod
    def create(command: str, command_id: Optional[str] = None, **kwargs) -> str:
        """
        Create a command message.

        Args:
            command: The command name
            command_id: Optional correlation ID for tracking acknowledgments
            **kwargs: Additional command parameters

        Returns:
            JSON-formatted command string with newline
        """
        message = {
            "command": command,
            "timestamp": datetime.datetime.now().isoformat(),
        }
        if command_id:
            message["command_id"] = command_id
        message.update(kwargs)
        return json.dumps(message) + "\n"

    @staticmethod
    def create_with_id(command: str, command_id: str, **kwargs) -> str:
        """
        Create a command message with a required correlation ID.

        This is used for commands that require acknowledgment.

        Args:
            command: The command name
            command_id: Correlation ID for tracking acknowledgments
            **kwargs: Additional command parameters

        Returns:
            JSON-formatted command string with newline
        """
        return CommandMessage.create(command, command_id=command_id, **kwargs)

    @staticmethod
    def parse(raw_json: str) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(raw_json.strip())

            if not isinstance(data, dict):
                logger.warning("Command is not a dict: %s", raw_json[:100])
                return None

            if "command" not in data:
                logger.warning("Command missing 'command' key: %s", raw_json[:100])
                return None

            return data

        except json.JSONDecodeError as e:
            logger.warning("Failed to parse JSON command: %s - %s", e, raw_json[:100])
            return None
        except Exception as e:
            logger.error("Unexpected error parsing command: %s - %s", e, raw_json[:100])
            return None

    @staticmethod
    def start_session(session_dir: str = None) -> str:
        kwargs = {}
        if session_dir:
            kwargs["session_dir"] = session_dir
        return CommandMessage.create("start_session", **kwargs)

    @staticmethod
    def stop_session() -> str:
        return CommandMessage.create("stop_session")

    @staticmethod
    def record(session_dir: str = None, trial_number: int = None, trial_label: str = None) -> str:
        kwargs = {}
        if session_dir:
            kwargs["session_dir"] = session_dir
        if trial_number is not None:
            kwargs["trial_number"] = trial_number
        if trial_label:
            kwargs["trial_label"] = trial_label
        return CommandMessage.create("record", **kwargs)

    @staticmethod
    def pause() -> str:
        return CommandMessage.create("pause")

    @staticmethod
    def start_recording(session_dir: str = None, trial_number: int = None, trial_label: str = None) -> str:
        return CommandMessage.record(session_dir, trial_number, trial_label)

    @staticmethod
    def stop_recording() -> str:
        return CommandMessage.pause()

    @staticmethod
    def take_snapshot() -> str:
        return CommandMessage.create("take_snapshot")

    @staticmethod
    def get_status() -> str:
        return CommandMessage.create("get_status")

    @staticmethod
    def get_geometry() -> str:
        return CommandMessage.create("get_geometry")

    @staticmethod
    def toggle_preview(camera_id: int = 0, enabled: bool = True) -> str:
        return CommandMessage.create("toggle_preview", camera_id=camera_id, enabled=enabled)

    @staticmethod
    def quit() -> str:
        return CommandMessage.create("quit")

    # =========================================================================
    # Device Assignment Commands (for centralized device discovery)
    # =========================================================================

    @staticmethod
    def assign_device(
        device_id: str,
        device_type: str,
        port: str,
        baudrate: int,
        session_dir: str = None,
        is_wireless: bool = False,
        is_network: bool = False,
        network_address: str = None,
        network_port: int = None,
        sounddevice_index: int = None,
        audio_channels: int = None,
        audio_sample_rate: float = None,
        # Camera device fields
        is_camera: bool = False,
        camera_type: str = None,
        camera_stable_id: str = None,
        camera_dev_path: str = None,
        camera_hw_model: str = None,
        camera_location: str = None,
        camera_index: int = None,
        display_name: str = None,
        # Camera audio sibling fields (for webcams with built-in microphones)
        camera_audio_index: int = None,
        camera_audio_channels: int = None,
        camera_audio_sample_rate: float = None,
        camera_audio_alsa_card: int = None,
        # Correlation ID for acknowledgment tracking
        command_id: str = None,
    ) -> str:
        """
        Assign a device to the module.

        Args:
            device_id: Unique device identifier (port for USB, node_id for wireless, hardware_id for network)
            device_type: Device type string (e.g., "sVOG", "wDRT_Wireless", "Pupil_Labs_Neon")
            port: Serial port path (dongle port for wireless devices, None for network)
            baudrate: Serial baudrate (0 for network devices)
            session_dir: Optional current session directory
            is_wireless: Whether this is a wireless device
            is_network: Whether this is a network device
            network_address: IP address for network devices
            network_port: API port for network devices (e.g., 8080)
            sounddevice_index: Index in sounddevice for audio devices
            audio_channels: Number of input channels for audio devices
            audio_sample_rate: Sample rate for audio devices
            is_camera: Whether this is a camera device
            camera_type: Camera type ("usb" or "picam")
            camera_stable_id: USB bus path or picam number
            camera_dev_path: /dev/video* path for USB cameras
            camera_hw_model: Hardware model
            camera_location: USB port or CSI connector
            display_name: Display name for the device
            camera_audio_index: sounddevice index for webcam's built-in microphone
            camera_audio_channels: Number of input channels for webcam mic
            camera_audio_sample_rate: Sample rate for webcam mic
            camera_audio_alsa_card: ALSA card number for webcam mic
            command_id: Optional correlation ID for tracking acknowledgment
        """
        kwargs = {
            "device_id": device_id,
            "device_type": device_type,
            "port": port,
            "baudrate": baudrate,
            "is_wireless": is_wireless,
            "is_network": is_network,
        }
        if session_dir:
            kwargs["session_dir"] = session_dir
        if network_address:
            kwargs["network_address"] = network_address
        if network_port is not None:
            kwargs["network_port"] = network_port
        if sounddevice_index is not None:
            kwargs["sounddevice_index"] = sounddevice_index
        if audio_channels is not None:
            kwargs["audio_channels"] = audio_channels
        if audio_sample_rate is not None:
            kwargs["audio_sample_rate"] = audio_sample_rate
        # Camera fields
        if is_camera:
            kwargs["is_camera"] = is_camera
        if camera_type:
            kwargs["camera_type"] = camera_type
        if camera_stable_id:
            kwargs["camera_stable_id"] = camera_stable_id
        if camera_dev_path:
            kwargs["camera_dev_path"] = camera_dev_path
        if camera_hw_model:
            kwargs["camera_hw_model"] = camera_hw_model
        if camera_location:
            kwargs["camera_location"] = camera_location
        if camera_index is not None:
            kwargs["camera_index"] = camera_index
        if display_name:
            kwargs["display_name"] = display_name
        # Camera audio sibling fields
        if camera_audio_index is not None:
            kwargs["camera_audio_index"] = camera_audio_index
        if camera_audio_channels is not None:
            kwargs["camera_audio_channels"] = camera_audio_channels
        if camera_audio_sample_rate is not None:
            kwargs["camera_audio_sample_rate"] = camera_audio_sample_rate
        if camera_audio_alsa_card is not None:
            kwargs["camera_audio_alsa_card"] = camera_audio_alsa_card
        return CommandMessage.create("assign_device", command_id=command_id, **kwargs)

    @staticmethod
    def unassign_device(device_id: str) -> str:
        """Remove a device from the module."""
        return CommandMessage.create("unassign_device", device_id=device_id)

    @staticmethod
    def unassign_all_devices() -> str:
        """Disconnect all devices from the module before shutdown.

        This ensures serial ports are properly released before the process
        is terminated. Should be sent before quit() during graceful shutdown.
        """
        return CommandMessage.create("unassign_all_devices")

    @staticmethod
    def show_window() -> str:
        """Show the module window."""
        return CommandMessage.create("show_window")

    @staticmethod
    def hide_window() -> str:
        """Hide the module window."""
        return CommandMessage.create("hide_window")

    # =========================================================================
    # XBee Wireless Communication (for proxying XBee data to modules)
    # =========================================================================

    @staticmethod
    def xbee_data(node_id: str, data: str) -> str:
        """
        Forward XBee data from main logger to module.

        Args:
            node_id: Source device node ID (e.g., "wDRT_01")
            data: Raw data string from the device
        """
        return CommandMessage.create("xbee_data", node_id=node_id, data=data)

    @staticmethod
    def xbee_send_result(node_id: str, success: bool) -> str:
        """
        Send result of XBee send operation back to module.

        Args:
            node_id: Target device node ID
            success: Whether the send was successful
        """
        return CommandMessage.create("xbee_send_result", node_id=node_id, success=success)

    # =========================================================================
    # Logging Control Commands
    # =========================================================================

    @staticmethod
    def set_log_level(level: str, target: str = "all") -> str:
        """
        Dynamically set log level for a module.

        Args:
            level: Log level name ("debug", "info", "warning", "error", "critical")
            target: Which handler(s) to affect:
                   - "console": stderr/stdout handler only
                   - "ui": forwarded logs for master UI display only
                   - "all": both console and UI handlers

        Note: File logging always stays at DEBUG for full capture.
        """
        return CommandMessage.create(
            "set_log_level",
            level=level.lower(),
            target=target,
        )


class StatusMessage:

    output_stream = None

    def __init__(self, raw_json: str):
        self.raw = raw_json.strip()
        self.data = None
        self.status_type = None
        self.timestamp = None
        self.payload = {}
        self.valid = False

        self._parse()

    @classmethod
    def configure(cls, output_stream) -> None:
        cls.output_stream = output_stream

    @staticmethod
    def send(status: str, data: Optional[Dict[str, Any]] = None, command_id: Optional[str] = None) -> None:
        """
        Send a status message to the parent process.

        Args:
            status: Status type (e.g., "device_ready", "error")
            data: Optional data payload
            command_id: Optional correlation ID to acknowledge a command
        """
        import sys
        message = {
            "type": "status",
            "status": status,
            "timestamp": datetime.datetime.now().isoformat(),
            "data": data or {}
        }
        if command_id:
            message["command_id"] = command_id
        output = StatusMessage.output_stream if StatusMessage.output_stream else sys.stdout
        print(json.dumps(message), file=output, flush=True)

    @staticmethod
    def send_ack(command_id: str, success: bool = True, data: Optional[Dict[str, Any]] = None) -> None:
        """
        Send a command acknowledgment.

        Args:
            command_id: The correlation ID of the command being acknowledged
            success: Whether the command succeeded
            data: Optional additional data
        """
        status = "command_ack" if success else "command_nack"
        payload = data or {}
        payload["success"] = success
        StatusMessage.send(status, payload, command_id=command_id)

    @staticmethod
    def send_with_timing(status: str, duration_ms: float, data: Optional[Dict[str, Any]] = None) -> None:
        payload = data or {}
        payload["duration_ms"] = round(duration_ms, 1)
        StatusMessage.send(status, payload)

    @staticmethod
    def send_phase_complete(phase_name: str, duration_ms: float, data: Optional[Dict[str, Any]] = None) -> None:
        payload = data or {}
        payload["phase"] = phase_name
        payload["duration_ms"] = round(duration_ms, 1)
        StatusMessage.send("phase_complete", payload)

    @staticmethod
    def send_xbee_data(node_id: str, data: str) -> None:
        """
        Request main logger to send data to XBee device.

        Args:
            node_id: Target device node ID (e.g., "wDRT_01")
            data: Data string to send
        """
        StatusMessage.send("xbee_send", {"node_id": node_id, "data": data})

    def _parse(self) -> None:
        try:
            self.data = json.loads(self.raw)

            if not isinstance(self.data, dict):
                logger.warning("Status message is not a dict: %s", self.raw)
                return

            if self.data.get("type") != "status":
                logger.debug("Non-status message: %s", self.data.get("type"))
                return

            self.status_type = self.data.get("status")
            self.timestamp = self.data.get("timestamp")
            self.payload = self.data.get("data", {})
            self.valid = True

        except json.JSONDecodeError as e:
            logger.warning("Failed to parse JSON status: %s - %s", e, self.raw)
        except Exception as e:
            logger.error("Unexpected error parsing status: %s - %s", e, self.raw)

    def is_valid(self) -> bool:
        return self.valid

    def get_status_type(self) -> Optional[str]:
        return self.status_type

    def get_payload(self) -> Dict[str, Any]:
        return self.payload

    def get_timestamp(self) -> Optional[str]:
        return self.timestamp

    def is_error(self) -> bool:
        return self.status_type == "error"

    def is_warning(self) -> bool:
        return self.status_type == "warning"

    def get_error_message(self) -> Optional[str]:
        if self.is_error():
            return self.payload.get("message")
        return None

    def get_command_id(self) -> Optional[str]:
        """Get the correlation ID if this is a command acknowledgment."""
        if self.data:
            return self.data.get("command_id")
        return None

    def is_acknowledgment(self) -> bool:
        """Check if this is a command acknowledgment."""
        return self.status_type in ("command_ack", "command_nack", "device_ready", "device_error")

    def __repr__(self) -> str:
        if self.valid:
            return f"StatusMessage(type={self.status_type}, payload={self.payload})"
        return f"StatusMessage(invalid: {self.raw[:50]}...)"


class StatusType:
    INITIALIZING = "initializing"
    INITIALIZED = "initialized"
    DISCOVERING = "discovering"
    DEVICE_DETECTED = "device_detected"
    RECORDING_STARTED = "recording_started"
    RECORDING_STOPPED = "recording_stopped"
    SNAPSHOT_TAKEN = "snapshot_taken"
    STATUS_REPORT = "status_report"
    PREVIEW_FRAME = "preview_frame"
    PREVIEW_TOGGLED = "preview_toggled"
    GEOMETRY_CHANGED = "geometry_changed"
    PHASE_COMPLETE = "phase_complete"
    SHUTDOWN_STARTED = "shutdown_started"
    CLEANUP_COMPLETE = "cleanup_complete"
    ERROR = "error"
    WARNING = "warning"
    QUITTING = "quitting"

    # Device assignment status (for centralized device discovery)
    DEVICE_ASSIGNED = "device_assigned"
    DEVICE_UNASSIGNED = "device_unassigned"
    DEVICE_ERROR = "device_error"

    # Window visibility status
    WINDOW_SHOWN = "window_shown"
    WINDOW_HIDDEN = "window_hidden"

    # XBee wireless communication status
    XBEE_SEND = "xbee_send"              # Module requests to send data via XBee
    XBEE_SEND_RESULT = "xbee_send_result"  # Result of XBee send operation

    # Command acknowledgment status
    COMMAND_ACK = "command_ack"          # Command succeeded
    COMMAND_NACK = "command_nack"        # Command failed

    # Health monitoring status
    HEARTBEAT = "heartbeat"              # Module heartbeat signal
    READY = "ready"                      # Module ready for commands

    # Device connection status (with correlation ID support)
    DEVICE_READY = "device_ready"        # Device successfully connected

    # Logging control status
    LOG_LEVEL_CHANGED = "log_level_changed"  # Module log level was changed
    LOG_MESSAGE = "log_message"              # Forwarded log message for master UI


if __name__ == "__main__":
    print("Testing command creation:")
    print(CommandMessage.start_session())
    print(CommandMessage.stop_session())
    print(CommandMessage.record())
    print(CommandMessage.pause())
    print(CommandMessage.get_status())
    print(CommandMessage.quit())

    print("\nTesting status parsing:")
    test_status = '{"type": "status", "status": "initialized", "timestamp": "2025-01-01T12:00:00", "data": {"cameras": 2}}'
    msg = StatusMessage(test_status)
    print(f"Valid: {msg.is_valid()}")
    print(f"Type: {msg.get_status_type()}")
    print(f"Payload: {msg.get_payload()}")

    error_status = '{"type": "status", "status": "error", "timestamp": "2025-01-01T12:00:00", "data": {"message": "Camera init failed"}}'
    err_msg = StatusMessage(error_status)
    print(f"\nError: {err_msg.is_error()}")
    print(f"Error message: {err_msg.get_error_message()}")
