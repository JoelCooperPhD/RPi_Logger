"""Helpers for resolving writable module configuration files."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from rpi_logger.core.paths import USER_MODULE_CONFIG_DIR

logger = logging.getLogger(__name__)


def resolve_writable_module_config(
    module_dir: Path,
    module_id: str,
    *,
    filename: str = "config.txt",
) -> Path:
    """Return a config path that is guaranteed to be user-writable.

    When the template bundled with the module cannot be written (e.g. repo checkout),
    we fall back to ~/.rpi_logger/module_configs/<module_id>/<filename> and seed it
    with the template contents the first time it is needed.
    """

    template_path = module_dir / filename
    if template_path.exists() and _is_path_writable(template_path):
        return template_path

    fallback_dir = USER_MODULE_CONFIG_DIR / module_id
    try:
        fallback_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Failed to create module config dir %s: %s", fallback_dir, exc)

    fallback_path = fallback_dir / filename
    if not fallback_path.exists():
        try:
            if template_path.exists():
                shutil.copy2(template_path, fallback_path)
            else:
                fallback_path.touch()
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Failed to seed fallback config %s: %s", fallback_path, exc)

    logger.info(
        "Using writable config store %s (template %s unavailable for writes)",
        fallback_path,
        template_path,
    )
    return fallback_path


def _is_path_writable(path: Path) -> bool:
    if path.exists():
        return os.access(path, os.W_OK)
    parent = path.parent
    return parent.exists() and os.access(parent, os.W_OK)
