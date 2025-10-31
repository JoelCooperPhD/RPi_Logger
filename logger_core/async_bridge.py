import asyncio
import threading
import time
import tkinter as tk
from typing import Optional
import logging

logger = logging.getLogger(__name__)


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

    def start(self) -> None:
        """Start AsyncIO event loop in background thread."""
        logger.info("Starting AsyncIO bridge in background thread")
        self.thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self.thread.start()

        while self.loop is None:
            time.sleep(0.01)

        logger.info("AsyncIO event loop running in background (thread %s)",
                   self.thread.ident)

    def _run_event_loop(self) -> None:
        """Run asyncio event loop (called in background thread)."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        logger.debug("AsyncIO loop started in thread %s", threading.get_ident())

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

        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def call_in_gui(self, func, *args, **kwargs) -> None:
        """
        Schedule a function to run in the GUI (main thread).
        Can be called from AsyncIO tasks (background thread).

        This is thread-safe via Tkinter's after() mechanism.
        """
        def wrapper():
            try:
                func(*args, **kwargs)
            except Exception as e:
                logger.error("Error in GUI callback %s: %s", func.__name__, e, exc_info=True)

        self.root.after(0, wrapper)

    def stop(self) -> None:
        """Stop the AsyncIO event loop and cancel all tasks."""
        if self.loop and self._running:
            logger.info("Stopping AsyncIO bridge")
            self._running = False

            asyncio.run_coroutine_threadsafe(self._shutdown(), self.loop)

    async def _shutdown(self) -> None:
        """Cancel all tasks and stop the loop (runs in background thread)."""
        tasks = [task for task in asyncio.all_tasks(self.loop)
                 if task is not asyncio.current_task()]

        logger.info("Cancelling %d pending tasks", len(tasks))

        for task in tasks:
            task.cancel()

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        self.loop.stop()
        logger.info("AsyncIO loop stopped cleanly")
