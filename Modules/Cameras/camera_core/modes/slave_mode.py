
import asyncio
import base64
import time
from typing import TYPE_CHECKING

import cv2

from .base_mode import BaseMode
from logger_core.commands import BaseSlaveMode, BaseCommandHandler
from ..commands import CommandHandler

if TYPE_CHECKING:
    from ..camera_system import CameraSystem


class SlaveMode(BaseSlaveMode, BaseMode):

    def __init__(self, camera_system: 'CameraSystem'):
        BaseSlaveMode.__init__(self, camera_system)
        BaseMode.__init__(self, camera_system)

    def create_command_handler(self) -> BaseCommandHandler:
        return CommandHandler(self.system)

    async def _main_loop(self) -> None:
        last_preview_time = 0
        preview_interval = 0.033  # ~30 FPS for preview streaming

        loop = asyncio.get_event_loop()

        while self.is_running():
            current_time = time.time()

            frames = self.update_preview_frames()

            if current_time - last_preview_time >= preview_interval:
                last_preview_time = current_time

                for i, frame in enumerate(frames):
                    if (i < len(self.system.preview_enabled) and
                        self.system.preview_enabled[i] and
                        frame is not None):
                        try:
                            ret, buffer = await loop.run_in_executor(
                                None,
                                cv2.imencode,
                                '.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75]
                            )
                            if ret:
                                from logger_core.commands import StatusMessage
                                frame_b64 = base64.b64encode(buffer).decode('utf-8')
                                StatusMessage.send("preview_frame", {
                                    "camera_id": i,
                                    "frame": frame_b64,
                                    "timestamp": current_time,
                                })
                        except Exception as e:
                            self.logger.error("Error encoding preview frame: %s", e)

            # Minimal sleep to prevent excessive CPU usage but allow high frame rates
            await asyncio.sleep(0.001)  # 1ms sleep
