import asyncio
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..core.state import USBAudioDevice


@dataclass
class ALSAAudioDevice:
    card_index: int
    device_name: str
    bus_path: str
    channels: int
    sample_rates: tuple[int, ...]


async def match_audio_to_camera(camera_bus_path: str) -> Optional[USBAudioDevice]:
    audio_devices = await _enumerate_alsa_capture_devices()

    for device in audio_devices:
        if device.bus_path == camera_bus_path:
            sounddevice_idx = await _get_sounddevice_index(device.card_index)
            return USBAudioDevice(
                card_index=device.card_index,
                device_name=device.device_name,
                bus_path=device.bus_path,
                channels=device.channels,
                sample_rates=device.sample_rates,
                sounddevice_index=sounddevice_idx,
            )

    return None


async def _enumerate_alsa_capture_devices() -> list[ALSAAudioDevice]:
    devices = []

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["arecord", "-l"],
            capture_output=True,
            text=True,
            timeout=5.0,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return devices

    if result.returncode != 0:
        return devices

    card_pattern = re.compile(r"card (\d+): (\w+) \[([^\]]+)\].*device (\d+):")
    for line in result.stdout.split("\n"):
        match = card_pattern.search(line)
        if match:
            card_idx = int(match.group(1))
            card_id = match.group(2)
            card_name = match.group(3)

            bus_path = await _get_audio_card_bus_path(card_idx)
            if bus_path:
                sample_rates = await _probe_sample_rates(card_idx)
                devices.append(ALSAAudioDevice(
                    card_index=card_idx,
                    device_name=card_name,
                    bus_path=bus_path,
                    channels=2,
                    sample_rates=sample_rates,
                ))

    return devices


async def _get_audio_card_bus_path(card_index: int) -> Optional[str]:
    sysfs_path = Path(f"/sys/class/sound/card{card_index}/device")
    if not sysfs_path.exists():
        return None

    try:
        real_path = await asyncio.to_thread(lambda: sysfs_path.resolve())
        real_path_str = str(real_path)

        match = re.search(r'/usb\d+/(\d+-[\d.]+)', real_path_str)
        return match.group(1) if match else None
    except OSError:
        return None


async def _probe_sample_rates(card_index: int) -> tuple[int, ...]:
    rates = await _read_rates_from_proc(card_index)
    if rates:
        return rates

    rates = await _probe_rates_with_arecord(card_index)
    return rates if rates else (48000,)


async def _read_rates_from_proc(card_index: int) -> tuple[int, ...]:
    proc_path = Path(f"/proc/asound/card{card_index}/stream0")
    if not proc_path.exists():
        return ()

    try:
        content = await asyncio.to_thread(proc_path.read_text)
        rates = set()
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("Rates:"):
                rate_str = line.replace("Rates:", "").strip()
                for part in rate_str.split(","):
                    part = part.strip()
                    if part.isdigit():
                        rates.add(int(part))
        return tuple(sorted(rates)) if rates else ()
    except OSError:
        return ()


async def _probe_rates_with_arecord(card_index: int) -> tuple[int, ...]:
    standard_rates = (16000, 22050, 24000, 32000, 44100, 48000)
    supported = []

    for rate in standard_rates:
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                [
                    "arecord", "-D", f"hw:{card_index},0",
                    "-r", str(rate), "-c", "1", "-f", "S16_LE",
                    "-d", "0", "--dump-hw-params"
                ],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            if str(rate) in result.stderr or str(rate) in result.stdout:
                supported.append(rate)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    return tuple(supported)


async def _get_sounddevice_index(card_index: int) -> int:
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        for idx, dev in enumerate(devices):
            if dev.get("max_input_channels", 0) > 0:
                name = dev.get("name", "")
                if f"hw:{card_index}" in name or f"Card {card_index}" in name:
                    return idx
    except Exception:
        pass

    return card_index


async def list_all_audio_devices() -> list[ALSAAudioDevice]:
    return await _enumerate_alsa_capture_devices()
