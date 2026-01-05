"""Hardware Detection Framework.

Detects available hardware for testing purposes and generates availability matrix.
Each module's hardware dependency is documented and tested.

Usage:
    from hardware_detection import HardwareAvailability

    hw = HardwareAvailability()
    print(hw.availability_matrix())

    if hw.is_available("GPS"):
        # Run GPS tests
        pass
"""

from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class DeviceType(Enum):
    """Types of hardware devices."""
    GPS_SERIAL = auto()
    DRT_SDRT = auto()
    DRT_WDRT = auto()
    VOG_SVOG = auto()
    VOG_WVOG = auto()
    EYETRACKER_NEON = auto()
    AUDIO_INPUT = auto()
    CAMERA_USB = auto()
    CAMERA_CSI = auto()


@dataclass
class DeviceInfo:
    """Information about a detected device."""
    device_type: DeviceType
    available: bool
    device_path: Optional[str] = None
    device_name: Optional[str] = None
    reason: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ModuleAvailability:
    """Availability information for a module."""
    module_name: str
    available: bool
    devices: List[DeviceInfo] = field(default_factory=list)
    reason: str = ""
    can_be_mocked: bool = True


class HardwareAvailability:
    """Detects and reports hardware availability for testing.

    This class probes for various hardware devices required by Logger modules
    and provides a unified interface for test code to check availability.
    """

    # Known USB VID/PID combinations for devices
    KNOWN_DEVICES = {
        # DRT devices
        DeviceType.DRT_SDRT: [
            (0x2341, 0x0043),  # Arduino Uno
            (0x2341, 0x8036),  # Arduino Leonardo
            (0x1a86, 0x7523),  # CH340 (common Arduino clone)
        ],
        DeviceType.DRT_WDRT: [
            (0xf057, 0x08AE),  # MicroPython Pyboard (wDRT firmware)
        ],
        # VOG devices
        DeviceType.VOG_SVOG: [
            (0x2341, 0x0043),  # Arduino Uno
            (0x2341, 0x8036),  # Arduino Leonardo
            (0x1a86, 0x7523),  # CH340 (common Arduino clone)
        ],
        DeviceType.VOG_WVOG: [
            (0xf057, 0x08AE),  # MicroPython Pyboard (wVOG firmware)
        ],
        # GPS devices (common USB GPS dongles)
        DeviceType.GPS_SERIAL: [
            (0x1546, 0x01a7),  # U-Blox 7
            (0x1546, 0x01a8),  # U-Blox 8
            (0x067b, 0x2303),  # Prolific PL2303 (common GPS adapter)
            (0x10c4, 0xea60),  # CP210x (common GPS adapter)
        ],
    }

    def __init__(self):
        """Initialize hardware detection."""
        self._cache: Dict[str, ModuleAvailability] = {}
        self._detected = False

    def detect_all(self) -> None:
        """Run hardware detection for all modules."""
        self._cache = {
            "GPS": self._detect_gps(),
            "DRT": self._detect_drt(),
            "VOG": self._detect_vog(),
            "EyeTracker": self._detect_eyetracker(),
            "Audio": self._detect_audio(),
            "Cameras": self._detect_cameras(),
            "CSICameras": self._detect_csi_cameras(),
            "Notes": ModuleAvailability(
                module_name="Notes",
                available=True,
                reason="No hardware required",
            ),
        }
        self._detected = True

    def get_availability(self, module_name: str) -> ModuleAvailability:
        """Get availability info for a specific module."""
        if not self._detected:
            self.detect_all()
        return self._cache.get(module_name, ModuleAvailability(
            module_name=module_name,
            available=False,
            reason=f"Unknown module: {module_name}",
        ))

    def is_available(self, module_name: str) -> bool:
        """Check if a module's hardware is available."""
        return self.get_availability(module_name).available

    def get_testable_modules(self) -> List[str]:
        """Get list of modules that can be tested."""
        if not self._detected:
            self.detect_all()
        return [name for name, avail in self._cache.items() if avail.available]

    def get_untestable_modules(self) -> List[str]:
        """Get list of modules that cannot be tested."""
        if not self._detected:
            self.detect_all()
        return [name for name, avail in self._cache.items() if not avail.available]

    def availability_matrix(self) -> str:
        """Generate human-readable availability matrix."""
        if not self._detected:
            self.detect_all()

        lines = [
            "=== HARDWARE AVAILABILITY MATRIX ===",
            "",
            f"{'Module':<14} | {'Device Type':<20} | {'Available':<10} | Reason",
            "-" * 80,
        ]

        for module_name, avail in self._cache.items():
            if avail.devices:
                for device in avail.devices:
                    status = "YES" if device.available else "NO"
                    lines.append(
                        f"{module_name:<14} | {device.device_type.name:<20} | {status:<10} | {device.reason or device.device_name or '-'}"
                    )
            else:
                status = "YES" if avail.available else "NO"
                lines.append(
                    f"{module_name:<14} | {'-':<20} | {status:<10} | {avail.reason}"
                )

        lines.append("-" * 80)

        testable = self.get_testable_modules()
        untestable = self.get_untestable_modules()

        lines.append(f"TESTABLE MODULES: {', '.join(testable) if testable else 'None'}")
        lines.append(f"UNTESTABLE MODULES: {', '.join(untestable) if untestable else 'None'}")

        return "\n".join(lines)

    # =========================================================================
    # Detection Methods
    # =========================================================================

    def _detect_gps(self) -> ModuleAvailability:
        """Detect GPS serial devices."""
        devices = []

        # Check for known GPS VID/PIDs
        serial_ports = self._list_serial_ports()
        for port_path, vid, pid, name in serial_ports:
            if (vid, pid) in self.KNOWN_DEVICES.get(DeviceType.GPS_SERIAL, []):
                devices.append(DeviceInfo(
                    device_type=DeviceType.GPS_SERIAL,
                    available=True,
                    device_path=port_path,
                    device_name=name,
                    reason="Known GPS device detected",
                ))

        # Also check for common GPS port patterns
        gps_patterns = ["/dev/ttyUSB*", "/dev/ttyACM*", "/dev/serial0"]
        for pattern in gps_patterns:
            for port in Path("/dev").glob(pattern.replace("/dev/", "")):
                port_str = str(port)
                if not any(d.device_path == port_str for d in devices):
                    # Could be a GPS device, mark as potential
                    devices.append(DeviceInfo(
                        device_type=DeviceType.GPS_SERIAL,
                        available=True,
                        device_path=port_str,
                        reason="Potential GPS serial port",
                    ))

        if devices:
            available_devices = [d for d in devices if d.available]
            return ModuleAvailability(
                module_name="GPS",
                available=len(available_devices) > 0,
                devices=devices,
                reason=f"{len(available_devices)} GPS device(s) detected",
            )

        return ModuleAvailability(
            module_name="GPS",
            available=False,
            reason="No GPS device detected",
            can_be_mocked=True,
        )

    def _detect_drt(self) -> ModuleAvailability:
        """Detect DRT devices (sDRT and wDRT)."""
        devices = []
        serial_ports = self._list_serial_ports()

        # Check for wDRT (Pyboard)
        for port_path, vid, pid, name in serial_ports:
            if (vid, pid) in self.KNOWN_DEVICES.get(DeviceType.DRT_WDRT, []):
                devices.append(DeviceInfo(
                    device_type=DeviceType.DRT_WDRT,
                    available=True,
                    device_path=port_path,
                    device_name=name,
                    reason="wDRT Pyboard detected",
                ))
            elif (vid, pid) in self.KNOWN_DEVICES.get(DeviceType.DRT_SDRT, []):
                devices.append(DeviceInfo(
                    device_type=DeviceType.DRT_SDRT,
                    available=True,
                    device_path=port_path,
                    device_name=name,
                    reason="Potential sDRT Arduino detected",
                ))

        if devices:
            available_devices = [d for d in devices if d.available]
            return ModuleAvailability(
                module_name="DRT",
                available=len(available_devices) > 0,
                devices=devices,
                reason=f"{len(available_devices)} DRT device(s) detected",
            )

        return ModuleAvailability(
            module_name="DRT",
            available=False,
            reason="No DRT device detected (no matching VID/PID)",
            can_be_mocked=True,
        )

    def _detect_vog(self) -> ModuleAvailability:
        """Detect VOG devices (sVOG and wVOG)."""
        devices = []
        serial_ports = self._list_serial_ports()

        # Check for wVOG (Pyboard)
        for port_path, vid, pid, name in serial_ports:
            if (vid, pid) in self.KNOWN_DEVICES.get(DeviceType.VOG_WVOG, []):
                devices.append(DeviceInfo(
                    device_type=DeviceType.VOG_WVOG,
                    available=True,
                    device_path=port_path,
                    device_name=name,
                    reason="wVOG Pyboard detected",
                ))
            elif (vid, pid) in self.KNOWN_DEVICES.get(DeviceType.VOG_SVOG, []):
                devices.append(DeviceInfo(
                    device_type=DeviceType.VOG_SVOG,
                    available=True,
                    device_path=port_path,
                    device_name=name,
                    reason="Potential sVOG Arduino detected",
                ))

        if devices:
            available_devices = [d for d in devices if d.available]
            return ModuleAvailability(
                module_name="VOG",
                available=len(available_devices) > 0,
                devices=devices,
                reason=f"{len(available_devices)} VOG device(s) detected",
            )

        return ModuleAvailability(
            module_name="VOG",
            available=False,
            reason="No VOG device detected (no matching VID/PID)",
            can_be_mocked=True,
        )

    def _detect_eyetracker(self) -> ModuleAvailability:
        """Detect Pupil Labs Neon eye tracker."""
        devices = []

        # Try to discover Neon via network
        try:
            # Simple check: try to import the library
            import pupil_labs.realtime_api  # noqa: F401

            # Try to find a device on the network
            # This is a simplified check - real discovery would use their API
            devices.append(DeviceInfo(
                device_type=DeviceType.EYETRACKER_NEON,
                available=False,  # Need actual network discovery
                reason="Pupil Labs API available, network discovery required",
            ))

        except ImportError:
            return ModuleAvailability(
                module_name="EyeTracker",
                available=False,
                reason="pupil_labs.realtime_api not installed",
                can_be_mocked=True,
            )

        # For now, mark as unavailable unless we do actual discovery
        return ModuleAvailability(
            module_name="EyeTracker",
            available=False,
            devices=devices,
            reason="Network discovery not implemented in test",
            can_be_mocked=True,
        )

    def _detect_audio(self) -> ModuleAvailability:
        """Detect audio input devices."""
        devices = []

        try:
            import sounddevice as sd

            input_devices = sd.query_devices(kind='input')

            if isinstance(input_devices, dict):
                # Single device
                devices.append(DeviceInfo(
                    device_type=DeviceType.AUDIO_INPUT,
                    available=True,
                    device_name=input_devices.get('name', 'Unknown'),
                    extra={'index': input_devices.get('index'), 'channels': input_devices.get('max_input_channels')},
                ))
            elif input_devices:
                # No default input device
                # Query all devices and filter input
                all_devices = sd.query_devices()
                for idx, dev in enumerate(all_devices):
                    if dev.get('max_input_channels', 0) > 0:
                        devices.append(DeviceInfo(
                            device_type=DeviceType.AUDIO_INPUT,
                            available=True,
                            device_name=dev.get('name', 'Unknown'),
                            extra={'index': idx, 'channels': dev.get('max_input_channels')},
                        ))

        except ImportError:
            return ModuleAvailability(
                module_name="Audio",
                available=False,
                reason="sounddevice not installed",
                can_be_mocked=True,
            )
        except Exception as e:
            return ModuleAvailability(
                module_name="Audio",
                available=False,
                reason=f"Error querying audio devices: {e}",
                can_be_mocked=True,
            )

        if devices:
            return ModuleAvailability(
                module_name="Audio",
                available=True,
                devices=devices,
                reason=f"{len(devices)} audio input device(s) detected",
            )

        return ModuleAvailability(
            module_name="Audio",
            available=False,
            reason="No audio input devices found",
            can_be_mocked=True,
        )

    def _detect_cameras(self) -> ModuleAvailability:
        """Detect USB webcams."""
        devices = []

        # Check for video devices on Linux
        video_devices = list(Path("/dev").glob("video*"))

        for video_path in video_devices:
            # Filter to only capture devices (not metadata devices)
            try:
                # On Linux, even-numbered video devices are usually capture
                device_num = int(video_path.name.replace("video", ""))
                if device_num % 2 == 0:  # Capture device
                    device_name = self._get_v4l2_device_name(str(video_path))
                    devices.append(DeviceInfo(
                        device_type=DeviceType.CAMERA_USB,
                        available=True,
                        device_path=str(video_path),
                        device_name=device_name or f"Camera {device_num}",
                    ))
            except ValueError:
                continue

        if devices:
            return ModuleAvailability(
                module_name="Cameras",
                available=True,
                devices=devices,
                reason=f"{len(devices)} USB camera(s) detected",
            )

        return ModuleAvailability(
            module_name="Cameras",
            available=False,
            reason="No USB cameras detected",
            can_be_mocked=True,
        )

    def _detect_csi_cameras(self) -> ModuleAvailability:
        """Detect Raspberry Pi CSI cameras."""
        devices = []

        # Check if we're on a Raspberry Pi
        if not self._is_raspberry_pi():
            return ModuleAvailability(
                module_name="CSICameras",
                available=False,
                reason="Not running on Raspberry Pi platform",
                can_be_mocked=True,
            )

        # Try to detect CSI cameras via libcamera
        try:
            result = subprocess.run(
                ["libcamera-hello", "--list-cameras"],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode == 0 and "Available cameras" in result.stdout:
                # Parse camera list
                for line in result.stdout.split("\n"):
                    if line.strip().startswith(("0 :", "1 :", "2 :", "3 :")):
                        devices.append(DeviceInfo(
                            device_type=DeviceType.CAMERA_CSI,
                            available=True,
                            device_name=line.strip(),
                        ))

        except FileNotFoundError:
            return ModuleAvailability(
                module_name="CSICameras",
                available=False,
                reason="libcamera-hello not found",
                can_be_mocked=True,
            )
        except subprocess.TimeoutExpired:
            return ModuleAvailability(
                module_name="CSICameras",
                available=False,
                reason="libcamera-hello timed out",
                can_be_mocked=True,
            )
        except Exception as e:
            return ModuleAvailability(
                module_name="CSICameras",
                available=False,
                reason=f"Error detecting CSI cameras: {e}",
                can_be_mocked=True,
            )

        if devices:
            return ModuleAvailability(
                module_name="CSICameras",
                available=True,
                devices=devices,
                reason=f"{len(devices)} CSI camera(s) detected",
            )

        return ModuleAvailability(
            module_name="CSICameras",
            available=False,
            reason="No CSI cameras detected",
            can_be_mocked=True,
        )

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def _list_serial_ports(self) -> List[Tuple[str, int, int, str]]:
        """List available serial ports with VID/PID.

        Returns:
            List of tuples: (port_path, vid, pid, device_name)
        """
        ports = []

        try:
            import serial.tools.list_ports

            for port in serial.tools.list_ports.comports():
                vid = port.vid or 0
                pid = port.pid or 0
                ports.append((port.device, vid, pid, port.description or ""))

        except ImportError:
            # Fallback: scan /dev for serial ports
            for pattern in ["ttyUSB*", "ttyACM*"]:
                for port in Path("/dev").glob(pattern):
                    ports.append((str(port), 0, 0, ""))

        return ports

    def _get_v4l2_device_name(self, device_path: str) -> Optional[str]:
        """Get camera name from V4L2 device."""
        try:
            result = subprocess.run(
                ["v4l2-ctl", "--device", device_path, "--info"],
                capture_output=True,
                text=True,
                timeout=2,
            )

            if result.returncode == 0:
                for line in result.stdout.split("\n"):
                    if "Card type" in line:
                        return line.split(":", 1)[-1].strip()

        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        return None

    def _is_raspberry_pi(self) -> bool:
        """Check if running on Raspberry Pi."""
        # Check /proc/cpuinfo for Raspberry Pi
        try:
            with open("/proc/cpuinfo", "r") as f:
                cpuinfo = f.read().lower()
                return "raspberry" in cpuinfo or "bcm" in cpuinfo
        except (FileNotFoundError, PermissionError):
            pass

        # Check /proc/device-tree/model
        try:
            with open("/proc/device-tree/model", "r") as f:
                model = f.read().lower()
                return "raspberry" in model
        except (FileNotFoundError, PermissionError):
            pass

        return False


# =============================================================================
# Pytest Integration
# =============================================================================

# Global instance for pytest markers
_hw_availability: Optional[HardwareAvailability] = None


def get_hardware_availability() -> HardwareAvailability:
    """Get or create global hardware availability instance."""
    global _hw_availability
    if _hw_availability is None:
        _hw_availability = HardwareAvailability()
        _hw_availability.detect_all()
    return _hw_availability


def requires_hardware(module_name: str):
    """Pytest marker decorator to skip tests if hardware unavailable.

    Usage:
        @requires_hardware("GPS")
        def test_gps_data():
            ...
    """
    import pytest

    hw = get_hardware_availability()
    avail = hw.get_availability(module_name)

    return pytest.mark.skipif(
        not avail.available,
        reason=f"Hardware unavailable: {avail.reason}"
    )


# =============================================================================
# CLI Entry Point
# =============================================================================

def main():
    """CLI entry point for hardware detection."""
    hw = HardwareAvailability()
    hw.detect_all()
    print(hw.availability_matrix())


if __name__ == "__main__":
    main()
