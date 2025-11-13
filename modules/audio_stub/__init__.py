"""Public entry-points for the refactored audio stub package."""

try:  # pragma: no cover - optional during unit tests without vmc installed
    from .app import AudioApp
except ModuleNotFoundError as exc:  # pragma: no cover
    if exc.name != "vmc":
        raise
    AudioApp = None  # type: ignore[assignment]
from .config import AudioStubSettings, build_arg_parser, parse_cli_args, read_config_file
try:  # pragma: no cover - optional during unit tests without vmc installed
    from .runtime import AudioStubRuntime
except ModuleNotFoundError as exc:  # pragma: no cover
    if exc.name != "vmc":
        raise
    AudioStubRuntime = None  # type: ignore[assignment]
from .state import AudioDeviceInfo, AudioSnapshot, AudioState

__all__ = [
    "AudioApp",
    "AudioStubRuntime",
    "AudioStubSettings",
    "AudioState",
    "AudioSnapshot",
    "AudioDeviceInfo",
    "build_arg_parser",
    "parse_cli_args",
    "read_config_file",
]
