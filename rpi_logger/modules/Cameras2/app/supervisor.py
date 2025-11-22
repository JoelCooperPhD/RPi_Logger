"""Supervisor presets for Cameras2."""

from __future__ import annotations

from pathlib import Path
import importlib.util

from rpi_logger.core.logging_utils import get_module_logger


def create_supervisor(args, module_dir: Path):
    """Construct a stub supervisor for Cameras2 if the stub package exists."""

    logger = get_module_logger(__name__)
    supervisor_path = module_dir.parent / "stub (codex)" / "vmc" / "supervisor.py"
    if not supervisor_path.exists():
        logger.warning("StubCodexSupervisor path missing: %s", supervisor_path)
        return None

    spec = importlib.util.spec_from_file_location("stub_codex_supervisor", supervisor_path)
    if not spec or not spec.loader:
        logger.warning("Unable to load stub supervisor spec from %s", supervisor_path)
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)  # type: ignore[attr-defined]
    except Exception:
        logger.warning("Failed to load StubCodexSupervisor", exc_info=True)
        return None

    supervisor_cls = getattr(module, "StubCodexSupervisor", None)
    if not supervisor_cls:
        logger.warning("StubCodexSupervisor class not found in %s", supervisor_path)
        return None
    return supervisor_cls(args, module_dir=module_dir, logger=logger)
