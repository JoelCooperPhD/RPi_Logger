"""
Cameras Module Quick Start Guide dialog.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext

from rpi_logger.core.ui.theme.styles import Theme


CAMERAS_HELP_TEXT = """
═══════════════════════════════════════════════════════════════════
                 CAMERAS MODULE QUICK START GUIDE
═══════════════════════════════════════════════════════════════════

OVERVIEW
Records synchronized video from RPi CSI cameras (IMX296, etc.) and USB cameras.
Each camera runs in its own instance with configurable resolution and frame rate.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. QUICK START
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   1. Connect camera (CSI/USB)
   2. Enable in Modules menu
   3. Click Connect in Devices panel
   4. Adjust settings (Controls > Settings)
   5. Start session to record

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2. INTERFACE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Preview: Live feed at reduced resolution
Settings: Preview/Record resolution & FPS (Controls menu)
Metrics: Real-time Cap In/Tgt, Rec Out/Tgt, Disp/Tgt


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3. OUTPUT FILES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Files: {prefix}_{camera_id}.avi, *_timing.csv, *_metadata.csv
Location: {session_dir}/Cameras/{camera_id}/
Format: AVI/MJPEG/YUV420P, default 1280x720@30fps
Overlay: YYYY-MM-DDTHH:MM:SS.mmm #frame


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
4. TIMING CSV
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Columns: trial, device_time_unix, frame_index, capture_time_unix,
         encode_time_mono, sensor_timestamp_ns, video_pts
Note: sensor_timestamp_ns only for CSI cameras (empty for USB)


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5. SYNCHRONIZATION & METADATA
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Sync: Use encode_time_mono for cross-module sync
Metadata CSV: camera_id, backend, start/end_time_unix, target_fps,
              resolution, video_path, timing_path

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
6. CAMERA TYPES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CSI (IMX296/219/477): Hardware timestamps, global/rolling shutter
USB (UVC): No hardware timestamps, variable FPS

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
7. CONFIGURATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Defaults: Capture 1280x720@30fps, Preview 320x180@10fps, JPEG Q=80
Preview: Lower res = smoother (320x240@5-10fps recommended)
Record: Use native sensor res for quality (30-60fps typical)


═══════════════════════════════════════════════════════════════════
                        TROUBLESHOOTING
═══════════════════════════════════════════════════════════════════
Camera not detected: Check cable/USB, enable in Modules menu,
  verify with 'libcamera-hello' or 'v4l2-ctl --list-devices'
Laggy preview: Lower preview res (320x240@5fps), check CPU
Dropped frames: Lower FPS/res, use faster storage, check disk space
Corrupted video: Check cable/seating, test with 'libcamera-still'
Empty sensor_timestamp_ns: Normal for USB (use encode_time_mono)
"""


class CamerasHelpDialog:
    """Dialog showing Cameras quick start guide."""

    def __init__(self, parent):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Cameras Quick Start Guide")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        Theme.configure_toplevel(self.dialog)

        self.dialog.geometry("700x600")

        main_frame = ttk.Frame(self.dialog, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        title_label = ttk.Label(
            main_frame,
            text="Cameras Quick Start Guide"
        )
        title_label.pack(pady=(0, 10))

        text_frame = ttk.Frame(main_frame)
        text_frame.pack(fill=tk.BOTH, expand=True)

        self.text_widget = scrolledtext.ScrolledText(
            text_frame,
            wrap=tk.WORD,
            state='disabled'
        )
        Theme.configure_scrolled_text(self.text_widget, readonly=True)
        self.text_widget.pack(fill=tk.BOTH, expand=True)

        self._populate_help()

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=(10, 0))

        close_button = ttk.Button(
            button_frame,
            text="Close",
            command=self.dialog.destroy
        )
        close_button.pack()

        self.dialog.protocol("WM_DELETE_WINDOW", self.dialog.destroy)

        x = parent.winfo_x() + (parent.winfo_width() // 2) - 350
        y = parent.winfo_y() + (parent.winfo_height() // 2) - 300
        self.dialog.geometry(f"+{x}+{y}")

    def _populate_help(self):
        self.text_widget.config(state='normal')
        self.text_widget.insert('1.0', CAMERAS_HELP_TEXT)
        self.text_widget.config(state='disabled')
