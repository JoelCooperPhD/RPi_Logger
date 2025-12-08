"""
Retry Policy - Exponential backoff for transient failures.

Provides configurable retry behavior for connection operations
with exponential backoff and jitter to prevent thundering herd.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, List, Optional, TypeVar

from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger("RetryPolicy")

T = TypeVar('T')


class RetryOutcome(Enum):
    """Outcome of a retry operation."""
    SUCCESS = "success"
    EXHAUSTED = "exhausted"  # All retries failed
    ABORTED = "aborted"      # Retry was cancelled


@dataclass
class RetryAttempt:
    """Record of a single retry attempt."""
    attempt_number: int
    started_at: float
    duration_ms: float
    success: bool
    error: Optional[str] = None


@dataclass
class RetryResult:
    """Result of a retry operation."""
    outcome: RetryOutcome
    success: bool
    attempts: List[RetryAttempt] = field(default_factory=list)
    total_duration_ms: float = 0.0
    final_error: Optional[str] = None
    result_data: Any = None

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)


class RetryPolicy:
    """
    Configurable retry policy with exponential backoff.

    Features:
    - Exponential backoff with configurable base and max delay
    - Optional jitter to prevent thundering herd
    - Retry callbacks for logging/monitoring
    - Abort capability for graceful cancellation

    Usage:
        policy = RetryPolicy(max_attempts=3, base_delay=1.0)

        result = await policy.execute(
            operation=lambda: connect_device(device_id),
            on_retry=lambda attempt, error: logger.warning(
                "Retry %d: %s", attempt, error
            ),
        )

        if result.success:
            print(f"Connected after {result.attempt_count} attempts")
        else:
            print(f"Failed after {result.attempt_count} attempts: {result.final_error}")
    """

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        backoff_factor: float = 2.0,
        jitter: float = 0.1,
    ):
        """
        Initialize retry policy.

        Args:
            max_attempts: Maximum number of attempts (including first try)
            base_delay: Initial delay between retries (seconds)
            max_delay: Maximum delay between retries (seconds)
            backoff_factor: Multiplier for exponential backoff
            jitter: Random jitter factor (0.1 = ±10%)
        """
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.jitter = jitter
        self._aborted = False

    def abort(self) -> None:
        """Signal that retry should be aborted."""
        self._aborted = True

    def reset(self) -> None:
        """Reset abort flag for reuse."""
        self._aborted = False

    def get_delay(self, attempt: int) -> float:
        """
        Calculate delay before the given attempt.

        Args:
            attempt: Attempt number (1-based, first retry is attempt 2)

        Returns:
            Delay in seconds with jitter applied
        """
        if attempt <= 1:
            return 0.0

        # Exponential backoff: base_delay * factor^(attempt-2)
        delay = self.base_delay * (self.backoff_factor ** (attempt - 2))
        delay = min(delay, self.max_delay)

        # Apply jitter
        if self.jitter > 0:
            jitter_range = delay * self.jitter
            delay += random.uniform(-jitter_range, jitter_range)

        return max(0.0, delay)

    async def execute(
        self,
        operation: Callable[[], Awaitable[bool]],
        on_retry: Optional[Callable[[int, Optional[str]], None]] = None,
        on_success: Optional[Callable[[int], None]] = None,
    ) -> RetryResult:
        """
        Execute an operation with retries.

        Args:
            operation: Async function that returns True on success, False on failure
            on_retry: Optional callback called before each retry (attempt_num, error)
            on_success: Optional callback called on success (attempt_num)

        Returns:
            RetryResult with outcome and attempt history
        """
        self._aborted = False
        attempts: List[RetryAttempt] = []
        start_time = time.time()
        last_error: Optional[str] = None

        for attempt in range(1, self.max_attempts + 1):
            if self._aborted:
                return RetryResult(
                    outcome=RetryOutcome.ABORTED,
                    success=False,
                    attempts=attempts,
                    total_duration_ms=(time.time() - start_time) * 1000,
                    final_error="Retry aborted",
                )

            # Wait before retry (not before first attempt)
            if attempt > 1:
                delay = self.get_delay(attempt)
                if on_retry:
                    on_retry(attempt, last_error)
                logger.debug(
                    "Retry attempt %d/%d after %.2fs delay",
                    attempt, self.max_attempts, delay
                )
                await asyncio.sleep(delay)

            # Execute the operation
            attempt_start = time.time()
            try:
                success = await operation()
                attempt_duration = (time.time() - attempt_start) * 1000

                attempt_record = RetryAttempt(
                    attempt_number=attempt,
                    started_at=attempt_start,
                    duration_ms=attempt_duration,
                    success=success,
                )
                attempts.append(attempt_record)

                if success:
                    if on_success:
                        on_success(attempt)
                    return RetryResult(
                        outcome=RetryOutcome.SUCCESS,
                        success=True,
                        attempts=attempts,
                        total_duration_ms=(time.time() - start_time) * 1000,
                    )
                else:
                    last_error = "Operation returned False"

            except Exception as e:
                attempt_duration = (time.time() - attempt_start) * 1000
                last_error = str(e)

                attempt_record = RetryAttempt(
                    attempt_number=attempt,
                    started_at=attempt_start,
                    duration_ms=attempt_duration,
                    success=False,
                    error=last_error,
                )
                attempts.append(attempt_record)

                logger.debug(
                    "Attempt %d failed: %s (%.1fms)",
                    attempt, last_error, attempt_duration
                )

        # All attempts exhausted
        return RetryResult(
            outcome=RetryOutcome.EXHAUSTED,
            success=False,
            attempts=attempts,
            total_duration_ms=(time.time() - start_time) * 1000,
            final_error=last_error,
        )

    async def execute_with_result(
        self,
        operation: Callable[[], Awaitable[T]],
        is_success: Callable[[T], bool] = lambda x: x is not None,
        on_retry: Optional[Callable[[int, Optional[str]], None]] = None,
    ) -> RetryResult:
        """
        Execute an operation that returns a result value.

        Args:
            operation: Async function returning a result
            is_success: Function to determine if result indicates success
            on_retry: Optional callback called before each retry

        Returns:
            RetryResult with result_data containing the final result
        """
        self._aborted = False
        attempts: List[RetryAttempt] = []
        start_time = time.time()
        last_error: Optional[str] = None
        last_result: Any = None

        for attempt in range(1, self.max_attempts + 1):
            if self._aborted:
                return RetryResult(
                    outcome=RetryOutcome.ABORTED,
                    success=False,
                    attempts=attempts,
                    total_duration_ms=(time.time() - start_time) * 1000,
                    final_error="Retry aborted",
                    result_data=last_result,
                )

            if attempt > 1:
                delay = self.get_delay(attempt)
                if on_retry:
                    on_retry(attempt, last_error)
                await asyncio.sleep(delay)

            attempt_start = time.time()
            try:
                result = await operation()
                last_result = result
                attempt_duration = (time.time() - attempt_start) * 1000
                success = is_success(result)

                attempts.append(RetryAttempt(
                    attempt_number=attempt,
                    started_at=attempt_start,
                    duration_ms=attempt_duration,
                    success=success,
                ))

                if success:
                    return RetryResult(
                        outcome=RetryOutcome.SUCCESS,
                        success=True,
                        attempts=attempts,
                        total_duration_ms=(time.time() - start_time) * 1000,
                        result_data=result,
                    )
                else:
                    last_error = "Result check failed"

            except Exception as e:
                attempt_duration = (time.time() - attempt_start) * 1000
                last_error = str(e)
                attempts.append(RetryAttempt(
                    attempt_number=attempt,
                    started_at=attempt_start,
                    duration_ms=attempt_duration,
                    success=False,
                    error=last_error,
                ))

        return RetryResult(
            outcome=RetryOutcome.EXHAUSTED,
            success=False,
            attempts=attempts,
            total_duration_ms=(time.time() - start_time) * 1000,
            final_error=last_error,
            result_data=last_result,
        )


# Pre-configured policies for common use cases
DEFAULT_RETRY_POLICY = RetryPolicy(
    max_attempts=3,
    base_delay=1.0,
    max_delay=10.0,
    backoff_factor=2.0,
)

AGGRESSIVE_RETRY_POLICY = RetryPolicy(
    max_attempts=5,
    base_delay=0.5,
    max_delay=5.0,
    backoff_factor=1.5,
)

PATIENT_RETRY_POLICY = RetryPolicy(
    max_attempts=3,
    base_delay=2.0,
    max_delay=30.0,
    backoff_factor=2.0,
)
