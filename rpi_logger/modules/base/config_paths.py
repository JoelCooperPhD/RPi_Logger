"""Helpers for resolving writable module configuration files."""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from rpi_logger.core.logging_utils import get_module_logger
from rpi_logger.core.paths import USER_MODULE_CONFIG_DIR

logger = get_module_logger(__name__)


@dataclass(frozen=True)
class ModuleConfigContext:
    """Describes where a module's config template lives and which path is writable."""

    module_id: str
    template_path: Path
    writable_path: Path
    using_template: bool

    def as_path(self) -> Path:
        """Backward-compatible helper that returns the writable config path."""
        return self.writable_path


def resolve_module_config_path(
    module_dir: Path,
    module_id: str,
    *,
    filename: str = "config.txt",
) -> ModuleConfigContext:
    """Return template + writable paths for a module's config file."""

    template_path = module_dir / filename
    if template_path.exists() and _is_path_writable(template_path):
        return ModuleConfigContext(
            module_id=module_id,
            template_path=template_path,
            writable_path=template_path,
            using_template=True,
        )

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
    return ModuleConfigContext(
        module_id=module_id,
        template_path=template_path,
        writable_path=fallback_path,
        using_template=False,
    )


def resolve_writable_module_config(
    module_dir: Path,
    module_id: str,
    *,
    filename: str = "config.txt",
) -> Path:
    """Backward-compatible helper that returns only the writable config path."""

    return resolve_module_config_path(
        module_dir,
        module_id,
        filename=filename,
    ).writable_path


def _is_path_writable(path: Path) -> bool:
    if path.exists():
        return os.access(path, os.W_OK)
    parent = path.parent
    return parent.exists() and os.access(parent, os.W_OK)
