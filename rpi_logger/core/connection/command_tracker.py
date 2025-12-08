"""
Command Tracker - Reliable command delivery with correlation IDs.

This module provides request-response semantics for module commands.
Every command gets a unique correlation ID and waits for explicit
acknowledgment from the module.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional, TYPE_CHECKING

from rpi_logger.core.logging_utils import get_module_logger

if TYPE_CHECKING:
    from rpi_logger.core.module_process import ModuleProcess

logger = get_module_logger("CommandTracker")


class CommandStatus(Enum):
    """Status of a tracked command."""
    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class CommandResult:
    """Result of a command execution."""
    success: bool
    status: CommandStatus
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    duration_ms: float = 0.0


@dataclass
class PendingCommand:
    """Tracks a command awaiting acknowledgment."""
    command_id: str
    command_type: str
    device_id: Optional[str]
    sent_at: float
    timeout: float
    future: asyncio.Future = field(default_factory=lambda: asyncio.get_event_loop().create_future())

    def is_expired(self) -> bool:
        """Check if this command has exceeded its timeout."""
        return (time.time() - self.sent_at) > self.timeout

    def elapsed_ms(self) -> float:
        """Get elapsed time since command was sent."""
        return (time.time() - self.sent_at) * 1000


class CommandTracker:
    """
    Tracks commands sent to modules and matches them with responses.

    This provides reliable command delivery by:
    1. Assigning unique correlation IDs to commands
    2. Tracking pending commands
    3. Matching responses to their originating commands
    4. Handling timeouts for unacknowledged commands

    Usage:
        tracker = CommandTracker()

        # Send command and wait for ack
        result = await tracker.send_and_wait(
            process=module_process,
            command_type="assign_device",
            command_json=command_json,
            device_id="ACM0",
            timeout=5.0,
        )

        if result.success:
            print("Device connected!")
        else:
            print(f"Failed: {result.error}")
    """

    def __init__(self):
        self._pending: Dict[str, PendingCommand] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        """Start the command tracker and cleanup task."""
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.debug("Command tracker started")

    async def stop(self) -> None:
        """Stop the command tracker."""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        # Cancel all pending commands
        async with self._lock:
            for pending in self._pending.values():
                if not pending.future.done():
                    pending.future.set_result(CommandResult(
                        success=False,
                        status=CommandStatus.FAILED,
                        error="Tracker stopped",
                    ))
            self._pending.clear()

        logger.debug("Command tracker stopped")

    def generate_command_id(self) -> str:
        """Generate a unique command ID."""
        return str(uuid.uuid4())[:8]

    async def send_and_wait(
        self,
        send_func: Callable[[str], Any],
        command_type: str,
        command_json: str,
        command_id: str,
        device_id: Optional[str] = None,
        timeout: float = 5.0,
    ) -> CommandResult:
        """
        Send a command and wait for acknowledgment.

        Args:
            send_func: Async function to send command (e.g., process.send_command)
            command_type: Type of command (e.g., "assign_device")
            command_json: Full JSON command string (should include command_id)
            command_id: The correlation ID embedded in the command
            device_id: Optional device ID for device-related commands
            timeout: Maximum time to wait for acknowledgment

        Returns:
            CommandResult with success/failure status
        """
        pending = PendingCommand(
            command_id=command_id,
            command_type=command_type,
            device_id=device_id,
            sent_at=time.time(),
            timeout=timeout,
        )

        async with self._lock:
            self._pending[command_id] = pending

        logger.debug(
            "Sending command %s (type=%s, device=%s, timeout=%.1fs)",
            command_id, command_type, device_id, timeout
        )

        try:
            # Send the command
            await send_func(command_json)

            # Wait for response
            result = await asyncio.wait_for(pending.future, timeout=timeout)
            result.duration_ms = pending.elapsed_ms()
            return result

        except asyncio.TimeoutError:
            logger.warning(
                "Command %s timed out after %.1fs (type=%s, device=%s)",
                command_id, timeout, command_type, device_id
            )
            return CommandResult(
                success=False,
                status=CommandStatus.TIMEOUT,
                error=f"Command timed out after {timeout}s",
                duration_ms=pending.elapsed_ms(),
            )
        except Exception as e:
            logger.error("Command %s failed: %s", command_id, e)
            return CommandResult(
                success=False,
                status=CommandStatus.FAILED,
                error=str(e),
                duration_ms=pending.elapsed_ms(),
            )
        finally:
            async with self._lock:
                self._pending.pop(command_id, None)

    def on_response(
        self,
        command_id: str,
        success: bool,
        data: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> bool:
        """
        Handle a response from a module.

        This should be called when the module sends an acknowledgment
        (e.g., device_ready, device_error, command_ack).

        Args:
            command_id: The correlation ID from the response
            success: Whether the command succeeded
            data: Optional response data
            error: Optional error message

        Returns:
            True if response matched a pending command
        """
        pending = self._pending.get(command_id)
        if not pending:
            logger.debug("No pending command for response: %s", command_id)
            return False

        if pending.future.done():
            logger.debug("Command %s already resolved", command_id)
            return False

        result = CommandResult(
            success=success,
            status=CommandStatus.ACKNOWLEDGED if success else CommandStatus.FAILED,
            data=data,
            error=error,
        )

        pending.future.set_result(result)

        logger.debug(
            "Command %s resolved: success=%s, elapsed=%.1fms",
            command_id, success, pending.elapsed_ms()
        )

        return True

    def on_device_ready(self, device_id: str, data: Optional[Dict[str, Any]] = None) -> bool:
        """
        Handle device_ready status from module.

        Finds pending assign_device command for this device and resolves it.
        """
        # Find pending command for this device
        for cmd_id, pending in list(self._pending.items()):
            if pending.device_id == device_id and pending.command_type == "assign_device":
                return self.on_response(cmd_id, success=True, data=data)

        logger.debug("No pending assign_device for device_ready: %s", device_id)
        return False

    def on_device_error(
        self,
        device_id: str,
        error: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Handle device_error status from module.

        Finds pending assign_device command for this device and fails it.
        """
        for cmd_id, pending in list(self._pending.items()):
            if pending.device_id == device_id and pending.command_type == "assign_device":
                return self.on_response(cmd_id, success=False, error=error, data=data)

        logger.debug("No pending assign_device for device_error: %s", device_id)
        return False

    def get_pending_count(self) -> int:
        """Get number of pending commands."""
        return len(self._pending)

    def get_pending_for_device(self, device_id: str) -> Optional[PendingCommand]:
        """Get pending command for a specific device."""
        for pending in self._pending.values():
            if pending.device_id == device_id:
                return pending
        return None

    async def _cleanup_loop(self) -> None:
        """Background task to clean up expired commands."""
        while self._running:
            try:
                await asyncio.sleep(1.0)

                async with self._lock:
                    expired = [
                        cmd_id for cmd_id, pending in self._pending.items()
                        if pending.is_expired() and not pending.future.done()
                    ]

                    for cmd_id in expired:
                        pending = self._pending.get(cmd_id)
                        if pending and not pending.future.done():
                            pending.future.set_result(CommandResult(
                                success=False,
                                status=CommandStatus.TIMEOUT,
                                error="Command expired",
                                duration_ms=pending.elapsed_ms(),
                            ))
                            logger.debug("Expired command: %s", cmd_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Cleanup loop error: %s", e)
