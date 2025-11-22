import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rpi_logger.modules.base.config_paths import resolve_module_config_path


class ConfigPathResolutionTests(unittest.TestCase):

    def test_returns_template_when_writable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            module_dir = Path(tmp_dir)
            template = module_dir / "config.txt"
            template.write_text("display_name = Demo\n", encoding="utf-8")

            ctx = resolve_module_config_path(module_dir, "demo")

            self.assertTrue(ctx.using_template)
            self.assertEqual(ctx.template_path, template)
            self.assertEqual(ctx.writable_path, template)

    def test_falls_back_when_template_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir, tempfile.TemporaryDirectory() as user_dir:
            module_dir = Path(tmp_dir)
            template = module_dir / "config.txt"
            template.write_text("display_name = Demo\n", encoding="utf-8")
            template.chmod(stat.S_IREAD)

            fallback_root = Path(user_dir)
            with mock.patch(
                "rpi_logger.modules.base.config_paths.USER_MODULE_CONFIG_DIR",
                fallback_root,
            ):
                ctx = resolve_module_config_path(module_dir, "demo")

            expected_dir = fallback_root / "demo"
            self.assertFalse(ctx.using_template)
            self.assertEqual(ctx.writable_path.parent, expected_dir)
            self.assertTrue(ctx.writable_path.exists())


if __name__ == "__main__":
    unittest.main()
