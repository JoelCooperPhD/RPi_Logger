
import asyncio
import errno
import hashlib
from rpi_logger.core.logging_utils import get_module_logger
import re
from pathlib import Path
from typing import Any, Dict, Iterable

import aiofiles

from .logging_config import configure_logging
from .paths import PROJECT_ROOT, USER_CONFIG_OVERRIDES_DIR


logger = get_module_logger("ConfigManager")


class ConfigManager:

    def __init__(self):
        self.logger = get_module_logger("ConfigManager")
        self.lock = asyncio.Lock()
        try:
            self._project_root = PROJECT_ROOT.resolve()
        except Exception:  # pragma: no cover - defensive fallback
            self._project_root = PROJECT_ROOT

    # ------------------------------------------------------------------
    # Internal helpers

    @staticmethod
    def _stringify_value(value: Any) -> str:
        if isinstance(value, bool):
            return str(value).lower()
        return str(value)

    def _parse_config_lines(self, lines: Iterable[str]) -> Dict[str, str]:
        config: Dict[str, str] = {}

        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' not in line:
                continue

            key, value = line.split('=', 1)
            key = key.strip()
            value = value.strip()

            if '#' in value:
                value = value.split('#')[0].strip()

            if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]

            config[key] = value

        return config

    def _resolve_override_path(self, config_path: Path) -> Path:
        try:
            rel_path = config_path.resolve().relative_to(self._project_root)
        except Exception:
            digest = hashlib.sha1(str(config_path).encode('utf-8')).hexdigest()[:10]
            safe_name = re.sub(r'[^a-zA-Z0-9._-]+', '_', config_path.stem or 'config')
            rel_path = Path('external') / f"{safe_name}_{digest}{config_path.suffix or '.txt'}"
        return USER_CONFIG_OVERRIDES_DIR / rel_path

    def _load_override_sync(self, config_path: Path) -> Dict[str, str]:
        override_path = self._resolve_override_path(config_path)
        if not override_path.exists():
            return {}

        try:
            with open(override_path, 'r', encoding='utf-8') as fh:
                return self._parse_config_lines(fh)
        except Exception as exc:
            logger.warning("Failed to read override config %s: %s", override_path, exc)
            return {}

    def _write_override_sync(self, config_path: Path, updates: Dict[str, Any]) -> bool:
        if not updates:
            return True

        override_path = self._resolve_override_path(config_path)
        try:
            existing = self._load_override_sync(config_path)
            for key, value in updates.items():
                existing[key] = self._stringify_value(value)

            override_path.parent.mkdir(parents=True, exist_ok=True)
            with open(override_path, 'w', encoding='utf-8') as fh:
                for key in sorted(existing.keys()):
                    fh.write(f"{key} = {existing[key]}\n")

            logger.debug("Stored config overrides in %s", override_path)
            return True
        except Exception as exc:
            logger.error("Failed to write config override %s: %s", override_path, exc)
            return False

    def _clear_override(self, config_path: Path) -> None:
        override_path = self._resolve_override_path(config_path)
        try:
            override_path.unlink(missing_ok=True)
        except Exception:
            return

    def read_config(self, config_path: Path) -> Dict[str, str]:
        """Synchronous wrapper for read_config_async. Use in non-async contexts."""
        try:
            # Try to get the running event loop
            loop = asyncio.get_running_loop()
            # We're in an async context but called sync method - use asyncio.to_thread
            # This shouldn't happen in well-designed code, but provides a fallback
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(self._read_config_sync, config_path)
                return future.result()
        except RuntimeError:
            # No event loop running - we're in a pure sync context
            return self._read_config_sync(config_path)

    def _read_config_sync(self, config_path: Path) -> Dict[str, str]:
        """Pure synchronous implementation for config reading."""
        config: Dict[str, str] = {}

        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = self._parse_config_lines(f)
            except Exception as e:
                logger.error("Failed to read config %s: %s", config_path, e)

        overrides = self._load_override_sync(config_path)
        if overrides:
            config.update(overrides)

        return config

    async def read_config_async(self, config_path: Path) -> Dict[str, str]:
        """Async version for use in async contexts."""
        config: Dict[str, str] = {}

        if await asyncio.to_thread(config_path.exists):
            try:
                lines: list[str] = []
                async with aiofiles.open(config_path, 'r', encoding='utf-8') as f:
                    async for line in f:
                        lines.append(line)
                config = self._parse_config_lines(lines)
            except Exception as e:
                logger.error("Failed to read config %s: %s", config_path, e)

        overrides = await asyncio.to_thread(self._load_override_sync, config_path)
        if overrides:
            config.update(overrides)

        return config

    def write_config(self, config_path: Path, updates: Dict[str, Any]) -> bool:
        """Synchronous wrapper for write_config_async. Use in non-async contexts."""
        try:
            # Try to get the running event loop
            loop = asyncio.get_running_loop()
            # We're in an async context but called sync method - use thread pool
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(self._write_config_sync, config_path, updates)
                return future.result()
        except RuntimeError:
            # No event loop running - we're in a pure sync context
            return self._write_config_sync(config_path, updates)

    def _write_config_sync(self, config_path: Path, updates: Dict[str, Any]) -> bool:
        """Pure synchronous implementation for config writing."""
        if not config_path.exists():
            logger.error("Config file not found: %s", config_path)
            return False

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            updated_keys = set()

            for i, line in enumerate(lines):
                stripped = line.strip()
                if not stripped or stripped.startswith('#'):
                    continue

                if '=' in stripped:
                    key = stripped.split('=')[0].strip()
                    if key in updates:
                        value_str = self._stringify_value(updates[key])
                        indent = len(line) - len(line.lstrip())
                        lines[i] = ' ' * indent + f"{key} = {value_str}\n"
                        updated_keys.add(key)

            for key, value in updates.items():
                if key not in updated_keys:
                    value_str = self._stringify_value(value)
                    lines.append(f"{key} = {value_str}\n")
                    logger.debug("Added new config key: %s = %s", key, value_str)

            with open(config_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)

            self._clear_override(config_path)
            return True

        except OSError as e:
            if isinstance(e, PermissionError) or e.errno in (errno.EACCES, errno.EROFS):
                logger.warning(
                    "Config %s is not writable (%s). Falling back to override file",
                    config_path,
                    e,
                )
                return self._write_override_sync(config_path, updates)
            logger.error("Failed to write config %s: %s", config_path, e, exc_info=True)
            return False
        except Exception as e:  # pragma: no cover - defensive
            logger.error("Failed to write config %s: %s", config_path, e, exc_info=True)
            return False

    async def write_config_async(self, config_path: Path, updates: Dict[str, Any]) -> bool:
        """Async version for use in async contexts."""
        if not await asyncio.to_thread(config_path.exists):
            logger.error("Config file not found: %s", config_path)
            return False

        async with self.lock:
            try:
                async with aiofiles.open(config_path, 'r', encoding='utf-8') as f:
                    lines = await f.readlines()

                updated_keys = set()

                for i, line in enumerate(lines):
                    stripped = line.strip()
                    if not stripped or stripped.startswith('#'):
                        continue

                    if '=' in stripped:
                        key = stripped.split('=')[0].strip()
                        if key in updates:
                            value_str = self._stringify_value(updates[key])
                            indent = len(line) - len(line.lstrip())
                            lines[i] = ' ' * indent + f"{key} = {value_str}\n"
                            updated_keys.add(key)

                for key, value in updates.items():
                    if key not in updated_keys:
                        value_str = self._stringify_value(value)
                        lines.append(f"{key} = {value_str}\n")
                        logger.debug("Added new config key: %s = %s", key, value_str)

                async with aiofiles.open(config_path, 'w', encoding='utf-8') as f:
                    await f.writelines(lines)

                await asyncio.to_thread(self._clear_override, config_path)
                return True

            except OSError as e:
                if isinstance(e, PermissionError) or e.errno in (errno.EACCES, errno.EROFS):
                    logger.warning(
                        "Config %s is not writable (%s). Falling back to override file",
                        config_path,
                        e,
                    )
                    return await asyncio.to_thread(self._write_override_sync, config_path, updates)
                logger.error("Failed to write config %s: %s", config_path, e, exc_info=True)
                return False
            except Exception as e:  # pragma: no cover - defensive
                logger.error("Failed to write config %s: %s", config_path, e, exc_info=True)
                return False

    def get_bool(self, config: Dict[str, str], key: str, default: bool = False) -> bool:
        if key not in config:
            return default

        value = config[key].lower()
        return value in ('true', '1', 'yes', 'on')

    def get_int(self, config: Dict[str, str], key: str, default: int = 0) -> int:
        if key not in config:
            return default

        try:
            return int(config[key])
        except ValueError:
            logger.warning("Invalid int value for %s: %s, using default %d", key, config[key], default)
            return default

    def get_float(self, config: Dict[str, str], key: str, default: float = 0.0) -> float:
        if key not in config:
            return default

        try:
            return float(config[key])
        except ValueError:
            logger.warning("Invalid float value for %s: %s, using default %f", key, config[key], default)
            return default

    def get_str(self, config: Dict[str, str], key: str, default: str = "") -> str:
        return config.get(key, default)


_config_manager = ConfigManager()


def get_config_manager() -> ConfigManager:
    return _config_manager


if __name__ == "__main__":
    configure_logging(level=logging.DEBUG, force=True)

    from pathlib import Path
    import tempfile

    test_config = """#################################

enabled = true
sample_rate = 48000

window_x = 100
window_y = 100
window_width = 800
window_height = 600
"""

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write(test_config)
        test_path = Path(f.name)

    cm = ConfigManager()

    config = cm.read_config(test_path)
    print("Original config:", config)

    print(f"enabled (bool): {cm.get_bool(config, 'enabled')}")
    print(f"sample_rate (int): {cm.get_int(config, 'sample_rate')}")
    print(f"window_x (int): {cm.get_int(config, 'window_x')}")

    updates = {
        'enabled': False,
        'window_x': 200,
        'window_y': 200,
        'new_key': 'test_value'
    }
    cm.write_config(test_path, updates)

    config2 = cm.read_config(test_path)
    print("\nUpdated config:", config2)

    test_path.unlink()
