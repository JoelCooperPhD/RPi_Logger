"""Platform capability detection for optimization selection."""

import os
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional


@dataclass(frozen=True)
class PlatformCapabilities:
    """Detected platform capabilities."""
    is_raspberry_pi: bool
    pi_model: Optional[str]  # e.g., "Raspberry Pi 5 Model B"
    cpu_cores: int
    has_nvenc: bool  # NVIDIA hardware encoder (desktop only)


@lru_cache(maxsize=1)
def detect_platform() -> PlatformCapabilities:
    """Detect platform capabilities (cached)."""
    is_pi = False
    pi_model = None
    has_nvenc = False

    # Check for Raspberry Pi
    try:
        with open('/proc/device-tree/model', 'r') as f:
            model = f.read().strip('\x00').strip()
            if 'Raspberry Pi' in model:
                is_pi = True
                pi_model = model
    except (FileNotFoundError, PermissionError):
        pass

    # Check CPU cores
    try:
        cpu_cores = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        cpu_cores = os.cpu_count() or 1

    # Check for NVENC (desktop only - Pi 5 has no hardware encoder)
    if not is_pi:
        try:
            result = subprocess.run(
                ['ffmpeg', '-hide_banner', '-encoders'],
                capture_output=True, text=True, timeout=5
            )
            has_nvenc = 'h264_nvenc' in result.stdout
        except Exception:
            pass

    return PlatformCapabilities(
        is_raspberry_pi=is_pi,
        pi_model=pi_model,
        cpu_cores=cpu_cores,
        has_nvenc=has_nvenc,
    )
