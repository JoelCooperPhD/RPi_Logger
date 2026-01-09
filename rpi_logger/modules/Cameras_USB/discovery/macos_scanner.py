import asyncio

from .platform_scanner import (
    VideoDevice,
    AudioDevice,
    match_audio_by_name,
    probe_video_devices_opencv,
    probe_audio_devices_sounddevice,
)


class MacOSScanner:
    def __init__(self):
        self._audio_cache: list[AudioDevice] | None = None

    async def scan_video_devices(self) -> list[VideoDevice]:
        devices = await probe_video_devices_opencv()

        enriched = []
        for dev in devices:
            name = await self._get_device_name_avfoundation(dev.index)
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

    async def _get_device_name_avfoundation(self, index: int) -> str | None:
        import subprocess

        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
                capture_output=True,
                text=True,
                timeout=5.0,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

        lines = result.stderr.split("\n")
        video_section = False
        current_index = 0

        for line in lines:
            if "AVFoundation video devices:" in line:
                video_section = True
                continue
            if "AVFoundation audio devices:" in line:
                break
            if video_section and "[" in line and "]" in line:
                if current_index == index:
                    start = line.find("]") + 1
                    return line[start:].strip()
                current_index += 1

        return None
