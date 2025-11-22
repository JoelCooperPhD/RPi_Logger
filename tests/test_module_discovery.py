import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rpi_logger.core.module_discovery import discover_modules


def _write_entry_point(path: Path, module_slug: str) -> None:
    entry = path / f"main_{module_slug}.py"
    entry.write_text(
        "import asyncio\n\n"
        "async def main():\n"
        "    await asyncio.sleep(0)\n",
        encoding="utf-8",
    )


class ModuleDiscoveryConfigTests(unittest.TestCase):

    def test_config_path_prefers_template_when_writable(self) -> None:
        with tempfile.TemporaryDirectory() as modules_dir, tempfile.TemporaryDirectory() as user_dir:
            modules_path = Path(modules_dir)
            module_dir = modules_path / "Notes"
            module_dir.mkdir()
            _write_entry_point(module_dir, "notes")
            template = module_dir / "config.txt"
            template.write_text("display_name = Notes\n", encoding="utf-8")

            with mock.patch(
                "rpi_logger.modules.base.config_paths.USER_MODULE_CONFIG_DIR",
                Path(user_dir),
            ):
                modules = discover_modules(modules_path)

            self.assertEqual(len(modules), 1)
            info = modules[0]
            self.assertEqual(info.module_id, "notes")
            self.assertEqual(info.config_path, template)
            self.assertEqual(info.config_template_path, template)

    def test_config_path_falls_back_when_template_unwritable(self) -> None:
        with tempfile.TemporaryDirectory() as modules_dir, tempfile.TemporaryDirectory() as user_dir:
            modules_path = Path(modules_dir)
            module_dir = modules_path / "Notes"
            module_dir.mkdir()
            _write_entry_point(module_dir, "notes")
            template = module_dir / "config.txt"
            template.write_text("display_name = Notes\n", encoding="utf-8")
            template.chmod(stat.S_IREAD)

            fallback_root = Path(user_dir)
            with mock.patch(
                "rpi_logger.modules.base.config_paths.USER_MODULE_CONFIG_DIR",
                fallback_root,
            ):
                modules = discover_modules(modules_path)

            self.assertEqual(len(modules), 1)
            info = modules[0]
            expected_fallback = fallback_root / "notes" / "config.txt"
            self.assertEqual(info.config_path, expected_fallback)
            self.assertTrue(info.config_path.exists())
            self.assertEqual(info.config_template_path, template)

    def test_config_path_falls_back_when_template_missing(self) -> None:
        with tempfile.TemporaryDirectory() as modules_dir, tempfile.TemporaryDirectory() as user_dir:
            modules_path = Path(modules_dir)
            module_dir = modules_path / "Notes"
            module_dir.mkdir()
            _write_entry_point(module_dir, "notes")

            fallback_root = Path(user_dir)
            with mock.patch(
                "rpi_logger.modules.base.config_paths.USER_MODULE_CONFIG_DIR",
                fallback_root,
            ):
                modules = discover_modules(modules_path)

            self.assertEqual(len(modules), 1)
            info = modules[0]
            expected_fallback = fallback_root / "notes" / "config.txt"
            self.assertEqual(info.config_path, expected_fallback)
            self.assertIsNone(info.config_template_path)
            self.assertTrue(info.config_path.exists())


if __name__ == "__main__":
    unittest.main()
