
import datetime
import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("CommandProtocol")


class CommandMessage:

    @staticmethod
    def create(command: str, **kwargs) -> str:
        message = {
            "command": command,
            "timestamp": datetime.datetime.now().isoformat(),
        }
        message.update(kwargs)
        return json.dumps(message) + "\n"

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
    def send(status: str, data: Optional[Dict[str, Any]] = None) -> None:
        import sys
        message = {
            "type": "status",
            "status": status,
            "timestamp": datetime.datetime.now().isoformat(),
            "data": data or {}
        }
        output = StatusMessage.output_stream if StatusMessage.output_stream else sys.stdout
        print(json.dumps(message), file=output, flush=True)

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
