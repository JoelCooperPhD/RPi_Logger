#!/usr/bin/env python3
"""
Module Discovery System

Dynamically discovers logging modules in the Modules/ directory.
Validates module structure and extracts metadata.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("ModuleDiscovery")


@dataclass
class ModuleInfo:
    """Information about a discovered module."""

    name: str                    # Module name (e.g., "Cameras")
    directory: Path              # Module directory path
    entry_point: Path            # Path to main_*.py file
    config_path: Optional[Path]  # Path to config.txt (if exists)
    display_name: str            # Human-readable name

    def __repr__(self) -> str:
        return f"ModuleInfo(name={self.name}, entry={self.entry_point.name})"


def extract_module_name_from_entry(entry_point: Path) -> Optional[str]:
    """
    Extract module name from main_*.py filename pattern.

    Args:
        entry_point: Path to main_*.py file

    Returns:
        Module name or None if pattern doesn't match

    Examples:
        main_camera.py -> Cameras
        main_audio.py -> AudioRecorder
        main_eye_tracker.py -> EyeTracker
    """
    # Pattern: main_<name>.py or main_<name>_<suffix>.py
    match = re.match(r'main_(.+)\.py$', entry_point.name)
    if not match:
        return None

    # Extract the name part
    name_part = match.group(1)

    # Convert snake_case to TitleCase for display
    # e.g., "eye_tracker" -> "EyeTracker"
    parts = name_part.split('_')
    title_case = ''.join(word.capitalize() for word in parts)

    return title_case


def validate_module_structure(module_dir: Path, entry_point: Path) -> bool:
    """
    Validate that a module has the expected structure.

    Args:
        module_dir: Module directory
        entry_point: Entry point file

    Returns:
        True if valid, False otherwise
    """
    # Check entry point exists and is a file
    if not entry_point.is_file():
        logger.warning("Entry point not found: %s", entry_point)
        return False

    # Check for basic Python syntax (quick validation)
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

    # Check for *_core directory (common pattern)
    core_dirs = list(module_dir.glob('*_core'))
    if not core_dirs:
        logger.debug("No *_core directory found in %s (optional)", module_dir)

    return True


def load_module_config(module_dir: Path) -> Optional[dict]:
    """
    Load module configuration from config.txt if available.

    Args:
        module_dir: Module directory

    Returns:
        Config dict or None if not found
    """
    config_path = module_dir / "config.txt"
    if not config_path.exists():
        return None

    config = {}
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith('#'):
                    continue
                # Parse key = value
                if '=' in line:
                    key, value = line.split('=', 1)
                    config[key.strip()] = value.strip()
    except Exception as e:
        logger.warning("Failed to load config %s: %s", config_path, e)
        return None

    return config


def discover_modules(modules_dir: Path = None) -> List[ModuleInfo]:
    """
    Discover all valid logging modules in the Modules directory.

    Args:
        modules_dir: Path to Modules directory (default: ./Modules)

    Returns:
        List of discovered and validated ModuleInfo objects
    """
    if modules_dir is None:
        # Default to Modules/ in project root
        modules_dir = Path(__file__).parent.parent / "Modules"

    if not modules_dir.exists():
        logger.error("Modules directory not found: %s", modules_dir)
        return []

    logger.info("Discovering modules in: %s", modules_dir)
    discovered = []

    # Iterate through subdirectories
    for module_dir in sorted(modules_dir.iterdir()):
        # Skip non-directories
        if not module_dir.is_dir():
            continue

        # Skip hidden directories and special directories
        if module_dir.name.startswith('.') or module_dir.name in ('__pycache__', 'base'):
            continue

        logger.debug("Checking module directory: %s", module_dir.name)

        # Look for main_*.py entry points
        entry_points = list(module_dir.glob('main_*.py'))

        if not entry_points:
            logger.debug("No main_*.py found in %s, skipping", module_dir.name)
            continue

        if len(entry_points) > 1:
            logger.warning("Multiple entry points in %s: %s - using first",
                          module_dir.name, [e.name for e in entry_points])

        entry_point = entry_points[0]

        # Extract module name from entry point
        module_name = extract_module_name_from_entry(entry_point)
        if not module_name:
            logger.warning("Could not extract module name from %s", entry_point.name)
            # Fall back to directory name
            module_name = module_dir.name

        # Validate module structure
        if not validate_module_structure(module_dir, entry_point):
            logger.warning("Module %s failed validation, skipping", module_dir.name)
            continue

        # Load config if available
        config_path = module_dir / "config.txt"
        if not config_path.exists():
            config_path = None
            logger.debug("No config.txt for %s", module_name)

        # Load config to get display name (if available)
        config = load_module_config(module_dir)
        display_name = module_name  # Default to module name

        # Create ModuleInfo
        info = ModuleInfo(
            name=module_name,
            directory=module_dir,
            entry_point=entry_point,
            config_path=config_path,
            display_name=display_name,
        )

        discovered.append(info)
        logger.info("Discovered module: %s (entry: %s)", info.name, entry_point.name)

    logger.info("Discovery complete: %d module(s) found", len(discovered))
    return discovered


def get_module_by_name(modules: List[ModuleInfo], name: str) -> Optional[ModuleInfo]:
    """
    Get module info by name.

    Args:
        modules: List of discovered modules
        name: Module name to find

    Returns:
        ModuleInfo or None if not found
    """
    for module in modules:
        if module.name == name:
            return module
    return None


if __name__ == "__main__":
    # Test discovery
    logging.basicConfig(level=logging.DEBUG)
    modules = discover_modules()
    print(f"\nDiscovered {len(modules)} modules:")
    for mod in modules:
        print(f"  - {mod.display_name} ({mod.name})")
        print(f"    Entry: {mod.entry_point}")
        print(f"    Config: {mod.config_path}")
