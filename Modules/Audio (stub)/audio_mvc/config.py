"""Configuration helpers for the Audio (Stub) module."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class AudioStubConfig:
    """Normalized configuration derived from CLI args + config file."""

    mode: str
    output_dir: Path
    session_prefix: str
    log_level: str
    log_file: Path | None
    enable_commands: bool
    window_geometry: str | None
    sample_rate: int = 48_000
    discovery_timeout: float = 5.0
    discovery_retry: float = 3.0
    auto_select_new: bool = False
    auto_start_recording: bool = False
    console_output: bool = False
    meter_refresh_interval: float = 0.08
    device_scan_interval: float = 3.0
    recorder_start_timeout: float = 3.0
    recorder_stop_timeout: float = 2.0
    shutdown_timeout: float = 15.0

    @classmethod
    def from_args(cls, args: Any) -> "AudioStubConfig":
        output_dir = getattr(args, "output_dir", None)
        if not isinstance(output_dir, Path):
            output_dir = Path(str(output_dir or "audio-stub"))

        session_prefix = str(getattr(args, "session_prefix", "audio_stub") or "audio_stub")

        return cls(
            mode=str(getattr(args, "mode", "gui")),
            output_dir=output_dir,
            session_prefix=session_prefix,
            log_level=str(getattr(args, "log_level", "info")),
            log_file=getattr(args, "log_file", None),
            enable_commands=bool(getattr(args, "enable_commands", False)),
            window_geometry=getattr(args, "window_geometry", None),
            sample_rate=int(getattr(args, "sample_rate", 48_000)),
            discovery_timeout=float(getattr(args, "discovery_timeout", 5.0)),
            discovery_retry=float(getattr(args, "discovery_retry", 3.0)),
            auto_select_new=bool(getattr(args, "auto_select_new", False)),
            auto_start_recording=bool(getattr(args, "auto_start_recording", False)),
            console_output=bool(getattr(args, "console_output", False)),
        )
