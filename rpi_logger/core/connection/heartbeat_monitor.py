"""
Heartbeat Monitor - Connection health monitoring.

Tracks heartbeat signals from modules to detect unresponsive
connections and trigger recovery actions.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, Dict, List, Optional, Set

from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger("HeartbeatMonitor")


class HealthStatus(Enum):
    """Health status of a monitored connection."""
    HEALTHY = "healthy"
    WARNING = "warning"    # Missed some heartbeats
    UNHEALTHY = "unhealthy"  # Exceeded threshold
    UNKNOWN = "unknown"    # No heartbeats received yet


@dataclass
class HeartbeatInfo:
    """Heartbeat tracking for a single connection."""
    instance_id: str
    last_heartbeat: float = 0.0
    heartbeat_count: int = 0
    missed_count: int = 0
    status: HealthStatus = HealthStatus.UNKNOWN
    registered_at: float = field(default_factory=time.time)

    def record_heartbeat(self) -> None:
        """Record a received heartbeat."""
        self.last_heartbeat = time.time()
        self.heartbeat_count += 1
        self.missed_count = 0
        self.status = HealthStatus.HEALTHY

    def record_missed(self) -> None:
        """Record a missed heartbeat."""
        self.missed_count += 1

    def time_since_last(self) -> float:
        """Get seconds since last heartbeat."""
        if self.last_heartbeat == 0:
            return time.time() - self.registered_at
        return time.time() - self.last_heartbeat

    def uptime_seconds(self) -> float:
        """Get seconds since registration."""
        return time.time() - self.registered_at


# Callback types
UnhealthyCallback = Callable[[str, HeartbeatInfo], Awaitable[None]]
RecoveredCallback = Callable[[str, HeartbeatInfo], Awaitable[None]]


class HeartbeatMonitor:
    """
    Monitors heartbeats from module instances.

    This provides health monitoring by:
    1. Tracking heartbeat timestamps per instance
    2. Detecting missed heartbeats
    3. Triggering callbacks when instances become unhealthy
    4. Triggering callbacks when instances recover

    Usage:
        monitor = HeartbeatMonitor(
            interval=2.0,
            timeout=10.0,
            warning_threshold=2,
        )

        monitor.set_unhealthy_callback(handle_unhealthy)
        monitor.set_recovered_callback(handle_recovered)

        await monitor.start()

        # Register an instance to monitor
        monitor.register("DRT:ACM0")

        # When heartbeat received from module
        monitor.on_heartbeat("DRT:ACM0")
    """

    def __init__(
        self,
        interval: float = 2.0,
        timeout: float = 10.0,
        warning_threshold: int = 2,
        unhealthy_threshold: int = 3,
        callback_timeout: float = 30.0,
    ):
        """
        Initialize heartbeat monitor.

        Args:
            interval: Expected heartbeat interval from modules (seconds)
            timeout: Time without heartbeat before marking unhealthy (seconds)
            warning_threshold: Missed heartbeats before WARNING status
            unhealthy_threshold: Missed heartbeats before UNHEALTHY status
            callback_timeout: Timeout for callback execution (seconds)
        """
        self.interval = interval
        self.timeout = timeout
        self.warning_threshold = warning_threshold
        self.unhealthy_threshold = unhealthy_threshold
        self.callback_timeout = callback_timeout

        self._instances: Dict[str, HeartbeatInfo] = {}
        self._unhealthy_callback: Optional[UnhealthyCallback] = None
        self._recovered_callback: Optional[RecoveredCallback] = None
        self._monitor_task: Optional[asyncio.Task] = None
        self._running = False
        self._lock = asyncio.Lock()

        # Track callback tasks to prevent garbage collection
        self._callback_tasks: Set[asyncio.Task] = set()

    def set_unhealthy_callback(self, callback: UnhealthyCallback) -> None:
        """Set callback for when an instance becomes unhealthy."""
        self._unhealthy_callback = callback

    def set_recovered_callback(self, callback: RecoveredCallback) -> None:
        """Set callback for when an instance recovers."""
        self._recovered_callback = callback

    async def start(self) -> None:
        """Start the heartbeat monitor."""
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("Heartbeat monitor started (interval=%.1fs, timeout=%.1fs)",
                   self.interval, self.timeout)

    async def stop(self) -> None:
        """Stop the heartbeat monitor."""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        # Wait for any pending callback tasks
        if self._callback_tasks:
            await asyncio.gather(*self._callback_tasks, return_exceptions=True)
            self._callback_tasks.clear()

        logger.info("Heartbeat monitor stopped")

    def register(self, instance_id: str) -> None:
        """
        Register an instance for heartbeat monitoring.

        Args:
            instance_id: The instance to monitor
        """
        if instance_id not in self._instances:
            self._instances[instance_id] = HeartbeatInfo(instance_id=instance_id)
            logger.debug("Registered instance for heartbeat: %s", instance_id)

    def unregister(self, instance_id: str) -> None:
        """
        Unregister an instance from monitoring.

        Args:
            instance_id: The instance to stop monitoring
        """
        if instance_id in self._instances:
            del self._instances[instance_id]
            logger.debug("Unregistered instance from heartbeat: %s", instance_id)

    def on_heartbeat(self, instance_id: str, data: Optional[Dict] = None) -> None:
        """
        Record a heartbeat from an instance.

        Args:
            instance_id: The instance that sent the heartbeat
            data: Optional heartbeat data (e.g., uptime, status)
        """
        info = self._instances.get(instance_id)
        if not info:
            # Auto-register if we receive heartbeat for unknown instance
            self.register(instance_id)
            info = self._instances[instance_id]

        was_unhealthy = info.status == HealthStatus.UNHEALTHY
        info.record_heartbeat()

        if was_unhealthy:
            logger.info("Instance %s recovered (received heartbeat)", instance_id)
            if self._recovered_callback:
                task = asyncio.create_task(
                    self._run_recovered_callback(instance_id, info)
                )
                self._callback_tasks.add(task)
                task.add_done_callback(self._callback_tasks.discard)

    async def _run_recovered_callback(
        self, instance_id: str, info: HeartbeatInfo
    ) -> None:
        """Run recovered callback with timeout and error handling."""
        try:
            await asyncio.wait_for(
                self._recovered_callback(instance_id, info),  # type: ignore[misc]
                timeout=self.callback_timeout
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Recovered callback for %s timed out after %.1fs",
                instance_id, self.callback_timeout
            )
        except Exception as e:
            logger.warning("Recovered callback error for %s: %s", instance_id, e)

    def get_status(self, instance_id: str) -> HealthStatus:
        """Get current health status of an instance."""
        info = self._instances.get(instance_id)
        return info.status if info else HealthStatus.UNKNOWN

    def get_info(self, instance_id: str) -> Optional[HeartbeatInfo]:
        """Get heartbeat info for an instance."""
        return self._instances.get(instance_id)

    def get_all_statuses(self) -> Dict[str, HealthStatus]:
        """Get health status of all monitored instances."""
        return {
            instance_id: info.status
            for instance_id, info in self._instances.items()
        }

    def get_unhealthy_instances(self) -> List[str]:
        """Get list of unhealthy instance IDs."""
        return [
            instance_id
            for instance_id, info in self._instances.items()
            if info.status == HealthStatus.UNHEALTHY
        ]

    def is_healthy(self, instance_id: str) -> bool:
        """Check if an instance is healthy."""
        info = self._instances.get(instance_id)
        return info is not None and info.status == HealthStatus.HEALTHY

    async def _monitor_loop(self) -> None:
        """Background task to check heartbeat health."""
        # Check slightly more frequently than the expected interval
        check_interval = self.interval / 2

        while self._running:
            try:
                await asyncio.sleep(check_interval)
                await self._check_all_instances()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Heartbeat monitor error: %s", e)

    async def _check_all_instances(self) -> None:
        """Check health of all registered instances."""
        now = time.time()

        for instance_id, info in list(self._instances.items()):
            time_since = info.time_since_last()

            # Determine expected heartbeats missed
            if info.last_heartbeat == 0:
                # No heartbeats yet - use registration time
                expected_heartbeats = int(time_since / self.interval)
            else:
                expected_heartbeats = int(time_since / self.interval)

            previous_status = info.status

            # Update status based on missed heartbeats
            if expected_heartbeats >= self.unhealthy_threshold:
                info.status = HealthStatus.UNHEALTHY
                info.missed_count = expected_heartbeats
            elif expected_heartbeats >= self.warning_threshold:
                info.status = HealthStatus.WARNING
                info.missed_count = expected_heartbeats
            elif info.last_heartbeat > 0:
                # Only mark healthy if we've received at least one heartbeat
                info.status = HealthStatus.HEALTHY

            # Trigger callback if status changed to unhealthy
            if (info.status == HealthStatus.UNHEALTHY and
                    previous_status != HealthStatus.UNHEALTHY):
                logger.warning(
                    "Instance %s unhealthy: no heartbeat for %.1fs (%d missed)",
                    instance_id, time_since, info.missed_count
                )
                if self._unhealthy_callback:
                    try:
                        await self._unhealthy_callback(instance_id, info)
                    except Exception as e:
                        logger.warning("Unhealthy callback error: %s", e)
