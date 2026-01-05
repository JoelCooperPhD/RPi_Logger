"""Audio configuration."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from rpi_logger.cli.common import add_common_cli_arguments
from rpi_logger.modules.base.preferences import ScopedPreferences

INTERACTION_MODES: tuple[str, str] = ("gui", "headless")


@dataclass(slots=True)
class AudioSettings:
    """Audio configuration settings."""
    mode: str = "gui"
    output_dir: Path = Path("audio")
    session_prefix: str = "audio"
    log_level: str = "debug"
    log_file: Path | None = None
    enable_commands: bool = False
    sample_rate: int = 48_000
    console_output: bool = False
    meter_refresh_interval: float = 0.08
    recorder_start_timeout: float = 3.0
    recorder_stop_timeout: float = 2.0
    shutdown_timeout: float = 15.0

    @classmethod
    def from_args(cls, args: Any) -> "AudioSettings":
        defaults = cls()

        output_dir = getattr(args, "output_dir", None)
        if not isinstance(output_dir, Path):
            output_dir = Path(str(output_dir or defaults.output_dir))

        session_prefix = getattr(args, "session_prefix", defaults.session_prefix) or defaults.session_prefix

        mode = _normalize_mode(getattr(args, "mode", defaults.mode))

        return cls(
            mode=mode,
            output_dir=output_dir,
            session_prefix=str(session_prefix),
            log_level=str(getattr(args, "log_level", defaults.log_level)),
            log_file=getattr(args, "log_file", None),
            enable_commands=bool(getattr(args, "enable_commands", defaults.enable_commands)),
            sample_rate=int(getattr(args, "sample_rate", defaults.sample_rate)),
            console_output=bool(getattr(args, "console_output", defaults.console_output)),
            meter_refresh_interval=float(getattr(args, "meter_refresh_interval", defaults.meter_refresh_interval)),
            recorder_start_timeout=float(getattr(args, "recorder_start_timeout", defaults.recorder_start_timeout)),
            recorder_stop_timeout=float(getattr(args, "recorder_stop_timeout", defaults.recorder_stop_timeout)),
            shutdown_timeout=float(getattr(args, "shutdown_timeout", defaults.shutdown_timeout)),
        )

    @classmethod
    def from_preferences(cls, prefs: ScopedPreferences, args: Any) -> "AudioSettings":
        base = cls.from_args(args)
        merged = asdict(base)

        def _maybe_update(key: str, cast):
            stored = prefs.get(key)
            if stored is None:
                return
            try:
                merged[key] = cast(stored)
            except Exception:
                return

        _maybe_update("session_prefix", str)
        _maybe_update("log_level", str)
        _maybe_update("sample_rate", int)
        _maybe_update("console_output", bool)
        _maybe_update("output_dir", lambda value: Path(value))

        settings = cls(**merged)
        return settings

def read_config_file(path: Path) -> dict[str, object]:
    config: dict[str, object] = {}
    if not path.exists():
        return config

    text = path.read_text(encoding="utf-8")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = [part.strip() for part in line.split("=", 1)]
        if not key:
            continue
        lowered = value.lower()
        if lowered in {"true", "yes", "on"}:
            config[key] = True
        elif lowered in {"false", "no", "off"}:
            config[key] = False
        else:
            try:
                if "." in value:
                    config[key] = float(value)
                else:
                    config[key] = int(value)
            except ValueError:
                config[key] = value
    return config


def _config_value(config: Mapping[str, object], key: str, fallback: Any) -> Any:
    value = config.get(key, fallback)
    if isinstance(value, str) and (
        isinstance(fallback, Path)
        or key.endswith("_dir")
        or key.endswith("_file")
    ):
        return Path(value)
    if isinstance(fallback, Path):
        return Path(str(value))
    return value


def build_arg_parser(config: Mapping[str, object]) -> argparse.ArgumentParser:
    defaults = AudioSettings()
    parser = argparse.ArgumentParser(description="Audio module")

    default_mode = _normalize_mode(_config_value(config, "mode", defaults.mode))
    add_common_cli_arguments(
        parser,
        default_output=_config_value(config, "output_dir", defaults.output_dir),
        allowed_modes=list(INTERACTION_MODES),
        default_mode=default_mode,
        include_session_prefix=True,
        default_session_prefix=_config_value(config, "session_prefix", defaults.session_prefix),
        include_console_control=True,
        default_console_output=bool(_config_value(config, "console_output", defaults.console_output)),
        include_auto_recording=False,
        include_parent_control=True,
        include_window_geometry=True,
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=_config_value(config, "sample_rate", defaults.sample_rate),
        help="Sample rate (Hz) for input streams",
    )

    return parser


def parse_cli_args(argv: list[str] | None = None, *, config_path: Path) -> argparse.Namespace:
    config = read_config_file(config_path)
    parser = build_arg_parser(config)
    return parser.parse_args(argv)


def _normalize_mode(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text == "cli":
        return "headless"
    return text if text in INTERACTION_MODES else INTERACTION_MODES[0]
