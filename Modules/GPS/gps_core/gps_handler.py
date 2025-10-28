import asyncio
import logging
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
        logger.info("Stopping GPS handler")
        self.running = False

        if self.read_task:
            self.read_task.cancel()
            try:
                await self.read_task
            except asyncio.CancelledError:
                pass

        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()

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
