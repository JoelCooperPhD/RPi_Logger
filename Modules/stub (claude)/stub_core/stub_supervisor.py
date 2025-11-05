import asyncio
import logging
import time
from typing import Optional

from logger_core.commands import StatusMessage, StatusType
from .constants import DISPLAY_NAME
from .model import StubModel
from .controller import StubController
from .view import StubView

logger = logging.getLogger(__name__)


class StubSupervisor:
    def __init__(self, args):
        self.args = args

        StatusMessage.send(StatusType.INITIALIZING, {"message": f"{DISPLAY_NAME} starting"})

        self.model = StubModel()
        self.controller = StubController(self.model, shutdown_callback=self._shutdown_callback)
        self.view: Optional[StubView] = None

        self._shutdown_requested = False
        self.shutdown_event = asyncio.Event()

        if args.mode == "gui":
            self.view = StubView(
                self.model,
                args=args,
                window_geometry=args.window_geometry
            )
            logger.info("StubSupervisor initialized in GUI mode (VMC architecture)")
        else:
            logger.info("StubSupervisor initialized in headless mode")

    async def _shutdown_callback(self):
        await self.shutdown()

    async def run(self):
        run_start = time.perf_counter()
        logger.info("StubSupervisor.run() starting")

        await self.controller.start()

        ready_ms = self.model.mark_ready()
        logger.info(f"{DISPLAY_NAME} ready and idle ({ready_ms:.1f}ms)")

        if self.view:
            tasks = [
                asyncio.create_task(self.view.run(), name="view"),
                asyncio.create_task(self.shutdown_event.wait(), name="shutdown_event")
            ]

            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

            if not self._shutdown_requested:
                logger.info("View or shutdown event triggered, initiating shutdown")
                await self.shutdown()

            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        else:
            logger.info("Headless mode: waiting for shutdown event")
            await self.shutdown_event.wait()

        logger.info("StubSupervisor.run() finished")

    async def shutdown(self):
        if self._shutdown_requested:
            logger.info("shutdown() called but already in progress, skipping")
            return

        logger.info(f"{DISPLAY_NAME} shutting down")

        StatusMessage.send(StatusType.QUITTING, {"message": f"{DISPLAY_NAME} exiting"})

        self._shutdown_requested = True
        self.shutdown_event.set()

        await self.controller.stop()

        if self.view:
            await self.view.cleanup()

        self.model.finalize_metrics()
        metrics = self.model.metrics

        logger.info(
            f"{DISPLAY_NAME} stopped (runtime {metrics.runtime_ms:.1f}ms | shutdown {metrics.shutdown_ms:.1f}ms | window {metrics.window_ms:.1f}ms)"
        )

        self.model.send_runtime_report()

    def get_window_geometry(self) -> Optional[tuple[int, int, int, int]]:
        if self.view:
            return self.view.get_geometry()
        return None
