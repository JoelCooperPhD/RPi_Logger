
import asyncio
import logging
import re
import struct
from datetime import datetime
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..interfaces.gui import TkinterGUI

logger = logging.getLogger("AudioCaptureManager")


class AudioCaptureManager:

    def __init__(self, gui: 'TkinterGUI', available_devices: dict):
        self.gui = gui
        self.available_devices = available_devices
        self.audio_processes: Dict[int, asyncio.subprocess.Process] = {}
        self.audio_sample_rate = 8000  # Capture at 8kHz for visualization
        self.background_tasks: List[asyncio.Task] = []
        self.running = True

    def _task_done_callback(self, task: asyncio.Task) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception("Background task failed: %s", e)

    async def start_capture_for_device(self, device_id: int):
        if device_id in self.audio_processes:
            return

        device_info = self.available_devices.get(device_id)
        if not device_info:
            logger.error("Device %d not found in available devices", device_id)
            return

        device_name = device_info['name']
        alsa_match = re.search(r'\(([^)]+)\)$', device_name)
        if alsa_match:
            alsa_device = alsa_match.group(1)
        else:
            alsa_device = f'hw:{device_id}'
            logger.warning(
                "Could not extract ALSA device from name '%s', using fallback '%s'",
                device_name, alsa_device
            )

        try:
            cmd = [
                'arecord',
                '-D', alsa_device,
                '-f', 'S16_LE',
                '-r', '8000',
                '-c', '1',
                '-t', 'raw',
                '--quiet'
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE  # Capture errors for logging
            )
            self.audio_processes[device_id] = process

            await asyncio.sleep(0.1)

            if process.returncode is not None:
                try:
                    stderr_data = await asyncio.wait_for(process.stderr.read(), timeout=0.5)
                    error_msg = stderr_data.decode().strip() if stderr_data else "Unknown error"
                    logger.error(
                        "arecord failed to start for device %d (exit code %d): %s",
                        device_id, process.returncode, error_msg
                    )
                except Exception:
                    logger.error(
                        "arecord failed to start for device %d (exit code %d)",
                        device_id, process.returncode
                    )
                del self.audio_processes[device_id]
                return

            logger.info("Started audio capture for device %d (pid: %s)", device_id, process.pid)

            task = asyncio.create_task(self._capture_loop_for_device(device_id))
            task.add_done_callback(self._task_done_callback)
            self.background_tasks.append(task)

        except Exception as e:
            logger.error("Failed to start audio capture for device %d: %s", device_id, e)
            if device_id in self.audio_processes:
                del self.audio_processes[device_id]

    async def stop_capture_for_device(self, device_id: int):
        if device_id in self.audio_processes:
            process = self.audio_processes[device_id]
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                process.kill()
            except Exception as e:
                logger.error("Error stopping audio capture for device %d: %s", device_id, e)
            finally:
                del self.audio_processes[device_id]
                logger.info("Stopped audio capture for device %d", device_id)

    async def _read_audio_data_for_device(self, device_id: int):
        if device_id not in self.audio_processes:
            return

        process = self.audio_processes[device_id]
        if not process.stdout:
            return

        try:
            chunk_duration = 0.1  # 100ms
            chunk_samples = int(self.audio_sample_rate * chunk_duration)
            chunk_bytes = chunk_samples * 2

            # Add timeout to prevent blocking during shutdown
            try:
                data = await asyncio.wait_for(
                    process.stdout.read(chunk_bytes),
                    timeout=0.3
                )
            except asyncio.TimeoutError:
                logger.debug("Audio read timeout for device %d", device_id)
                return

            if data and self.gui and device_id in self.gui.level_meters:
                timestamp = datetime.now().timestamp()

                samples = struct.unpack(f'{len(data)//2}h', data)

                normalized = [s / 32768.0 for s in samples]

                self.gui.level_meters[device_id].add_samples(normalized, timestamp)

        except Exception as e:
            logger.debug("Error reading audio data for device %d: %s", device_id, e)

    async def _capture_loop_for_device(self, device_id: int):
        while self.running and self.gui and device_id in self.audio_processes:
            try:
                await self._read_audio_data_for_device(device_id)
            except Exception as e:
                logger.error("Audio capture loop error for device %d: %s", device_id, e)
                await asyncio.sleep(0.1)

        if device_id in self.audio_processes:
            process = self.audio_processes[device_id]
            if process.returncode and process.returncode != 0:
                try:
                    stderr_data = await asyncio.wait_for(process.stderr.read(), timeout=0.5)
                    if stderr_data:
                        logger.error(
                            "arecord error for device %d (exit code %d): %s",
                            device_id,
                            process.returncode,
                            stderr_data.decode().strip()
                        )
                except asyncio.TimeoutError:
                    logger.error("arecord failed for device %d (exit code %d)", device_id, process.returncode)
                except Exception as e:
                    logger.debug("Error reading stderr for device %d: %s", device_id, e)

    async def stop_all_captures(self):
        self.running = False

        if self.audio_processes:
            stop_tasks = [
                self.stop_capture_for_device(device_id)
                for device_id in list(self.audio_processes.keys())
            ]
            await asyncio.gather(*stop_tasks, return_exceptions=True)
