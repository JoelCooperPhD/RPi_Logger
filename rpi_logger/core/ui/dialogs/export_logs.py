"""
Export Logs dialog for Logger.

Allows users to export all application logs as a ZIP file for support.
"""

import datetime
import platform
import shutil
import subprocess
import sys
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox
from zipfile import ZipFile, ZIP_DEFLATED

from ..theme import Theme
from ...paths import LOGS_DIR, MODULE_LOGS_DIR, MASTER_LOG_FILE
from ...logging_utils import get_module_logger

logger = get_module_logger("ExportLogsDialog")


class ExportLogsDialog:
    """Dialog for exporting all logs as a ZIP file for support."""

    def __init__(self, parent: tk.Tk):
        self.parent = parent
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Export Logs for Support")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        Theme.configure_toplevel(self.dialog)

        self.dialog.geometry("480x330")
        self.dialog.resizable(False, False)

        self._build_ui()

        # Center dialog on parent
        x = parent.winfo_x() + (parent.winfo_width() // 2) - 240
        y = parent.winfo_y() + (parent.winfo_height() // 2) - 165
        self.dialog.geometry(f"+{x}+{y}")

        self.dialog.protocol("WM_DELETE_WINDOW", self.dialog.destroy)

    def _build_ui(self) -> None:
        """Build the dialog UI."""
        main_frame = ttk.Frame(self.dialog, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Title
        title_label = ttk.Label(
            main_frame,
            text="Export Logs for Support",
            font=('TkDefaultFont', 12, 'bold')
        )
        title_label.pack(pady=(0, 15))

        # Description
        desc_text = (
            "This will create a ZIP file containing all application logs.\n\n"
            "The export includes:\n"
            "  \u2022 Master application log\n"
            "  \u2022 All module logs\n"
            "  \u2022 System information\n\n"
            "No personal data or recordings are included."
        )
        desc_label = ttk.Label(
            main_frame,
            text=desc_text,
            justify=tk.LEFT
        )
        desc_label.pack(pady=(0, 15), anchor=tk.W)

        # Log location info
        location_text = f"Log location: {LOGS_DIR}"
        location_label = ttk.Label(
            main_frame,
            text=location_text,
            foreground="gray"
        )
        location_label.pack(pady=(0, 20), anchor=tk.W)

        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)

        export_button = ttk.Button(
            button_frame,
            text="Export...",
            command=self._do_export
        )
        export_button.pack(side=tk.LEFT, padx=(0, 10))

        open_folder_button = ttk.Button(
            button_frame,
            text="Open Log Folder",
            command=self._open_log_folder
        )
        open_folder_button.pack(side=tk.LEFT, padx=(0, 10))

        cancel_button = ttk.Button(
            button_frame,
            text="Cancel",
            command=self.dialog.destroy
        )
        cancel_button.pack(side=tk.RIGHT)

    def _do_export(self) -> None:
        """Export logs to a ZIP file."""
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        default_filename = f"rpi_logger_logs_{timestamp}.zip"

        filepath = filedialog.asksaveasfilename(
            parent=self.dialog,
            title="Save Logs Export",
            defaultextension=".zip",
            filetypes=[("ZIP files", "*.zip"), ("All files", "*.*")],
            initialfile=default_filename
        )

        if not filepath:
            return

        try:
            self._create_export_zip(Path(filepath))
            messagebox.showinfo(
                "Export Complete",
                f"Logs exported successfully to:\n\n{filepath}",
                parent=self.dialog
            )
            self.dialog.destroy()
        except Exception as e:
            logger.error("Failed to export logs: %s", e, exc_info=True)
            messagebox.showerror(
                "Export Failed",
                f"Failed to export logs:\n\n{e}",
                parent=self.dialog
            )

    def _create_export_zip(self, output_path: Path) -> None:
        """Create a ZIP file containing all logs.

        Args:
            output_path: Path for the output ZIP file.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Copy master log and rotated logs
            if MASTER_LOG_FILE.exists():
                shutil.copy2(MASTER_LOG_FILE, temp_path / "master.log")

            for rotated in LOGS_DIR.glob("master.log.*"):
                shutil.copy2(rotated, temp_path / rotated.name)

            # Copy module logs
            if MODULE_LOGS_DIR.exists():
                modules_temp = temp_path / "modules"
                modules_temp.mkdir()
                for module_dir in MODULE_LOGS_DIR.iterdir():
                    if module_dir.is_dir():
                        module_temp = modules_temp / module_dir.name
                        module_temp.mkdir()
                        for log_file in module_dir.glob("*.log*"):
                            shutil.copy2(log_file, module_temp / log_file.name)

            # Create system info file
            system_info = self._gather_system_info()
            (temp_path / "system_info.txt").write_text(system_info, encoding="utf-8")

            # Create the ZIP file
            with ZipFile(output_path, 'w', ZIP_DEFLATED) as zipf:
                for file_path in temp_path.rglob("*"):
                    if file_path.is_file():
                        arcname = file_path.relative_to(temp_path)
                        zipf.write(file_path, arcname)

    def _gather_system_info(self) -> str:
        """Gather system information for the export."""
        try:
            from rpi_logger.core import __version__
        except ImportError:
            __version__ = "Unknown"

        lines = [
            "RPi Logger - System Information",
            "=" * 50,
            f"Export Date: {datetime.datetime.now().isoformat()}",
            "",
            "Application:",
            f"  Version: {__version__}",
            f"  Python: {sys.version}",
            "",
            "Platform:",
            f"  System: {platform.system()}",
            f"  Release: {platform.release()}",
            f"  Machine: {platform.machine()}",
            f"  Platform: {sys.platform}",
            "",
            "Paths:",
            f"  Log Directory: {LOGS_DIR}",
            f"  Master Log: {MASTER_LOG_FILE}",
            f"  Module Logs: {MODULE_LOGS_DIR}",
        ]

        return "\n".join(lines)

    def _open_log_folder(self) -> None:
        """Open the log folder in the system file manager."""
        try:
            # Ensure directory exists
            LOGS_DIR.mkdir(parents=True, exist_ok=True)

            if sys.platform == "linux":
                subprocess.Popen(["xdg-open", str(LOGS_DIR)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(LOGS_DIR)])
            elif sys.platform == "win32":
                subprocess.Popen(["explorer", str(LOGS_DIR)])
        except Exception as e:
            logger.error("Failed to open log folder: %s", e)
            messagebox.showerror(
                "Error",
                f"Failed to open log folder:\n\n{e}",
                parent=self.dialog
            )
