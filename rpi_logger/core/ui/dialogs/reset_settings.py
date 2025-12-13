"""
Reset settings dialog for Logger.
"""

from pathlib import Path
from tkinter import messagebox


class ResetSettingsDialog:
    """Dialog for resetting application settings to defaults."""

    def __init__(self, parent, config_path: Path, on_reset_callback=None):
        self.config_path = config_path
        self.on_reset_callback = on_reset_callback

        response = messagebox.askyesno(
            "Reset Settings",
            "This will reset all configuration settings to their default values.\n\n"
            "A backup of your current config will be saved.\n\n"
            "Are you sure you want to continue?",
            parent=parent
        )

        if response:
            self._reset_config()

    def _reset_config(self):
        try:
            if self.config_path.exists():
                backup_path = self.config_path.with_suffix('.txt.backup')
                import shutil
                shutil.copy2(self.config_path, backup_path)

            default_config = self._get_default_config()

            with open(self.config_path, 'w') as f:
                f.write(default_config)

            messagebox.showinfo(
                "Reset Complete",
                f"Settings have been reset to defaults.\n\n"
                f"Backup saved to: {self.config_path.with_suffix('.txt.backup')}\n\n"
                f"Please restart the application for changes to take effect."
            )

            if self.on_reset_callback:
                self.on_reset_callback()

        except Exception as e:
            messagebox.showerror(
                "Reset Failed",
                f"Failed to reset settings: {e}"
            )

    def _get_default_config(self) -> str:
        return """################################################################################
# MASTER LOGGER CONFIGURATION
################################################################################

data_dir = data
session_prefix = session
log_level = info
console_output = false
ui_update_rate_hz = 10
window_x = 0
window_y = 0
window_width = 800
window_height = 600
"""
