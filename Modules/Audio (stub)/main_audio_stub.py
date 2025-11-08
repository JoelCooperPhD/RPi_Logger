"""Audio (Stub) module entry point leveraging the stub (codex) stack."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
import sys
from typing import Optional

MODULE_DIR = Path(__file__).parent
PROJECT_ROOT = MODULE_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

STUB_ROOT = MODULE_DIR.parent / "stub (codex)"
if STUB_ROOT.exists() and str(STUB_ROOT) not in sys.path:
    sys.path.insert(0, str(STUB_ROOT))

_venv_site = PROJECT_ROOT / ".venv" / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
if _venv_site.exists() and str(_venv_site) not in sys.path:
    sys.path.insert(0, str(_venv_site))

from vmc import StubCodexSupervisor
from vmc.constants import PLACEHOLDER_GEOMETRY

from audio_runtime import AudioStubRuntime

DISPLAY_NAME = "Audio (Stub)"
MODULE_ID = "audio_stub"
DEFAULT_OUTPUT_SUBDIR = Path("audio-stub")
CONFIG_PATH = MODULE_DIR / "config.txt"

logger = logging.getLogger(__name__)


def _load_config(path: Path = CONFIG_PATH) -> dict[str, object]:
    config: dict[str, object] = {}
    if not path.exists():
        return config
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
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
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to load config %s: %s", path, exc)
    return config


def parse_args(argv: Optional[list[str]] = None):
    config = _load_config()
    default_output = Path(str(config.get("output_dir", DEFAULT_OUTPUT_SUBDIR)))
    default_prefix = str(config.get("session_prefix", MODULE_ID))
    default_sample_rate = int(config.get("sample_rate", 48000))
    default_auto_select = bool(config.get("auto_select_new", False))
    default_auto_start = bool(config.get("auto_start_recording", False))
    default_console = bool(config.get("console_output", False))
    default_timeout = float(config.get("discovery_timeout", 5.0))
    default_retry = float(config.get("discovery_retry", 3.0))
    default_log_level = str(config.get("log_level", "info"))

    parser = argparse.ArgumentParser(description=f"{DISPLAY_NAME} module")

    parser.add_argument(
        "--mode",
        choices=("gui", "headless"),
        default="gui",
        help="Execution mode set by the module manager",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=default_output,
        help="Session root provided by the module manager",
    )
    parser.add_argument(
        "--session-prefix",
        type=str,
        default=default_prefix,
        help="Prefix for generated session directories",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=default_log_level,
        help="Logging verbosity",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Optional explicit log file path",
    )
    parser.add_argument(
        "--enable-commands",
        action="store_true",
        default=False,
        help="Flag supplied by the logger when running under module manager",
    )
    parser.add_argument(
        "--window-geometry",
        type=str,
        default=None,
        help=(
            "Initial window geometry when launched with GUI "
            f"(fallback to saved config or {PLACEHOLDER_GEOMETRY})"
        ),
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=default_sample_rate,
        help="Sample rate (Hz) for input streams",
    )
    parser.add_argument(
        "--discovery-timeout",
        type=float,
        default=default_timeout,
        help="Device discovery timeout (seconds)",
    )
    parser.add_argument(
        "--discovery-retry",
        type=float,
        default=default_retry,
        help="Device rediscovery interval (seconds)",
    )

    auto_select = parser.add_mutually_exclusive_group()
    auto_select.add_argument(
        "--auto-select-new",
        dest="auto_select_new",
        action="store_true",
        default=default_auto_select,
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
        default=default_auto_start,
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
        default=default_console,
        help="Enable console logging",
    )
    console_group.add_argument(
        "--no-console",
        dest="console_output",
        action="store_false",
        help="Disable console logging",
    )

    return parser.parse_args(argv)


def build_runtime(context):
    return AudioStubRuntime(context)


async def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)

    if not args.enable_commands:
        logger.error("Audio (Stub) module must be launched by the logger controller.")
        return

    module_dir = MODULE_DIR

    supervisor = StubCodexSupervisor(
        args,
        module_dir,
        logger,
        runtime_factory=build_runtime,
        display_name=DISPLAY_NAME,
        module_id=MODULE_ID,
    )

    try:
        await supervisor.run()
    finally:
        await supervisor.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
