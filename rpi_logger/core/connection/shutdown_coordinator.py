"""
Shutdown Coordinator - Reliable process shutdown with acknowledgment.

This module provides ACK-based shutdown semantics for module processes.
Instead of blindly waiting a fixed time after sending unassign commands,
it waits for explicit acknowledgment that resources are released.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, Optional, TYPE_CHECKING

from rpi_logger.core.logging_utils import get_module_logger

if TYPE_CHECKING:
    pass

logger = get_module_logger("ShutdownCoordinator")


class ShutdownPhase(Enum):
    """Current phase of the shutdown process."""
    IDLE = "idle"
    UNASSIGNING = "unassigning"
    WAITING_ACK = "waiting_ack"
    QUITTING = "quitting"
    TERMINATING = "terminating"
    KILLING = "killing"
    DRAINING = "draining"
    COMPLETE = "complete"


@dataclass
class ShutdownResult:
    """Result of a shutdown operation."""
    success: bool
    acknowledged: bool
    forced: bool
    duration_ms: float
    phase_reached: ShutdownPhase
    error: Optional[str] = None

    @property
    def was_graceful(self) -> bool:
        """Check if shutdown was graceful (ACK received, no force needed)."""
        return self.acknowledged and not self.forced


class ShutdownCoordinator:
    """
    Coordinates reliable process shutdown with acknowledgment.

    This replaces the blind `await asyncio.sleep(0.5)` pattern with
    a proper request-ACK protocol:

    1. Send unassign_all_devices with command_id
    2. Wait for device_unassigned status with matching command_id
    3. If timeout, escalate to SIGTERM
    4. If still not closed, escalate to SIGKILL
    5. Drain all pipes before cleanup

    Usage:
        coordinator = ShutdownCoordinator()
        result = await coordinator.shutdown_process(
            process=module_process,
            send_func=process.send_command,
            timeout=10.0,
        )
        if result.was_graceful:
            logger.info("Clean shutdown in %.1fms", result.duration_ms)
    """

    def __init__(self):
        self._pending_acks: Dict[str, asyncio.Event] = {}
        self._ack_data: Dict[str, Dict[str, Any]] = {}

    def generate_command_id(self) -> str:
        """Generate a unique command ID for shutdown tracking."""
        return f"shutdown-{uuid.uuid4().hex[:8]}"

    async def request_device_unassign(
        self,
        send_func: Callable[[str], Awaitable[None]],
        timeout: float = 3.0,
        instance_id: Optional[str] = None,
    ) -> tuple[bool, Optional[Dict[str, Any]]]:
        """
        Send unassign_all_devices and wait for acknowledgment.

        Args:
            send_func: Async function to send command JSON
            timeout: Maximum time to wait for ACK
            instance_id: Optional identifier for logging

        Returns:
            Tuple of (acknowledged: bool, ack_data: Optional[Dict])
        """
        from rpi_logger.core.commands import CommandMessage

        command_id = self.generate_command_id()
        ack_event = asyncio.Event()
        self._pending_acks[command_id] = ack_event

        log_prefix = f"[{instance_id}] " if instance_id else ""

        try:
            # Send command with correlation ID
            command_json = CommandMessage.create_with_id(
                "unassign_all_devices",
                command_id=command_id,
            )
            await send_func(command_json)

            # Wait for ACK
            try:
                await asyncio.wait_for(ack_event.wait(), timeout=timeout)
                ack_data = self._ack_data.get(command_id)
                logger.info(
                    "%sDevice unassign acknowledged (command_id=%s)",
                    log_prefix, command_id
                )
                return True, ack_data
            except asyncio.TimeoutError:
                logger.warning(
                    "%sDevice unassign not acknowledged after %.1fs (command_id=%s)",
                    log_prefix, timeout, command_id
                )
                return False, None

        finally:
            self._pending_acks.pop(command_id, None)
            self._ack_data.pop(command_id, None)

    def on_device_unassigned(
        self,
        command_id: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Handle device_unassigned status from module.

        This should be called when the module sends acknowledgment
        that it has released its device(s).

        Args:
            command_id: The correlation ID from the response
            data: Optional response data (e.g., port_released, device_id)

        Returns:
            True if response matched a pending unassign request
        """
        ack_event = self._pending_acks.get(command_id)
        if not ack_event:
            logger.debug("No pending unassign for command_id: %s", command_id)
            return False

        if data:
            self._ack_data[command_id] = data

        ack_event.set()
        return True

    async def drain_process_pipes(
        self,
        stdout: Optional[asyncio.StreamReader],
        stderr: Optional[asyncio.StreamReader],
        timeout: float = 1.0,
    ) -> None:
        """
        Drain remaining data from process pipes.

        This ensures no data is left in pipe buffers before termination,
        preventing resource leaks in reader tasks.

        Args:
            stdout: Process stdout stream
            stderr: Process stderr stream
            timeout: Maximum time to spend draining
        """
        async def drain_stream(stream: asyncio.StreamReader, name: str) -> int:
            """Drain a single stream, return bytes drained."""
            if stream is None:
                return 0

            total_drained = 0
            try:
                while True:
                    # Read in chunks without blocking indefinitely
                    try:
                        chunk = await asyncio.wait_for(
                            stream.read(4096),
                            timeout=0.1,
                        )
                        if not chunk:
                            break
                        total_drained += len(chunk)
                    except asyncio.TimeoutError:
                        # No more data available
                        break
            except Exception as e:
                logger.debug("Error draining %s: %s", name, e)

            return total_drained

        try:
            async with asyncio.timeout(timeout):
                stdout_bytes, stderr_bytes = await asyncio.gather(
                    drain_stream(stdout, "stdout"),
                    drain_stream(stderr, "stderr"),
                    return_exceptions=True,
                )

                # Log if we actually drained anything
                stdout_count = stdout_bytes if isinstance(stdout_bytes, int) else 0
                stderr_count = stderr_bytes if isinstance(stderr_bytes, int) else 0

                if stdout_count > 0 or stderr_count > 0:
                    logger.debug(
                        "Drained %d bytes from stdout, %d bytes from stderr",
                        stdout_count, stderr_count
                    )

        except asyncio.TimeoutError:
            logger.debug("Pipe drain timed out after %.1fs", timeout)

    async def shutdown_process(
        self,
        process: asyncio.subprocess.Process,
        send_func: Callable[[str], Awaitable[None]],
        instance_id: Optional[str] = None,
        unassign_timeout: float = 3.0,
        quit_timeout: float = 7.0,
        terminate_timeout: float = 2.0,
        drain_timeout: float = 1.0,
    ) -> ShutdownResult:
        """
        Perform a complete, reliable process shutdown.

        Shutdown phases:
        1. UNASSIGNING - Send unassign_all_devices, wait for ACK
        2. QUITTING - Send quit command, wait for graceful exit
        3. TERMINATING - Send SIGTERM if not exited
        4. KILLING - Send SIGKILL if still alive
        5. DRAINING - Drain remaining pipe data
        6. COMPLETE - Process fully stopped

        Args:
            process: The asyncio subprocess to shut down
            send_func: Async function to send commands to the process
            instance_id: Optional identifier for logging
            unassign_timeout: Time to wait for unassign ACK
            quit_timeout: Time to wait for graceful exit after quit
            terminate_timeout: Time to wait after SIGTERM
            drain_timeout: Time to spend draining pipes

        Returns:
            ShutdownResult with details about the shutdown
        """
        from rpi_logger.core.commands import CommandMessage

        start_time = time.perf_counter()
        log_prefix = f"[{instance_id}] " if instance_id else ""
        acknowledged = False
        forced = False
        phase = ShutdownPhase.IDLE
        error = None

        try:
            # Phase 1: Request device unassignment
            phase = ShutdownPhase.UNASSIGNING
            logger.info("%sPhase 1: Requesting device unassignment", log_prefix)

            try:
                acknowledged, ack_data = await self.request_device_unassign(
                    send_func=send_func,
                    timeout=unassign_timeout,
                    instance_id=instance_id,
                )
                if acknowledged:
                    port_released = ack_data.get("port_released", False) if ack_data else False
                    logger.info(
                        "%sDevice unassignment confirmed (port_released=%s)",
                        log_prefix, port_released
                    )
                else:
                    logger.warning("%sDevice unassign not acknowledged, continuing shutdown", log_prefix)
            except Exception as e:
                logger.warning("%sError during unassign: %s", log_prefix, e)

            # Phase 2: Send quit command
            phase = ShutdownPhase.QUITTING
            logger.info("%sPhase 2: Sending quit command", log_prefix)

            try:
                await send_func(CommandMessage.quit())
            except Exception as e:
                logger.warning("%sError sending quit: %s", log_prefix, e)

            # Wait for graceful exit
            try:
                await asyncio.wait_for(process.wait(), timeout=quit_timeout)
                logger.info("%sProcess exited gracefully", log_prefix)
                phase = ShutdownPhase.DRAINING

            except asyncio.TimeoutError:
                # Phase 3: SIGTERM
                phase = ShutdownPhase.TERMINATING
                logger.warning("%sProcess did not exit gracefully, sending SIGTERM", log_prefix)
                forced = True

                try:
                    process.terminate()
                    await asyncio.wait_for(process.wait(), timeout=terminate_timeout)
                    logger.info("%sProcess terminated after SIGTERM", log_prefix)
                    phase = ShutdownPhase.DRAINING

                except asyncio.TimeoutError:
                    # Phase 4: SIGKILL
                    phase = ShutdownPhase.KILLING
                    logger.warning("%sProcess did not terminate, sending SIGKILL", log_prefix)

                    process.kill()
                    await process.wait()
                    logger.info("%sProcess killed", log_prefix)
                    phase = ShutdownPhase.DRAINING

            # Phase 5: Drain pipes
            if phase == ShutdownPhase.DRAINING:
                await self.drain_process_pipes(
                    stdout=process.stdout,
                    stderr=process.stderr,
                    timeout=drain_timeout,
                )

            phase = ShutdownPhase.COMPLETE
            duration_ms = (time.perf_counter() - start_time) * 1000

            logger.info(
                "%sShutdown complete in %.1fms (acknowledged=%s, forced=%s)",
                log_prefix, duration_ms, acknowledged, forced
            )

            return ShutdownResult(
                success=True,
                acknowledged=acknowledged,
                forced=forced,
                duration_ms=duration_ms,
                phase_reached=phase,
            )

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            error = str(e)
            logger.error("%sShutdown failed: %s", log_prefix, e, exc_info=True)

            return ShutdownResult(
                success=False,
                acknowledged=acknowledged,
                forced=forced,
                duration_ms=duration_ms,
                phase_reached=phase,
                error=error,
            )
