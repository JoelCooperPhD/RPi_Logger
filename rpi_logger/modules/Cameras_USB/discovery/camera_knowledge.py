"""Camera knowledge database - single source of truth for camera capabilities.

Keyed by VID:PID (camera model identifier), not USB port path.
Once a camera is probed, its capabilities are stored permanently.
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
import logging

logger = logging.getLogger(__name__)

# Known camera resolution limits (VID:PID -> max resolution)
# Cameras that have issues at certain resolutions
RESOLUTION_LIMITS: dict[str, tuple[int, int]] = {
    "0c45:6366": (1280, 720),  # Arducam - freezes at 1080p
}


@dataclass
class CameraProfile:
    vid_pid: str
    display_name: str
    modes: list[dict[str, Any]]
    max_resolution: Optional[tuple[int, int]]
    default_resolution: tuple[int, int]
    default_fps: float
    probed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "display_name": self.display_name,
            "modes": self.modes,
            "max_resolution": list(self.max_resolution) if self.max_resolution else None,
            "default_resolution": list(self.default_resolution),
            "default_fps": self.default_fps,
            "probed_at": self.probed_at,
        }

    @classmethod
    def from_dict(cls, vid_pid: str, data: dict[str, Any]) -> "CameraProfile":
        max_res = data.get("max_resolution")
        return cls(
            vid_pid=vid_pid,
            display_name=data.get("display_name", f"USB Camera ({vid_pid})"),
            modes=data.get("modes", []),
            max_resolution=tuple(max_res) if max_res else None,
            default_resolution=tuple(data.get("default_resolution", [640, 480])),
            default_fps=data.get("default_fps", 30.0),
            probed_at=data.get("probed_at", ""),
        )


class CameraKnowledge:
    """Single source of truth for what cameras can do."""

    def __init__(self, path: Path):
        self._path = path
        self._profiles: dict[str, CameraProfile] = {}
        self._loaded = False
        self._lock = asyncio.Lock()

    async def load(self) -> None:
        if self._loaded:
            return
        async with self._lock:
            if self._loaded:
                return
            self._profiles = await asyncio.to_thread(self._read_file)
            self._loaded = True
            logger.debug("Loaded %d camera profiles", len(self._profiles))

    def _read_file(self) -> dict[str, CameraProfile]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text("utf-8"))
            profiles = {}
            for vid_pid, entry in data.items():
                if isinstance(entry, dict):
                    profiles[vid_pid] = CameraProfile.from_dict(vid_pid, entry)
            return profiles
        except Exception as e:
            logger.warning("Failed to read camera knowledge: %s", e)
            return {}

    async def _save(self) -> None:
        data = {vid_pid: p.to_dict() for vid_pid, p in self._profiles.items()}
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(
                self._path.write_text, json.dumps(data, indent=2), "utf-8"
            )
        except Exception as e:
            logger.warning("Failed to save camera knowledge: %s", e)

    async def get(self, vid_pid: str) -> Optional[CameraProfile]:
        """Get camera profile by VID:PID."""
        await self.load()
        return self._profiles.get(vid_pid)

    async def register(self, profile: CameraProfile) -> None:
        """Store a camera profile after probing."""
        await self.load()
        async with self._lock:
            self._profiles[profile.vid_pid] = profile
            await self._save()
            logger.info("Registered camera %s: %s (%d modes)",
                       profile.vid_pid, profile.display_name, len(profile.modes))

    def get_modes(self, vid_pid: str) -> list[dict[str, Any]]:
        """Get available modes for a camera (sync, for UI).

        Returns modes filtered by any resolution limits.
        Must call load() first.
        """
        profile = self._profiles.get(vid_pid)
        if not profile:
            return []
        return profile.modes  # Already filtered at registration time

    @staticmethod
    def get_resolution_limit(vid_pid: str) -> Optional[tuple[int, int]]:
        """Get max resolution for a camera if it has known issues."""
        return RESOLUTION_LIMITS.get(vid_pid)

    @staticmethod
    def filter_modes(modes: list[dict], vid_pid: str) -> list[dict]:
        """Filter modes by resolution limit for a specific camera."""
        limit = RESOLUTION_LIMITS.get(vid_pid)
        if not limit:
            return modes
        max_pixels = limit[0] * limit[1]
        return [
            m for m in modes
            if m.get("size", (0, 0))[0] * m.get("size", (0, 0))[1] <= max_pixels
        ]

    @staticmethod
    def create_profile_from_probe(
        vid_pid: str,
        display_name: str,
        probed_modes: list[dict],
    ) -> CameraProfile:
        """Create a camera profile from probe results, applying resolution limits."""
        # Filter modes by known limits
        modes = CameraKnowledge.filter_modes(probed_modes, vid_pid)
        if not modes and probed_modes:
            # If filtering removed everything, keep the smallest mode
            modes = [min(probed_modes, key=lambda m: m.get("size", (0, 0))[0])]

        # Determine defaults
        default_resolution = (640, 480)
        default_fps = 30.0
        for mode in modes:
            size = mode.get("size", (0, 0))
            fps = mode.get("fps", 0)
            if size == (640, 480) and fps >= 30:
                default_resolution = size
                default_fps = fps
                break

        return CameraProfile(
            vid_pid=vid_pid,
            display_name=display_name,
            modes=modes,
            max_resolution=RESOLUTION_LIMITS.get(vid_pid),
            default_resolution=default_resolution,
            default_fps=default_fps,
            probed_at=datetime.now().isoformat(),
        )
