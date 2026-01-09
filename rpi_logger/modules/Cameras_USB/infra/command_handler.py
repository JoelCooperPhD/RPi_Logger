import asyncio
import json
import sys
from pathlib import Path
from typing import Callable, Awaitable, Optional
import logging

from ..core.actions import (
    Action,
    AssignDevice, UnassignCamera, SetAudioMode,
    StartStreaming, StopStreaming,
    StartRecording, StopRecording,
    ApplySettings, Shutdown,
)
from ..core.state import CameraSettings
from ..discovery import get_device_by_path, get_device_by_stable_id


logger = logging.getLogger(__name__)


class CommandHandler:
    def __init__(
        self,
        dispatch: Callable[[Action], Awaitable[None]],
        get_state: Callable[[], any],
    ):
        self._dispatch = dispatch
        self._get_state = get_state
        self._running = False
        self._reader_task: Optional[asyncio.Task] = None
        self._pending_commands: dict[str, asyncio.Future] = {}
        self._command_id = 0

    async def start(self) -> None:
        self._running = True
        self._reader_task = asyncio.create_task(self._read_commands())

    async def stop(self) -> None:
        self._running = False
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None

    async def _read_commands(self) -> None:
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        while self._running:
            try:
                line = await reader.readline()
                if not line:
                    break

                line_str = line.decode('utf-8').strip()
                if not line_str:
                    continue

                try:
                    cmd = json.loads(line_str)
                    await self._handle_command(cmd)
                except json.JSONDecodeError as e:
                    logger.warning("Invalid JSON command: %s", e)
                    self._send_response({"error": f"Invalid JSON: {e}"})

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Command read error: %s", e)

    async def _handle_command(self, cmd: dict) -> None:
        command = cmd.get("command", "")
        command_id = cmd.get("command_id", str(self._command_id))
        self._command_id += 1

        try:
            match command:
                case "assign_device":
                    await self._handle_assign_device(cmd, command_id)

                case "unassign_device":
                    await self._dispatch(UnassignCamera())
                    self._send_response({"status": "ok", "command_id": command_id})

                case "set_audio":
                    mode = cmd.get("mode", "auto")
                    await self._dispatch(SetAudioMode(mode))
                    self._send_response({"status": "ok", "command_id": command_id})

                case "start_streaming":
                    await self._dispatch(StartStreaming())
                    self._send_response({"status": "ok", "command_id": command_id})

                case "stop_streaming":
                    await self._dispatch(StopStreaming())
                    self._send_response({"status": "ok", "command_id": command_id})

                case "start_recording":
                    session_dir = Path(cmd.get("session_dir", "/tmp"))
                    trial = cmd.get("trial_number", 1)
                    await self._dispatch(StartRecording(session_dir, trial))
                    self._send_response({"status": "ok", "command_id": command_id})

                case "stop_recording":
                    await self._dispatch(StopRecording())
                    self._send_response({"status": "ok", "command_id": command_id})

                case "apply_settings":
                    settings_dict = cmd.get("settings", {})
                    settings = CameraSettings(
                        resolution=tuple(settings_dict.get("resolution", [640, 480])),
                        frame_rate=settings_dict.get("frame_rate", 30),
                        preview_divisor=settings_dict.get("preview_divisor", 4),
                        preview_scale=settings_dict.get("preview_scale", 0.25),
                        audio_mode=settings_dict.get("audio_mode", "auto"),
                        sample_rate=settings_dict.get("sample_rate", 48000),
                    )
                    await self._dispatch(ApplySettings(settings))
                    self._send_response({"status": "ok", "command_id": command_id})

                case "get_state":
                    state = self._get_state()
                    self._send_response({
                        "status": "ok",
                        "command_id": command_id,
                        "state": self._serialize_state(state),
                    })

                case "get_capabilities":
                    state = self._get_state()
                    caps = state.camera.capabilities
                    self._send_response({
                        "status": "ok",
                        "command_id": command_id,
                        "capabilities": self._serialize_capabilities(caps) if caps else None,
                    })

                case "shutdown":
                    await self._dispatch(Shutdown())
                    self._send_response({"status": "ok", "command_id": command_id})
                    self._running = False

                case _:
                    self._send_response({
                        "error": f"Unknown command: {command}",
                        "command_id": command_id,
                    })

        except Exception as e:
            logger.error("Command error: %s", e)
            self._send_response({
                "error": str(e),
                "command_id": command_id,
            })

    async def _handle_assign_device(self, cmd: dict, command_id: str) -> None:
        device_path = cmd.get("device_path")
        stable_id = cmd.get("stable_id")

        device = None
        if device_path:
            device = await get_device_by_path(device_path)
        elif stable_id:
            device = await get_device_by_stable_id(stable_id)

        if not device:
            self._send_response({
                "error": "Device not found",
                "command_id": command_id,
            })
            return

        await self._dispatch(AssignDevice(
            dev_path=device.dev_path,
            stable_id=device.stable_id,
            vid_pid=device.vid_pid,
            display_name=device.display_name,
            sysfs_path=device.sysfs_path,
            bus_path=device.bus_path,
        ))

        self._send_response({
            "status": "ok",
            "command_id": command_id,
            "device": {
                "dev_path": device.dev_path,
                "stable_id": device.stable_id,
                "vid_pid": device.vid_pid,
                "display_name": device.display_name,
            },
        })

    def _send_response(self, response: dict) -> None:
        try:
            line = json.dumps(response) + "\n"
            sys.stdout.write(line)
            sys.stdout.flush()
        except Exception as e:
            logger.error("Response send error: %s", e)

    def _serialize_state(self, state) -> dict:
        return {
            "camera_phase": state.camera.phase.name,
            "audio_phase": state.audio.phase.name,
            "recording_phase": state.recording_phase.name,
            "device_id": state.camera.device_info.stable_id if state.camera.device_info else None,
            "is_known": state.camera.is_known,
            "probing_progress": state.camera.probing_progress,
            "error": state.camera.error_message,
        }

    def _serialize_capabilities(self, caps) -> dict:
        return {
            "camera_id": caps.camera_id,
            "modes": list(caps.modes),
            "default_resolution": list(caps.default_resolution),
            "default_fps": caps.default_fps,
        }


async def send_status(status_type: str, payload: dict) -> None:
    msg = {
        "event": status_type,
        **payload,
    }
    try:
        line = json.dumps(msg) + "\n"
        sys.stdout.write(line)
        sys.stdout.flush()
    except Exception as e:
        logger.error("Status send error: %s", e)
