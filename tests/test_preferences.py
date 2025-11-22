import asyncio
import tempfile
import unittest
from pathlib import Path

from rpi_logger.modules.base.preferences import (
    ModulePreferences,
    PreferenceChange,
    ScopedPreferences,
)


class ModulePreferencesTests(unittest.TestCase):

    def test_sync_write_and_remove(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.txt"
            config_path.write_text("enabled = true\n", encoding="utf-8")

            observed: list[PreferenceChange] = []

            prefs = ModulePreferences(config_path, on_change=observed.append)
            self.assertTrue(prefs.get_bool("enabled"))

            prefs.write_sync({"sample_rate": 48000})
            snapshot = prefs.snapshot()
            self.assertEqual(snapshot["sample_rate"], "48000")

            prefs.write_sync({}, remove_keys=["enabled"])
            snapshot = prefs.snapshot()
            self.assertNotIn("enabled", snapshot)
            self.assertTrue(any("sample_rate" in change.updated for change in observed))

    def test_async_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.txt"
            config_path.write_text("", encoding="utf-8")

            prefs = ModulePreferences(config_path)

            async def _run() -> None:
                await prefs.write_async({"foo": "bar"})

            asyncio.run(_run())
            self.assertEqual(prefs.get("foo"), "bar")

    def test_scoped_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.txt"
            config_path.write_text("", encoding="utf-8")

            prefs = ModulePreferences(config_path)
            scoped = prefs.scope("camera")
            scoped.write_sync({"preview": "on"})
            self.assertEqual(prefs.get("camera.preview"), "on")
            self.assertEqual(scoped.get("preview"), "on")
            scoped.write_sync({}, remove_keys=["preview"])
            self.assertIsNone(prefs.get("camera.preview"))


if __name__ == "__main__":
    unittest.main()
