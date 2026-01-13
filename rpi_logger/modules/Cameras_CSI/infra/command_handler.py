import asyncio
import json
import sys
from pathlib import Path
from typing import Callable, Awaitable, TextIO

from ..core import (
    Action, AssignCamera, UnassignCamera,
    StartRecording, StopRecording, Shutdown,
    Store,
)


class CommandHandler:
    def __init__(
        self,
        store: Store,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
    ):
        self._store = store
        self._stdin = stdin or sys.stdin
        self._stdout = stdout or sys.stdout
        self._running = False
        self._pending_replies: dict[str, str] = {}

    async def start(self) -> None:
        self._running = True
        await self._send_status("ready", {})

    async def stop(self) -> None:
        self._running = False

    async def run(self) -> None:
        self._running = True
        await self._send_status("ready", {})

        while self._running:
            try:
                line = await asyncio.to_thread(self._stdin.readline)
                if not line:
                    break
                line = line.strip()
                if line:
                    await self._handle_line(line)
            except Exception as e:
                await self._send_status("error", {"message": str(e)})

    async def _handle_line(self, line: str) -> None:
        try:
            cmd = json.loads(line)
        except json.JSONDecodeError as e:
            await self._send_status("error", {"message": f"Invalid JSON: {e}"})
            return

        command = cmd.get("command")
        command_id = cmd.get("command_id", "")

        if command_id:
            self._pending_replies[command] = command_id

        try:
            await self._dispatch_command(cmd)
        except Exception as e:
            await self._send_status("error", {
                "message": str(e),
            }, in_reply_to=command_id)

    async def _dispatch_command(self, cmd: dict) -> None:
        command = cmd.get("command")

        match command:
            case "assign_device":
                await self._handle_assign_device(cmd)
            case "unassign_device":
                await self._handle_unassign_device(cmd)
            case "start_recording":
                await self._handle_start_recording(cmd)
            case "stop_recording":
                await self._handle_stop_recording(cmd)
            case "start_session":
                await self._handle_start_session(cmd)
            case "stop_session":
                await self._handle_stop_session(cmd)
            case "shutdown":
                await self._handle_shutdown(cmd)
            case _:
                await self._send_status("error", {
                    "message": f"Unknown command: {command}"
                }, in_reply_to=cmd.get("command_id"))

    async def _handle_assign_device(self, cmd: dict) -> None:
        command_id = cmd.get("command_id", "")
        device_id = cmd.get("device_id", "")

        camera_index = 0
        if "camera_index" in cmd:
            camera_index = cmd["camera_index"]
        elif device_id.startswith("picam:"):
            try:
                camera_index = int(device_id.split(":")[1])
            except (ValueError, IndexError):
                camera_index = 0

        await self._store.dispatch(AssignCamera(camera_index))

    async def _handle_unassign_device(self, cmd: dict) -> None:
        await self._store.dispatch(UnassignCamera())

    async def _handle_start_recording(self, cmd: dict) -> None:
        session_dir = Path(cmd.get("session_dir", "."))
        trial_number = cmd.get("trial_number", 1)
        await self._store.dispatch(StartRecording(session_dir, trial_number))

    async def _handle_stop_recording(self, cmd: dict) -> None:
        await self._store.dispatch(StopRecording())

    async def _handle_start_session(self, cmd: dict) -> None:
        pass

    async def _handle_stop_session(self, cmd: dict) -> None:
        await self._store.dispatch(StopRecording())

    async def _handle_shutdown(self, cmd: dict) -> None:
        await self._store.dispatch(Shutdown())
        self._running = False

    async def _send_status(
        self,
        status_type: str,
        payload: dict,
        in_reply_to: str | None = None
    ) -> None:
        message = {
            "status": status_type,
            **payload,
        }
        if in_reply_to:
            message["in_reply_to"] = in_reply_to

        line = json.dumps(message) + "\n"
        await asyncio.to_thread(self._stdout.write, line)
        await asyncio.to_thread(self._stdout.flush)

    def send_status_sync(self, status_type: str, payload: dict) -> None:
        message = {
            "status": status_type,
            **payload,
        }
        line = json.dumps(message) + "\n"
        self._stdout.write(line)
        self._stdout.flush()
