"""
Update available dialog for TheLogger.
"""

import tkinter as tk
from tkinter import ttk
import webbrowser

from ..theme import Theme
from ...update_checker import UpdateInfo


class UpdateAvailableDialog:
    """Dialog notifying user of available update."""

    def __init__(self, parent, update_info: UpdateInfo):
        self.update_info = update_info

        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Update Available")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        Theme.configure_toplevel(self.dialog)

        self.dialog.geometry("450x280")
        self.dialog.resizable(False, False)

        main_frame = ttk.Frame(self.dialog, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Title
        title_label = ttk.Label(
            main_frame,
            text="A New Version is Available!",
            font=('TkDefaultFont', 14, 'bold')
        )
        title_label.pack(pady=(0, 15))

        # Version info
        version_frame = ttk.Frame(main_frame)
        version_frame.pack(fill=tk.X, pady=10)

        current_label = ttk.Label(
            version_frame,
            text=f"Current version:  {update_info.current_version}"
        )
        current_label.pack()

        new_label = ttk.Label(
            version_frame,
            text=f"New version:      {update_info.latest_version}",
            font=('TkDefaultFont', 10, 'bold')
        )
        new_label.pack(pady=(5, 0))

        # Message
        message_label = ttk.Label(
            main_frame,
            text="Would you like to download the latest version?",
            justify=tk.CENTER
        )
        message_label.pack(pady=20)

        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=(10, 0))

        download_button = ttk.Button(
            button_frame,
            text="Download",
            command=self._on_download
        )
        download_button.pack(side=tk.LEFT, padx=5)

        later_button = ttk.Button(
            button_frame,
            text="Later",
            command=self.dialog.destroy
        )
        later_button.pack(side=tk.LEFT, padx=5)

        self.dialog.protocol("WM_DELETE_WINDOW", self.dialog.destroy)

        # Center on parent
        x = parent.winfo_x() + (parent.winfo_width() // 2) - 225
        y = parent.winfo_y() + (parent.winfo_height() // 2) - 140
        self.dialog.geometry(f"+{x}+{y}")

    def _on_download(self):
        """Open the download page in browser."""
        webbrowser.open_new(self.update_info.download_url)
        self.dialog.destroy()
