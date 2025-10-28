import asyncio
import logging
from typing import TYPE_CHECKING, Optional

from Modules.base.modes import BaseGUIMode
from ..interfaces.gui import TkinterGUI

if TYPE_CHECKING:
    from ..gps2_system import GPSSystem

logger = logging.getLogger(__name__)


class GUIMode(BaseGUIMode):

    def __init__(self, gps2_system: 'GPSSystem', enable_commands: bool = False):
        super().__init__(gps2_system, enable_commands)
        self.gps_update_task: Optional[asyncio.Task] = None

    def create_gui(self) -> TkinterGUI:
        return TkinterGUI(self.system, self.system.args)

    def create_command_handler(self, gui: TkinterGUI):
        from ..commands import CommandHandler
        return CommandHandler(self.system, gui=gui)

    async def on_devices_connected(self) -> None:
        if self.system.initialized and self.system.gps_handler:
            logger.info("Starting GPS update task")
            self.gps_update_task = asyncio.create_task(self._gps_update_loop())

    def create_tasks(self) -> list[asyncio.Task]:
        tasks = super().create_tasks()
        return tasks

    def update_preview(self) -> None:
        pass

    async def _gps_update_loop(self):
        logger.info("=== GPS UPDATE LOOP START ===")
        logger.info("system.running: %s", self.system.running)
        logger.info("gui: %s", self.gui)
        logger.info("gps_handler: %s", self.system.gps_handler)

        update_count = 0

        try:
            while self.system.running and self.gui:
                if self.system.gps_handler:
                    data = self.system.gps_handler.get_latest_data()
                    update_count += 1

                    if update_count % 50 == 0:
                        logger.info("GPS update loop iteration %d: fix=%s, lat=%.6f, lon=%.6f",
                                   update_count, data.get('fix_quality', 0),
                                   data.get('latitude', 0.0), data.get('longitude', 0.0))

                    if self.gui.root.winfo_exists():
                        self.gui.root.after(0, lambda d=data: self.gui.update_gps_display(d))
                    else:
                        logger.warning("GUI root window does not exist!")
                else:
                    logger.warning("No GPS handler available in update loop!")

                await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            logger.debug("GPS update loop cancelled")
        except Exception as e:
            logger.error("GPS update loop error: %s", e, exc_info=True)
        finally:
            logger.info("=== GPS UPDATE LOOP STOPPED (total updates: %d) ===", update_count)


    async def cleanup(self) -> None:
        logger.info("GPS2 mode cleanup")

        if self.gps_update_task and not self.gps_update_task.done():
            self.gps_update_task.cancel()
            try:
                await self.gps_update_task
            except asyncio.CancelledError:
                pass

        logger.info("GPS2 mode cleanup completed")
