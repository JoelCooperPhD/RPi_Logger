
import asyncio
import logging
from pathlib import Path
from typing import Any, Callable, List, Optional, TypeVar

from rpi_logger.core.logging_utils import get_module_logger


logger = get_module_logger(__name__)

T = TypeVar('T')


async def save_file_async(
    filepath: Path,
    write_func: Callable,
    *args: Any,
    **kwargs: Any
) -> Optional[Path]:
    try:
        await asyncio.to_thread(write_func, filepath, *args, **kwargs)
        logger.debug("Saved file: %s", filepath)
        return filepath
    except Exception as e:
        logger.error("Failed to save file %s: %s", filepath, e)
        return None


async def gather_with_logging(
    tasks: List[asyncio.Task],
    operation_name: str,
    logger_instance: Optional[logging.Logger] = None,
    return_exceptions: bool = True
) -> List[Any]:
    log = logger_instance or logger
    if not tasks:
        log.debug("%s: No tasks to gather", operation_name)
        return []
    log.debug("%s: Gathering %d tasks", operation_name, len(tasks))
    results = await asyncio.gather(*tasks, return_exceptions=return_exceptions)
    error_count = sum(1 for r in results if isinstance(r, Exception))
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            log.error("%s: Task %d failed: %s", operation_name, i, result)
    if error_count:
        log.warning("%s: Completed with %d/%d errors", operation_name, error_count, len(tasks))
    else:
        log.debug("%s: All tasks completed successfully", operation_name)
    return results


async def gather_with_timeout(
    tasks: List[asyncio.Task],
    timeout: float,
    operation_name: str,
    logger_instance: Optional[logging.Logger] = None
) -> List[Any]:
    log = logger_instance or logger
    try:
        log.debug("%s: Starting with %.1fs timeout", operation_name, timeout)
        return await asyncio.wait_for(
            gather_with_logging(tasks, operation_name, logger_instance),
            timeout=timeout
        )
    except asyncio.TimeoutError:
        log.error("%s: Timeout after %.1fs, cancelling tasks", operation_name, timeout)
        for task in tasks:
            if not task.done():
                task.cancel()
        raise


async def run_with_retries(
    coro_func: Callable,
    max_retries: int = 3,
    delay: float = 1.0,
    operation_name: str = "operation",
    logger_instance: Optional[logging.Logger] = None
) -> Any:
    log = logger_instance or logger
    last_exception = None
    for attempt in range(max_retries):
        try:
            log.debug("%s: Attempt %d/%d", operation_name, attempt + 1, max_retries)
            result = await coro_func()
            if attempt > 0:
                log.info("%s: Succeeded on attempt %d", operation_name, attempt + 1)
            return result
        except Exception as e:
            last_exception = e
            if attempt < max_retries - 1:
                log.warning("%s: Attempt %d failed: %s, retrying in %.1fs",
                           operation_name, attempt + 1, e, delay)
                await asyncio.sleep(delay)
            else:
                log.error("%s: All %d attempts failed", operation_name, max_retries)
    raise last_exception


async def cancel_task_safely(
    task: Optional[asyncio.Task],
    task_name: str = "task",
    timeout: float = 5.0,
    logger_instance: Optional[logging.Logger] = None
) -> bool:
    log = logger_instance or logger
    if task is None:
        log.debug("%s: No task to cancel", task_name)
        return True
    if task.done():
        log.debug("%s: Already done", task_name)
        return True
    log.debug("%s: Cancelling...", task_name)
    task.cancel()
    try:
        await asyncio.wait_for(task, timeout=timeout)
        log.debug("%s: Cancelled successfully", task_name)
        return True
    except asyncio.CancelledError:
        log.debug("%s: Cancelled (CancelledError)", task_name)
        return True
    except asyncio.TimeoutError:
        log.warning("%s: Cancellation timeout after %.1fs", task_name, timeout)
        return False
    except Exception as e:
        log.warning("%s: Exception during cancellation: %s", task_name, e)
        return False
