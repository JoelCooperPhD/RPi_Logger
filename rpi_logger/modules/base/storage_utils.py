"""Shared helpers for module data directories and filename conventions."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import re

from .io_utils import sanitize_path_component


def sanitize_device_id(device_id: str) -> str:
    """
    Sanitize a device ID for use in filenames.

    Converts device paths/identifiers to safe filename components by:
    - Converting to lowercase
    - Stripping leading slashes
    - Replacing path separators (/, \\) and colons with underscores
    - Removing other problematic characters (spaces, parentheses, brackets)
    - Collapsing consecutive underscores
    - Stripping leading/trailing underscores

    Args:
        device_id: Raw device identifier (e.g., "/dev/ttyUSB0", "GPS:serial0")

    Returns:
        Sanitized string safe for filenames (e.g., "dev_ttyusb0", "gps_serial0")
    """
    # Strip leading slashes and convert to lowercase
    safe = device_id.lstrip("/").lower()
    # Replace path separators and colons with underscores
    safe = safe.replace("/", "_").replace("\\", "_").replace(":", "_")
    # Remove spaces, parentheses, brackets
    safe = re.sub(r"[\s()\[\]]", "", safe)
    # Collapse consecutive underscores
    safe = re.sub(r"_+", "_", safe)
    # Strip leading/trailing underscores
    return safe.strip("_") or "device"


def _normalize_name(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalnum())


def _module_code(name: str) -> str:
    cleaned = "".join(ch for ch in name.upper() if ch.isalnum())
    return cleaned or "MODULE"


def ensure_module_data_dir(session_dir: Path, module_name: str) -> Path:
    """
    Ensure ``session_dir`` contains a sub-directory dedicated to ``module_name``.

    The helper detects when the provided ``session_dir`` is already the module
    directory (common when launching modules standalone) and avoids nesting.
    """
    normalized_session = _normalize_name(session_dir.name)
    normalized_module = _normalize_name(module_name)

    if normalized_session == normalized_module and session_dir.exists():
        target = session_dir
    else:
        safe_name = sanitize_path_component(module_name).strip("_") or module_name
        target = session_dir / safe_name
    target.mkdir(parents=True, exist_ok=True)
    return target


def derive_session_token(path: Path, module_name: Optional[str] = None) -> str:
    """
    Derive a timestamp/token component from the session directory name.

    When ``path`` points at a module subdirectory this helper will climb one
    level so that the token is still based on the session identifier.
    """
    base = Path(path)
    if (
        module_name
        and _normalize_name(base.name) == _normalize_name(module_name)
        and base.parent != base
    ):
        base = base.parent

    name = sanitize_path_component(base.name).strip("_")
    if "_" in name:
        candidate = name.split("_", 1)[1].strip("_")
        if candidate:
            return candidate
    return name or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def format_trial_suffix(trial_number: Optional[int], *, digits: int = 3) -> str:
    try:
        value = int(trial_number) if trial_number is not None else 0
    except (TypeError, ValueError):
        value = 0
    if value <= 0:
        value = 1
    return f"_trial{value:0{digits}d}"


def module_filename_prefix(
    directory: Path,
    module_name: str,
    trial_number: Optional[int] = None,
    *,
    code: Optional[str] = None,
) -> str:
    """
    Build a consistent filename prefix of the form
    ``{sessionToken}_{MODULECODE}_trial###``.
    """
    token = derive_session_token(directory, module_name)
    trial_suffix = format_trial_suffix(trial_number)
    module_code = _module_code(code or module_name)
    return f"{token}_{module_code}{trial_suffix}"


__all__ = [
    "derive_session_token",
    "ensure_module_data_dir",
    "format_trial_suffix",
    "module_filename_prefix",
    "sanitize_device_id",
]
