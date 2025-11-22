
import asyncio
from rpi_logger.core.logging_utils import get_module_logger
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .paths import MODULES_DIR
from .logging_config import configure_logging
from rpi_logger.modules.base.config_paths import resolve_module_config_path

logger = get_module_logger("ModuleDiscovery")


@dataclass
class ModuleInfo:

    name: str                    # Module name (e.g., "Cameras")
    directory: Path              # Module directory path
    entry_point: Path            # Path to main_*.py file
    config_path: Optional[Path]  # Path to config.txt (if exists)
    display_name: str            # Human-readable name
    module_id: str = ""          # Lowercase identifier derived from entry name
    config_template_path: Optional[Path] = None  # Original config template path

    def __repr__(self) -> str:
        return f"ModuleInfo(name={self.name}, entry={self.entry_point.name})"


def parse_bool(value, default: bool = True) -> bool:
    """Parse common string representations into booleans."""
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    normalized = str(value).strip().lower()
    if not normalized:
        return default

    if normalized in {'1', 'true', 'yes', 'on'}:
        return True
    if normalized in {'0', 'false', 'no', 'off'}:
        return False

    return default


def extract_module_name_from_entry(entry_point: Path) -> Optional[str]:
    match = re.match(r'main_(.+)\.py$', entry_point.name)
    if not match:
        return None

    name_part = match.group(1)

    parts = name_part.split('_')
    title_case = ''.join(word if word.isupper() else word.capitalize() for word in parts)

    return title_case


def extract_module_id(entry_point: Path, fallback_name: str) -> str:
    """Return the lowercase module identifier derived from the entry filename."""
    stem = entry_point.stem.lower()
    if stem.startswith('main_'):
        candidate = stem[5:]
        if candidate:
            return candidate
    return fallback_name.lower()


async def validate_module_structure_async(module_dir: Path, entry_point: Path) -> bool:
    """Async version of validate_module_structure."""
    return await asyncio.to_thread(validate_module_structure, module_dir, entry_point)


def validate_module_structure(module_dir: Path, entry_point: Path) -> bool:
    if not entry_point.is_file():
        logger.warning("Entry point not found: %s", entry_point)
        return False

    try:
        with open(entry_point, 'r', encoding='utf-8') as f:
            content = f.read()
            # Must have asyncio and main function
            if 'asyncio' not in content or 'async def main' not in content:
                logger.warning("Entry point missing asyncio/main: %s", entry_point)
                return False
    except Exception as e:
        logger.warning("Failed to read entry point %s: %s", entry_point, e)
        return False

    core_dirs = list(module_dir.glob('*_core'))
    if not core_dirs:
        logger.debug("No *_core directory found in %s (optional)", module_dir)

    return True


async def load_module_config_async(module_dir: Path) -> Optional[dict]:
    """Async version of load_module_config."""
    return await asyncio.to_thread(load_module_config, module_dir)


def load_module_config(module_dir: Path) -> Optional[dict]:
    config_path = module_dir / "config.txt"
    if not config_path.exists():
        return None

    config = {}
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, value = line.split('=', 1)
                    config[key.strip()] = value.strip()
    except Exception as e:
        logger.warning("Failed to load config %s: %s", config_path, e)
        return None

    return config


async def discover_modules_async(modules_dir: Path = None) -> List[ModuleInfo]:
    """Async version of discover_modules."""
    return await asyncio.to_thread(discover_modules, modules_dir)


def discover_modules(modules_dir: Path = None) -> List[ModuleInfo]:
    if modules_dir is None:
        modules_dir = MODULES_DIR

    if not modules_dir.exists():
        logger.error("Modules directory not found: %s", modules_dir)
        return []

    logger.info("Discovering modules in: %s", modules_dir)
    discovered = []

    for module_dir in sorted(modules_dir.iterdir()):
        if not module_dir.is_dir():
            continue

        if module_dir.name.startswith('.') or module_dir.name in ('__pycache__', 'base'):
            continue

        logger.debug("Checking module directory: %s", module_dir.name)

        entry_points = list(module_dir.glob('main_*.py'))

        if not entry_points:
            logger.debug("No main_*.py found in %s, skipping", module_dir.name)
            continue

        if len(entry_points) > 1:
            logger.warning("Multiple entry points in %s: %s - using first",
                          module_dir.name, [e.name for e in entry_points])

        entry_point = entry_points[0]

        module_name = extract_module_name_from_entry(entry_point)
        if not module_name:
            logger.warning("Could not extract module name from %s", entry_point.name)
            module_name = module_dir.name

        if not validate_module_structure(module_dir, entry_point):
            logger.warning("Module %s failed validation, skipping", module_dir.name)
            continue

        module_id = extract_module_id(entry_point, module_name)

        config_template_path = module_dir / "config.txt"
        config_path: Optional[Path] = None

        try:
            config_context = resolve_module_config_path(module_dir, module_id)
            config_path = config_context.writable_path
            template_candidate = config_context.template_path
            if template_candidate.exists():
                config_template_path = template_candidate
            else:
                config_template_path = None
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning(
                "Failed to resolve writable config for %s (%s): %s",
                module_name,
                module_dir,
                exc,
            )
            if config_template_path.exists():
                config_path = config_template_path
            else:
                config_template_path = None
                logger.debug("No config.txt for %s", module_name)

        config = load_module_config(module_dir)
        display_name = module_name  # Default to module name
        is_visible = True
        if config and isinstance(config, dict):
            display_name = config.get('display_name', display_name) or display_name
            is_visible = parse_bool(config.get('visible'), default=True)

        if not is_visible:
            logger.info("Module %s marked hidden via config, skipping", module_name)
            continue

        info = ModuleInfo(
            name=module_name,
            directory=module_dir,
            entry_point=entry_point,
            config_path=config_path,
            display_name=display_name,
            module_id=module_id,
            config_template_path=config_template_path,
        )

        discovered.append(info)
        logger.info("Discovered module: %s (entry: %s)", info.name, entry_point.name)

    logger.info("Discovery complete: %d module(s) found", len(discovered))
    return discovered


def get_module_by_name(modules: List[ModuleInfo], name: str) -> Optional[ModuleInfo]:
    for module in modules:
        if module.name == name:
            return module
    return None


if __name__ == "__main__":
    configure_logging(level=logging.DEBUG, force=True)
    modules = discover_modules()
    print(f"\nDiscovered {len(modules)} modules:")
    for mod in modules:
        print(f"  - {mod.display_name} ({mod.name})")
        print(f"    Entry: {mod.entry_point}")
        print(f"    Config: {mod.config_path}")
