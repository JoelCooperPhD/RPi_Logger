
import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import aiofiles
import sounddevice as sd

logger = logging.getLogger(__name__)


class DeviceDiscovery:

    @staticmethod
    async def get_audio_input_devices() -> Dict[int, Dict[str, Any]]:
        def _query_devices():
            try:
                devices = sd.query_devices()
                input_devices = {}

                for idx, device in enumerate(devices):
                    if device['max_input_channels'] > 0:  # Has input capability
                        input_devices[idx] = {
                            'name': device['name'],
                            'channels': device['max_input_channels'],
                            'sample_rate': device['default_samplerate']
                        }

                return input_devices
            except Exception as e:
                logger.error("Error querying audio devices: %s", e)
                return {}

        return await asyncio.to_thread(_query_devices)

    @staticmethod
    async def get_usb_audio_devices() -> Dict[str, str]:
        devices = {}
        cards_path = Path('/proc/asound/cards')

        if not cards_path.exists():
            return devices

        try:
            async with aiofiles.open(cards_path, 'r') as f:
                content = await f.read()
                lines = content.splitlines()

            for i in range(0, len(lines), 2):
                if i + 1 < len(lines):
                    card_line = lines[i].strip()
                    name_line = lines[i + 1].strip()

                    if 'USB' in card_line or 'USB' in name_line:
                        card_num = card_line.split()[0]
                        card_name = card_line.split(']:')[1].strip() if ']:' in card_line else card_line
                        devices[f"card_{card_num}"] = card_name
        except Exception as e:
            logger.debug("Error reading USB audio devices: %s", e)

        return devices

    @staticmethod
    def validate_sample_rate(sample_rate: int, min_rate: int = 8000, max_rate: int = 192000) -> int:
        if sample_rate < min_rate:
            logger.warning("Sample rate %d too low, using %d", sample_rate, min_rate)
            return min_rate
        if sample_rate > max_rate:
            logger.warning("Sample rate %d too high, using %d", sample_rate, max_rate)
            return max_rate
        return sample_rate
