"""
About dialog for TheLogger.
"""

import io
import tkinter as tk
from tkinter import ttk

from ..theme import Theme
from ...paths import LOGO_PATH

try:
    from PIL import Image
except ImportError:
    Image = None


class AboutDialog:
    """Dialog showing application information."""

    def __init__(self, parent):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("About")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        Theme.configure_toplevel(self.dialog)

        self.dialog.geometry("500x350")
        self.dialog.resizable(False, False)

        main_frame = ttk.Frame(self.dialog, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        if Image:
            try:
                if LOGO_PATH.exists():
                    logo_image = Image.open(LOGO_PATH).convert("RGB")
                    # Use native Tk PhotoImage with PPM to avoid PIL ImageTk issues
                    ppm_data = io.BytesIO()
                    logo_image.save(ppm_data, format="PPM")
                    logo_photo = tk.PhotoImage(data=ppm_data.getvalue())
                    logo_label = ttk.Label(main_frame, image=logo_photo)
                    logo_label.image = logo_photo
                    logo_label.pack(pady=(0, 20))
            except Exception:
                pass

        title_label = ttk.Label(
            main_frame,
            text="RPi Logger"
        )
        title_label.pack()

        try:
            from rpi_logger.core import __version__
            version_text = f"Version {__version__}"
        except ImportError:
            version_text = "Version Unknown"

        version_label = ttk.Label(
            main_frame,
            text=version_text
        )
        version_label.pack(pady=(5, 20))

        info_text = (
            "Multi-modal data collection for human factors research.\n\n"
            "Synchronized recording of video, audio, eye tracking,\n"
            "GPS, visual occlusion, and behavioral response tasks.\n\n"
            "© 2025 RED Scientific"
        )

        info_label = ttk.Label(
            main_frame,
            text=info_text,
            justify=tk.CENTER
        )
        info_label.pack(pady=10)

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=(20, 0))

        close_button = ttk.Button(
            button_frame,
            text="Close",
            command=self.dialog.destroy
        )
        close_button.pack()

        self.dialog.protocol("WM_DELETE_WINDOW", self.dialog.destroy)

        x = parent.winfo_x() + (parent.winfo_width() // 2) - 250
        y = parent.winfo_y() + (parent.winfo_height() // 2) - 175
        self.dialog.geometry(f"+{x}+{y}")
