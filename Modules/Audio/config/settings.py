"""Configuration loading + normalization helpers for the audio module."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional


INTERACTION_MODES: tuple[str, str] = ("gui", "cli")


@dataclass(slots=True)
class AudioSettings:
    """Normalized configuration derived from CLI args and config file."""

    mode: str = "gui"
    output_dir: Path = Path("audio")
    session_prefix: str = "audio"
    log_level: str = "debug"
    log_file: Path | None = None
    enable_commands: bool = False
    window_geometry: str | None = None
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
    def from_args(cls, args: Any) -> "AudioSettings":
        """Create a settings instance from an argparse namespace."""

        def _to_bool(value: Any) -> bool:
            return bool(value)

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
            enable_commands=_to_bool(getattr(args, "enable_commands", defaults.enable_commands)),
            window_geometry=getattr(args, "window_geometry", None),
            sample_rate=int(getattr(args, "sample_rate", defaults.sample_rate)),
            discovery_timeout=float(getattr(args, "discovery_timeout", defaults.discovery_timeout)),
            discovery_retry=float(getattr(args, "discovery_retry", defaults.discovery_retry)),
            auto_select_new=_to_bool(getattr(args, "auto_select_new", defaults.auto_select_new)),
            auto_start_recording=_to_bool(
                getattr(args, "auto_start_recording", defaults.auto_start_recording)
            ),
            console_output=_to_bool(getattr(args, "console_output", defaults.console_output)),
            meter_refresh_interval=float(
                getattr(args, "meter_refresh_interval", defaults.meter_refresh_interval)
            ),
            device_scan_interval=float(
                getattr(args, "device_scan_interval", defaults.device_scan_interval)
            ),
            recorder_start_timeout=float(
                getattr(args, "recorder_start_timeout", defaults.recorder_start_timeout)
            ),
            recorder_stop_timeout=float(
                getattr(args, "recorder_stop_timeout", defaults.recorder_stop_timeout)
            ),
            shutdown_timeout=float(getattr(args, "shutdown_timeout", defaults.shutdown_timeout)),
        )


def read_config_file(path: Path) -> dict[str, object]:
    """Load key/value pairs from ``config.txt`` style files."""

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
    """Create the CLI parser with defaults sourced from the config file."""

    defaults = AudioSettings()
    parser = argparse.ArgumentParser(description="Audio module")

    default_mode = _normalize_mode(_config_value(config, "mode", defaults.mode))

    parser.add_argument(
        "--mode",
        choices=INTERACTION_MODES,
        default=default_mode,
        help="Interaction mode: 'gui' enables the Tk panel, 'cli' runs command-line controls only",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_config_value(config, "output_dir", defaults.output_dir),
        help="Session root provided by the module manager",
    )
    parser.add_argument(
        "--session-prefix",
        type=str,
        default=_config_value(config, "session_prefix", defaults.session_prefix),
        help="Prefix for generated session directories",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=_config_value(config, "log_level", defaults.log_level),
        help="Logging verbosity",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=_config_value(config, "log_file", defaults.log_file),
        help="Optional explicit log file path",
    )
    parser.add_argument(
        "--enable-commands",
        action="store_true",
        default=_config_value(config, "enable_commands", defaults.enable_commands),
        help="Flag supplied by the logger when running under module manager",
    )
    parser.add_argument(
        "--window-geometry",
        type=str,
        default=_config_value(config, "window_geometry", defaults.window_geometry),
        help="Initial window geometry when launched with GUI",
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=_config_value(config, "sample_rate", defaults.sample_rate),
        help="Sample rate (Hz) for input streams",
    )
    parser.add_argument(
        "--discovery-timeout",
        type=float,
        default=_config_value(config, "discovery_timeout", defaults.discovery_timeout),
        help="Device discovery timeout (seconds)",
    )
    parser.add_argument(
        "--discovery-retry",
        type=float,
        default=_config_value(config, "discovery_retry", defaults.discovery_retry),
        help="Device rediscovery interval (seconds)",
    )

    auto_select = parser.add_mutually_exclusive_group()
    auto_select.add_argument(
        "--auto-select-new",
        dest="auto_select_new",
        action="store_true",
        default=_config_value(config, "auto_select_new", defaults.auto_select_new),
        help="Automatically select newly detected devices",
    )
    auto_select.add_argument(
        "--no-auto-select-new",
        dest="auto_select_new",
        action="store_false",
        help="Disable automatic selection of new devices",
    )

    auto_start = parser.add_mutually_exclusive_group()
    auto_start.add_argument(
        "--auto-start-recording",
        dest="auto_start_recording",
        action="store_true",
        default=_config_value(config, "auto_start_recording", defaults.auto_start_recording),
        help="Begin recording automatically when the module starts",
    )
    auto_start.add_argument(
        "--no-auto-start-recording",
        dest="auto_start_recording",
        action="store_false",
        help="Disable automatic recording on startup",
    )

    console_group = parser.add_mutually_exclusive_group()
    console_group.add_argument(
        "--console",
        dest="console_output",
        action="store_true",
        default=_config_value(config, "console_output", defaults.console_output),
        help="Enable console logging",
    )
    console_group.add_argument(
        "--no-console",
        dest="console_output",
        action="store_false",
        help="Disable console logging",
    )

    return parser


def parse_cli_args(
    argv: Optional[list[str]] = None,
    *,
    config_path: Path,
) -> argparse.Namespace:
    """Parse CLI arguments using configuration defaults."""

    config = read_config_file(config_path)
    parser = build_arg_parser(config)
    return parser.parse_args(argv)


def _normalize_mode(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text == "headless":
        return "cli"
    if text in INTERACTION_MODES:
        return text
    return INTERACTION_MODES[0]
