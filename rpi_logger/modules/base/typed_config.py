"""Typed configuration protocol for module configs with type coercion helpers."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Protocol, TypeVar, runtime_checkable

from .preferences import ScopedPreferences


@runtime_checkable
class ModuleConfig(Protocol):
    """Protocol for typed module configuration classes.

    All module config dataclasses should implement:
    - from_preferences(): Build config from ScopedPreferences
    - to_dict(): Export config as dict (for serialization)

    Example implementation:

        @dataclass(slots=True)
        class MyModuleConfig:
            output_dir: Path = Path("my_module")
            sample_rate: int = 48000
            enabled: bool = True

            @classmethod
            def from_preferences(
                cls, prefs: ScopedPreferences, args: Any = None
            ) -> "MyModuleConfig":
                return cls(
                    output_dir=Path(get_pref_str(prefs, "output_dir", "my_module")),
                    sample_rate=get_pref_int(prefs, "sample_rate", 48000),
                    enabled=get_pref_bool(prefs, "enabled", True),
                )

            def to_dict(self) -> dict[str, Any]:
                return asdict(self)
    """

    @classmethod
    def from_preferences(
        cls, prefs: ScopedPreferences, args: Any = None
    ) -> "ModuleConfig":
        """Construct config from preferences with optional CLI args override.

        Args:
            prefs: Scoped preferences instance for this module.
            args: Optional argparse namespace for CLI overrides.

        Returns:
            Typed config instance.
        """
        ...

    def to_dict(self) -> dict[str, Any]:
        """Export config values as dictionary."""
        ...


T = TypeVar("T", bound=ModuleConfig)


def load_typed_config(
    config_cls: type[T],
    prefs: ScopedPreferences,
    args: Any = None,
) -> T:
    """Helper to load a typed config from preferences.

    Args:
        config_cls: The config dataclass type.
        prefs: Scoped preferences instance.
        args: Optional argparse namespace for CLI overrides.

    Returns:
        Typed config instance.
    """
    return config_cls.from_preferences(prefs, args)


# ---------------------------------------------------------------------------
# Type coercion helpers for from_preferences() implementations
# ---------------------------------------------------------------------------


def get_pref_str(prefs: ScopedPreferences, key: str, default: str) -> str:
    val = prefs.get(key)
    return str(val) if val is not None else default


def get_pref_int(prefs: ScopedPreferences, key: str, default: int) -> int:
    val = prefs.get(key)
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def get_pref_float(prefs: ScopedPreferences, key: str, default: float) -> float:
    val = prefs.get(key)
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def get_pref_bool(prefs: ScopedPreferences, key: str, default: bool) -> bool:
    val = prefs.get(key)
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in {"true", "1", "yes", "on"}


def get_pref_path(prefs: ScopedPreferences, key: str, default: Path) -> Path:
    val = prefs.get(key)
    if val is None:
        return default
    text = str(val).strip()
    return Path(text) if text else default


__all__ = [
    "ModuleConfig",
    "load_typed_config",
    "get_pref_str",
    "get_pref_int",
    "get_pref_float",
    "get_pref_bool",
    "get_pref_path",
]
