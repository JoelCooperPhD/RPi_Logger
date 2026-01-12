import sys
from dataclasses import dataclass
from typing import Protocol


@dataclass
class VideoDevice:
    index: int
    name: str
    platform_id: str


@dataclass
class AudioDevice:
    index: int
    name: str
    channels: int
    sample_rates: tuple[int, ...]


class DeviceScanner(Protocol):
    async def scan_video_devices(self) -> list[VideoDevice]: ...
    async def scan_audio_devices(self) -> list[AudioDevice]: ...
    async def match_audio_to_video(self, video: VideoDevice) -> AudioDevice | None: ...


def get_scanner() -> DeviceScanner:
    if sys.platform == 'darwin':
        from .macos_scanner import MacOSScanner
        return MacOSScanner()
    elif sys.platform == 'win32':
        from .windows_scanner import WindowsScanner
        return WindowsScanner()
    else:
        from .linux_scanner import LinuxScanner
        return LinuxScanner()


def match_audio_by_name(video_name: str, audio_devices: list[AudioDevice]) -> AudioDevice | None:
    keywords = [w.lower() for w in video_name.split() if len(w) > 3]

    for audio in audio_devices:
        audio_lower = audio.name.lower()
        for kw in keywords:
            if kw in audio_lower:
                return audio

    return audio_devices[0] if audio_devices else None


async def probe_video_devices_opencv() -> list[VideoDevice]:
    import asyncio
    import cv2

    devices = []

    def _probe():
        result = []
        for idx in range(10):
            # Use DirectShow on Windows to avoid MSMF/Orbbec issues
            if sys.platform == "win32":
                cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
            else:
                cap = cv2.VideoCapture(idx)

            if cap.isOpened():
                backend = cap.getBackendName()
                result.append(VideoDevice(
                    index=idx,
                    name=f"Camera {idx} ({backend})",
                    platform_id=str(idx),
                ))
                cap.release()
            else:
                cap.release()
                break
        return result

    devices = await asyncio.to_thread(_probe)
    return devices


async def probe_audio_devices_sounddevice() -> list[AudioDevice]:
    import asyncio

    def _probe():
        try:
            import sounddevice as sd
        except ImportError:
            return []

        devices = []
        all_devices = sd.query_devices()

        for idx, dev in enumerate(all_devices):
            if dev.get("max_input_channels", 0) > 0:
                devices.append(AudioDevice(
                    index=idx,
                    name=dev.get("name", f"Audio {idx}"),
                    channels=dev.get("max_input_channels", 2),
                    sample_rates=(44100, 48000),
                ))

        return devices

    return await asyncio.to_thread(_probe)
