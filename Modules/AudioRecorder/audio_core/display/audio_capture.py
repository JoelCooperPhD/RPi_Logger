
import asyncio
import logging
import re
import struct
import time
from datetime import datetime
from typing import Dict, Optional, TYPE_CHECKING

from Modules.base import AsyncTaskManager

if TYPE_CHECKING:
    from ..interfaces.gui import TkinterGUI

logger = logging.getLogger("AudioCaptureManager")


class AudioCaptureManager:

    def __init__(self, gui: 'TkinterGUI', available_devices: dict):
        self.gui = gui
        self.available_devices = available_devices
        self.audio_processes: Dict[int, asyncio.subprocess.Process] = {}
        self.audio_sample_rate = 8000  # Capture at 8kHz for visualization
        self.running = True
        self._tasks = AsyncTaskManager("AudioCaptureTasks", logger)
        self._capture_tasks: Dict[int, asyncio.Task] = {}

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

            def _on_done(_: asyncio.Task, did: int = device_id) -> None:
                self._capture_tasks.pop(did, None)

            task = self._tasks.create(
                self._capture_loop_for_device(device_id),
                name=f"audio_capture_{device_id}",
                done_callback=_on_done
            )
            self._capture_tasks[device_id] = task

        except Exception as e:
            logger.error("Failed to start audio capture for device %d: %s", device_id, e)
            if device_id in self.audio_processes:
                del self.audio_processes[device_id]

    async def stop_capture_for_device(self, device_id: int):
        task_name = f"audio_capture_{device_id}"

        capture_task = self._capture_tasks.get(device_id)

        process_duration_ms: Optional[float] = None

        if device_id in self.audio_processes:
            process = self.audio_processes[device_id]

            # Remove from dict first to stop the background capture loop
            del self.audio_processes[device_id]
            logger.debug("Removed device %d from audio_processes, stopping capture loop", device_id)

            stop_started = time.perf_counter()
            try:
                process.terminate()
                logger.debug("Terminated arecord process for device %d, waiting for exit", device_id)
                await asyncio.wait_for(process.wait(), timeout=2.0)
                process_duration_ms = (time.perf_counter() - stop_started) * 1000
                logger.info(
                    "Stopped audio capture for device %d in %.1f ms",
                    device_id,
                    process_duration_ms,
                )
            except asyncio.TimeoutError:
                logger.warning("Process for device %d didn't exit after terminate, killing", device_id)
                process.kill()
                try:
                    await asyncio.wait_for(process.wait(), timeout=1.0)
                    process_duration_ms = (time.perf_counter() - stop_started) * 1000
                    logger.info(
                        "Killed audio capture for device %d in %.1f ms",
                        device_id,
                        process_duration_ms,
                    )
                except asyncio.TimeoutError:
                    logger.error("Process for device %d hung after kill", device_id)
            except Exception as e:
                logger.error("Error stopping audio capture for device %d: %s", device_id, e)

        # Best-effort cancellation for the capture loop task even if the process was missing
        if capture_task and not capture_task.done():
            cancelled = await self._tasks.cancel(task_name, timeout=1.5)
            if not cancelled:
                logger.warning("Background capture task for device %d did not exit cleanly", device_id)
        else:
            # Ensure stale bookkeeping is cleared
            self._capture_tasks.pop(device_id, None)

        if process_duration_ms is None and device_id not in self.audio_processes:
            logger.debug("Audio capture process for device %d was already stopped", device_id)

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
            stop_started = time.perf_counter()
            stop_tasks = [
                self.stop_capture_for_device(device_id)
                for device_id in list(self.audio_processes.keys())
            ]
            await asyncio.gather(*stop_tasks, return_exceptions=True)
            total_ms = (time.perf_counter() - stop_started) * 1000
            logger.info("Stopped all audio capture processes in %.1f ms", total_ms)

        # Cancel any straggling capture tasks that were still registered
        if self._capture_tasks:
            await self._tasks.cancel_matching(
                [f"audio_capture_{device_id}" for device_id in list(self._capture_tasks.keys())],
                timeout=1.5,
            )
            self._capture_tasks.clear()

    async def shutdown_tasks(self) -> None:
        await self._tasks.shutdown(timeout=2.0)
