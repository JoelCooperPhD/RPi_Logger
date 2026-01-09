import asyncio
import re
from pathlib import Path
from typing import Optional

from .platform_scanner import VideoDevice, AudioDevice


class LinuxScanner:
    async def scan_video_devices(self) -> list[VideoDevice]:
        devices = []
        video_dir = Path("/sys/class/video4linux")
        if not video_dir.exists():
            return devices

        for video_dev in video_dir.iterdir():
            if not video_dev.name.startswith("video"):
                continue

            dev_path = f"/dev/{video_dev.name}"
            device_link = video_dev / "device"
            if not device_link.exists():
                continue

            try:
                sysfs_path = str(device_link.resolve())
            except OSError:
                continue

            if "usb" not in sysfs_path.lower():
                continue

            index_path = video_dev / "index"
            if index_path.exists():
                try:
                    index = int(index_path.read_text().strip())
                    if index != 0:
                        continue
                except (ValueError, OSError):
                    pass

            bus_path = self._extract_usb_bus_path(sysfs_path)
            if not bus_path:
                continue

            display_name = await self._extract_display_name(sysfs_path)
            dev_index = self._dev_path_to_index(dev_path)

            devices.append(VideoDevice(
                index=dev_index,
                name=display_name or f"USB Camera ({dev_path})",
                platform_id=f"usb:{bus_path}",
            ))

        return devices

    async def scan_audio_devices(self) -> list[AudioDevice]:
        devices = []
        alsa_devices = await self._enumerate_alsa_capture_devices()

        for alsa_dev in alsa_devices:
            sd_index = await self._get_sounddevice_index(alsa_dev["card_index"])
            devices.append(AudioDevice(
                index=sd_index,
                name=alsa_dev["name"],
                channels=2,
                sample_rates=alsa_dev["sample_rates"],
            ))

        return devices

    async def match_audio_to_video(self, video: VideoDevice) -> AudioDevice | None:
        if not video.platform_id.startswith("usb:"):
            return None

        video_bus_path = video.platform_id[4:]
        alsa_devices = await self._enumerate_alsa_capture_devices()

        for alsa_dev in alsa_devices:
            if alsa_dev["bus_path"] == video_bus_path:
                sd_index = await self._get_sounddevice_index(alsa_dev["card_index"])
                return AudioDevice(
                    index=sd_index,
                    name=alsa_dev["name"],
                    channels=2,
                    sample_rates=alsa_dev["sample_rates"],
                )

        return None

    def _extract_usb_bus_path(self, sysfs_path: str) -> Optional[str]:
        match = re.search(r'/usb\d+/(\d+-[\d.]+)', sysfs_path)
        return match.group(1) if match else None

    def _dev_path_to_index(self, dev_path: str) -> int:
        match = re.search(r'video(\d+)', dev_path)
        return int(match.group(1)) if match else 0

    async def _extract_display_name(self, sysfs_path: str) -> Optional[str]:
        usb_device_path = self._find_usb_device_dir(sysfs_path)
        if not usb_device_path:
            return None

        product_path = Path(usb_device_path) / "product"
        try:
            name = await asyncio.to_thread(product_path.read_text)
            return name.strip()
        except (OSError, FileNotFoundError):
            return None

    def _find_usb_device_dir(self, sysfs_path: str) -> Optional[str]:
        path = Path(sysfs_path)
        while path != path.parent:
            if (path / "idVendor").exists() and (path / "idProduct").exists():
                return str(path)
            path = path.parent
        return None

    async def _enumerate_alsa_capture_devices(self) -> list[dict]:
        import subprocess

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
                card_name = match.group(3)

                bus_path = await self._get_audio_card_bus_path(card_idx)
                if bus_path:
                    devices.append({
                        "card_index": card_idx,
                        "name": card_name,
                        "bus_path": bus_path,
                        "sample_rates": (44100, 48000),
                    })

        return devices

    async def _get_audio_card_bus_path(self, card_index: int) -> Optional[str]:
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

    async def _get_sounddevice_index(self, card_index: int) -> int:
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
