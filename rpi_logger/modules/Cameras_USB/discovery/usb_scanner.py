import asyncio
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class USBVideoDevice:
    dev_path: str
    stable_id: str
    vid_pid: str
    display_name: str
    sysfs_path: str
    bus_path: str


async def scan_usb_cameras() -> list[USBVideoDevice]:
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

        bus_path = _extract_usb_bus_path(sysfs_path)
        if not bus_path:
            continue

        vid_pid = await _extract_vid_pid(sysfs_path)
        display_name = await _extract_display_name(sysfs_path)
        if not display_name:
            display_name = f"USB Camera ({vid_pid})" if vid_pid else "Unknown USB Camera"

        stable_id = f"usb:{bus_path}"

        devices.append(USBVideoDevice(
            dev_path=dev_path,
            stable_id=stable_id,
            vid_pid=vid_pid or "",
            display_name=display_name,
            sysfs_path=sysfs_path,
            bus_path=bus_path,
        ))

    return devices


def _extract_usb_bus_path(sysfs_path: str) -> Optional[str]:
    match = re.search(r'/usb\d+/(\d+-[\d.]+)', sysfs_path)
    return match.group(1) if match else None


async def _extract_vid_pid(sysfs_path: str) -> Optional[str]:
    usb_device_path = _find_usb_device_dir(sysfs_path)
    if not usb_device_path:
        return None

    vid_path = Path(usb_device_path) / "idVendor"
    pid_path = Path(usb_device_path) / "idProduct"

    try:
        vid = await asyncio.to_thread(vid_path.read_text)
        pid = await asyncio.to_thread(pid_path.read_text)
        return f"{vid.strip()}:{pid.strip()}"
    except (OSError, FileNotFoundError):
        return None


async def _extract_display_name(sysfs_path: str) -> Optional[str]:
    usb_device_path = _find_usb_device_dir(sysfs_path)
    if not usb_device_path:
        return None

    product_path = Path(usb_device_path) / "product"
    try:
        name = await asyncio.to_thread(product_path.read_text)
        return name.strip()
    except (OSError, FileNotFoundError):
        return None


def _find_usb_device_dir(sysfs_path: str) -> Optional[str]:
    path = Path(sysfs_path)
    while path != path.parent:
        if (path / "idVendor").exists() and (path / "idProduct").exists():
            return str(path)
        path = path.parent
    return None


async def get_device_by_path(dev_path: str) -> Optional[USBVideoDevice]:
    devices = await scan_usb_cameras()
    for device in devices:
        if device.dev_path == dev_path:
            return device
    return None


async def get_device_by_stable_id(stable_id: str) -> Optional[USBVideoDevice]:
    devices = await scan_usb_cameras()
    for device in devices:
        if device.stable_id == stable_id:
            return device
    return None
