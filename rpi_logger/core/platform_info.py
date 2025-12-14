"""
Platform detection for RPi Logger.

Provides centralized platform detection that runs once at boot and caches
the result. This allows modules to be filtered by platform compatibility
and provides consistent platform information to all subprocesses.

Copyright (C) 2024-2025 Red Scientific

Licensed under the Apache License, Version 2.0
"""

import platform
import sys
from dataclasses import dataclass
from typing import Optional, Set

from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger("PlatformInfo")


@dataclass(frozen=True)
class PlatformInfo:
    """Immutable platform information detected at boot.

    This is the single source of truth for platform detection in the application.
    Detected once at startup and cached for the lifetime of the process.

    Attributes:
        platform: System platform ('linux', 'darwin', 'win32')
        architecture: CPU architecture ('x86_64', 'arm64', 'aarch64', 'armv7l')
        is_raspberry_pi: True if running on a Raspberry Pi
        pi_model: Raspberry Pi model string if applicable (e.g., 'Raspberry Pi 4 Model B')
        os_release: OS release version string
        python_version: Python version string
    """

    platform: str
    architecture: str
    is_raspberry_pi: bool
    pi_model: Optional[str]
    os_release: str
    python_version: str

    @property
    def platform_tags(self) -> Set[str]:
        """Return set of all platform tags this system matches.

        Tags are used for module compatibility filtering. A module declaring
        'platforms = linux,raspberry_pi' will match if any of those tags
        are in this set.

        Returns:
            Set of matching platform tags. Always includes '*' (matches all).
        """
        tags: Set[str] = {self.platform, "*"}
        if self.is_raspberry_pi:
            tags.add("raspberry_pi")
        return tags

    def supports(self, requirements: list[str]) -> bool:
        """Check if this platform meets the given requirements.

        Args:
            requirements: List of platform tags required (e.g., ['linux', 'raspberry_pi']).
                         Empty list or ['*'] means all platforms are supported.

        Returns:
            True if this platform matches any of the requirements.
        """
        if not requirements or "*" in requirements:
            return True
        return bool(self.platform_tags & set(requirements))

    def to_cli_args(self) -> list[str]:
        """Convert platform info to CLI arguments for subprocess launch.

        Returns:
            List of CLI argument strings to pass to subprocess.
        """
        args = [
            "--platform", self.platform,
            "--architecture", self.architecture,
        ]
        if self.is_raspberry_pi:
            args.append("--is-raspberry-pi")
        return args

    def __str__(self) -> str:
        """Human-readable platform description."""
        if self.is_raspberry_pi:
            return f"{self.pi_model or 'Raspberry Pi'} ({self.architecture})"
        return f"{self.platform} ({self.architecture})"


def _detect_raspberry_pi() -> tuple[bool, Optional[str]]:
    """Detect if running on a Raspberry Pi.

    Checks the device tree model file which is present on Raspberry Pi
    and other ARM single-board computers.

    Returns:
        Tuple of (is_raspberry_pi, model_string).
        model_string is None if not a Raspberry Pi.
    """
    model_paths = [
        "/proc/device-tree/model",
        "/sys/firmware/devicetree/base/model",
    ]

    for path in model_paths:
        try:
            with open(path, "r", encoding="utf-8") as f:
                model = f.read().strip().rstrip("\x00")
                if "raspberry pi" in model.lower():
                    return True, model
        except (FileNotFoundError, PermissionError, OSError):
            continue

    return False, None


def detect_platform() -> PlatformInfo:
    """Detect current platform information.

    This performs the actual detection and should only be called once.
    Use get_platform_info() to get the cached singleton instance.

    Returns:
        PlatformInfo instance with detected platform details.
    """
    # Detect Raspberry Pi on Linux
    is_pi = False
    pi_model = None
    if sys.platform == "linux":
        is_pi, pi_model = _detect_raspberry_pi()

    info = PlatformInfo(
        platform=sys.platform,
        architecture=platform.machine(),
        is_raspberry_pi=is_pi,
        pi_model=pi_model,
        os_release=platform.release(),
        python_version=platform.python_version(),
    )

    logger.info("Platform detected: %s", info)
    if is_pi:
        logger.info("Raspberry Pi model: %s", pi_model)

    return info


# Singleton instance
_platform_info: Optional[PlatformInfo] = None


def get_platform_info() -> PlatformInfo:
    """Get cached platform information (singleton).

    This is the primary entry point for platform detection. The detection
    runs once on first call and the result is cached for subsequent calls.

    Returns:
        PlatformInfo instance with detected platform details.
    """
    global _platform_info
    if _platform_info is None:
        _platform_info = detect_platform()
    return _platform_info


def reset_platform_info() -> None:
    """Reset the cached platform info (for testing only)."""
    global _platform_info
    _platform_info = None


__all__ = [
    "PlatformInfo",
    "get_platform_info",
    "detect_platform",
    "reset_platform_info",
]
