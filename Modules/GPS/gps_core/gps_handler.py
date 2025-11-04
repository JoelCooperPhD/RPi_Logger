import asyncio
import contextlib
import logging
from collections import deque
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Dict, Any, Optional

import serial_asyncio

from .nmea_parser import NMEAParser

logger = logging.getLogger(__name__)


class GPSHandler:

    def __init__(self, port: str = '/dev/ttyUSB0', baudrate: int = 9600):
        self.port = port
        self.baudrate = baudrate
        self.parser = NMEAParser()
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.read_task: Optional[asyncio.Task] = None
        self.running = False
        self.recent_sentences: deque[str] = deque(maxlen=500)
        self._stop_lock = asyncio.Lock()

    async def start(self) -> None:
        logger.info("Connecting to GPS on %s @ %d baud", self.port, self.baudrate)

        self.reader, self.writer = await serial_asyncio.open_serial_connection(
            url=self.port,
            baudrate=self.baudrate
        )

        self.running = True
        self.read_task = asyncio.create_task(self._read_loop())

        logger.info("GPS connection established")

    async def stop(self) -> None:
        async with self._stop_lock:
            if not self.running and not self.read_task and not self.writer:
                logger.debug("GPS handler already stopped")
                return

            logger.info("Stopping GPS handler")
            self.running = False

            task = self.read_task
            if task:
                task_loop = task.get_loop()
                task.cancel()

                async def _await_task_completion() -> None:
                    with contextlib.suppress(asyncio.CancelledError):
                        await asyncio.wait_for(task, timeout=2.0)

                try:
                    current_loop = asyncio.get_running_loop()
                except RuntimeError:
                    current_loop = None

                try:
                    if current_loop is task_loop:
                        await _await_task_completion()
                    else:
                        waiter = asyncio.run_coroutine_threadsafe(_await_task_completion(), task_loop)
                        waiter.result(timeout=2.5)
                except asyncio.TimeoutError:
                    logger.warning("GPS read loop did not cancel within 2s; forcing close")
                except FutureTimeoutError:
                    logger.warning("GPS read loop did not cancel within 2s (cross-loop); forcing close")
                except Exception as exc:  # pragma: no cover - defensive logging
                    logger.error("Failed while awaiting GPS read loop shutdown: %s", exc, exc_info=True)
                finally:
                    self.read_task = None

            writer = self.writer
            transport = getattr(writer, "transport", None) if writer else None
            if writer:
                try:
                    writer.close()
                except Exception as exc:
                    logger.debug("Error closing GPS writer: %s", exc, exc_info=True)

                wait_closed = getattr(writer, "wait_closed", None)
                if wait_closed:
                    try:
                        await asyncio.wait_for(wait_closed(), timeout=2.0)
                    except asyncio.TimeoutError:
                        logger.warning("Timed out waiting for GPS writer to close; aborting transport")
                        if transport:
                            transport.close()
                    except Exception as exc:  # pragma: no cover - defensive logging
                        logger.debug("GPS writer wait_closed error: %s", exc, exc_info=True)
                elif transport:
                    transport.close()

            self.reader = None
            self.writer = None
            self.running = False

            logger.info("GPS handler stopped")

    async def wait_for_fix(self, timeout: float = 10.0) -> bool:
        start_time = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start_time < timeout:
            data = self.get_latest_data()
            if data['fix_quality'] > 0:
                logger.info("GPS fix acquired!")
                return True
            await asyncio.sleep(0.5)

        logger.warning("GPS fix not acquired within timeout")
        return False

    def get_latest_data(self) -> Dict[str, Any]:
        return self.parser.get_latest_data()

    async def _read_loop(self) -> None:
        logger.info("GPS read loop started")
        sentence_count = 0
        last_log_count = 0

        try:
            while self.running:
                line = await self.reader.readline()
                sentence = line.decode('ascii', errors='ignore').strip()

                if sentence:
                    sentence_count += 1
                    logger.debug("RX [%d]: %s", sentence_count, sentence)
                    self.recent_sentences.append(sentence)
                    self.parser.parse_sentence(sentence)

                    if sentence_count - last_log_count >= 50:
                        logger.info("Received %d GPS sentences (latest: %s)", sentence_count, sentence[:40])
                        last_log_count = sentence_count

        except asyncio.CancelledError:
            logger.debug("GPS read loop cancelled")
        except Exception as e:
            logger.error("GPS read loop error: %s", e, exc_info=True)
        finally:
            logger.info("GPS read loop stopped (received %d sentences)", sentence_count)

    def get_recent_sentences(self, limit: Optional[int] = None) -> list[str]:
        if limit is None or limit <= 0:
            return list(self.recent_sentences)
        if limit >= len(self.recent_sentences):
            return list(self.recent_sentences)
        return list(self.recent_sentences)[-limit:]
