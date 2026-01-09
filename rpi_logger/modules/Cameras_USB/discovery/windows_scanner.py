import asyncio

from .platform_scanner import (
    VideoDevice,
    AudioDevice,
    match_audio_by_name,
    probe_video_devices_opencv,
    probe_audio_devices_sounddevice,
)


class WindowsScanner:
    def __init__(self):
        self._audio_cache: list[AudioDevice] | None = None

    async def scan_video_devices(self) -> list[VideoDevice]:
        devices = await probe_video_devices_opencv()

        enriched = []
        for dev in devices:
            name = await self._get_device_name_dshow(dev.index)
            enriched.append(VideoDevice(
                index=dev.index,
                name=name or dev.name,
                platform_id=str(dev.index),
            ))

        return enriched

    async def scan_audio_devices(self) -> list[AudioDevice]:
        self._audio_cache = await probe_audio_devices_sounddevice()
        return self._audio_cache

    async def match_audio_to_video(self, video: VideoDevice) -> AudioDevice | None:
        if self._audio_cache is None:
            await self.scan_audio_devices()

        return match_audio_by_name(video.name, self._audio_cache or [])

    async def _get_device_name_dshow(self, index: int) -> str | None:
        import subprocess

        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["ffmpeg", "-f", "dshow", "-list_devices", "true", "-i", "dummy"],
                capture_output=True,
                text=True,
                timeout=5.0,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

        lines = result.stderr.split("\n")
        video_devices = []

        for line in lines:
            if "DirectShow video devices" in line:
                continue
            if "DirectShow audio devices" in line:
                break
            if '"' in line and "Alternative name" not in line:
                start = line.find('"') + 1
                end = line.rfind('"')
                if start < end:
                    video_devices.append(line[start:end])

        if index < len(video_devices):
            return video_devices[index]

        return None
