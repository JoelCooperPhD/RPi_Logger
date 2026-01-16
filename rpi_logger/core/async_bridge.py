
import asyncio
import threading
import time
import tkinter as tk
from typing import Optional
from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger("AsyncBridge")


class AsyncBridge:
    """
    Bridge between Tkinter (main thread) and AsyncIO (background thread).

    This implements the "Guest Mode" pattern:
    - Tkinter is the "host" (main thread, owns the GUI with true mainloop())
    - AsyncIO is the "guest" (background thread, runs async tasks)
    - Communication via thread-safe callbacks

    This pattern is required for TkinterMapView and other libraries that
    depend on Tkinter's proper mainloop() implementation.
    """

    def __init__(self, root: tk.Tk):
        self.root = root
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None
        self._running = True
        self._ready = threading.Event()

    def start(self) -> None:
        """Start AsyncIO event loop in background thread."""
        logger.debug("Starting AsyncIO bridge in background thread")
        self.thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self.thread.start()

        if not self._ready.wait(timeout=5.0):
            raise RuntimeError("AsyncIO loop failed to start within 5 seconds")

        logger.debug("AsyncIO event loop running in background (thread %s)",
                    self.thread.ident)

    def _run_event_loop(self) -> None:
        """Run asyncio event loop (called in background thread)."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        logger.debug("AsyncIO loop started in thread %s", threading.get_ident())

        self._ready.set()

        self.loop.run_forever()

        logger.debug("AsyncIO loop stopped")

    def run_coroutine(self, coro):
        """
        Schedule a coroutine to run in the AsyncIO loop.
        Can be called from Tkinter (main thread).

        Returns:
            concurrent.futures.Future that can be used to get the result
        """
        if self.loop is None:
            raise RuntimeError("AsyncIO loop not started")
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future

    def call_in_gui(self, func, *args, **kwargs) -> None:
        """
        Schedule a function to run in the GUI (main thread).
        Can be called from AsyncIO tasks (background thread).

        This is thread-safe via Tkinter's after() mechanism.
        """
        def wrapper():
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                logger.error(f"AsyncBridge ERROR in {func.__name__}: {e}", exc_info=True)
                raise

        self.root.after(0, wrapper)

    async def call_in_gui_async(self, func, *args, timeout: float | None = None, **kwargs):
        """Awaitably schedule a GUI-thread callback from async code."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError as exc:  # Not in an asyncio context
            raise RuntimeError("call_in_gui_async() must be awaited from an asyncio task") from exc

        future = loop.create_future()

        def wrapper():
            try:
                result = func(*args, **kwargs)
            except Exception as error:  # pragma: no cover - GUI thread safety
                loop.call_soon_threadsafe(future.set_exception, error)
            else:
                loop.call_soon_threadsafe(future.set_result, result)

        self.root.after(0, wrapper)

        if timeout is not None:
            return await asyncio.wait_for(future, timeout)

        return await future

    def stop(self, timeout: float = 5.0) -> bool:
        """
        Stop the AsyncIO event loop and cancel all tasks.

        Args:
            timeout: Maximum time to wait for shutdown (seconds)

        Returns:
            True if shutdown completed cleanly, False if timed out
        """
        if not self.loop or not self._running:
            return True

        logger.debug("Stopping AsyncIO bridge")
        self._running = False

        # Schedule shutdown and wait for completion
        shutdown_complete = threading.Event()

        async def shutdown_wrapper():
            try:
                await self._shutdown()
            finally:
                shutdown_complete.set()

        asyncio.run_coroutine_threadsafe(shutdown_wrapper(), self.loop)

        # Wait for shutdown with timeout
        if not shutdown_complete.wait(timeout=timeout):
            logger.warning(
                "AsyncIO bridge shutdown timed out after %.1fs - forcing loop stop",
                timeout
            )
            # Force stop the loop
            self.loop.call_soon_threadsafe(self.loop.stop)
            return False

        logger.debug("AsyncIO bridge shutdown completed")
        return True

    async def _shutdown(self, task_timeout: float = 3.0) -> None:
        """
        Cancel all tasks and stop the loop (runs in background thread).

        Args:
            task_timeout: Maximum time to wait for tasks to cancel
        """
        tasks = [task for task in asyncio.all_tasks(self.loop)
                 if task is not asyncio.current_task()]

        if not tasks:
            logger.debug("No pending tasks to cancel")
            self.loop.stop()
            return

        logger.debug("Cancelling %d pending tasks", len(tasks))

        # Log task names for diagnostics
        for task in tasks:
            task_name = task.get_name() if hasattr(task, 'get_name') else str(task)
            logger.debug("Pending task: %s", task_name)

        # Cancel all tasks
        for task in tasks:
            task.cancel()

        # Wait with timeout
        try:
            done, pending = await asyncio.wait(
                tasks,
                timeout=task_timeout,
                return_when=asyncio.ALL_COMPLETED
            )

            if pending:
                logger.warning(
                    "%d tasks did not complete within %.1fs:",
                    len(pending), task_timeout
                )
                for task in pending:
                    task_name = task.get_name() if hasattr(task, 'get_name') else str(task)
                    logger.warning("  - %s", task_name)

            # Check for exceptions in completed tasks
            for task in done:
                try:
                    exc = task.exception()
                    if exc and not isinstance(exc, asyncio.CancelledError):
                        task_name = task.get_name() if hasattr(task, 'get_name') else str(task)
                        logger.error("Task %s raised exception: %s", task_name, exc)
                except asyncio.CancelledError:
                    pass

        except Exception as e:
            logger.error("Error during task cleanup: %s", e)

        self.loop.stop()
        logger.debug("AsyncIO loop stopped cleanly")
