"""CSI Cameras Module Quick Start Guide dialog."""
import tkinter as tk
from tkinter import ttk, scrolledtext
from rpi_logger.core.ui.theme.styles import Theme

CSI_CAMERAS_HELP_TEXT = """
=== CSI CAMERAS MODULE QUICK START GUIDE ===

OVERVIEW
CSI Cameras module captures synchronized video from Raspberry Pi camera
modules (IMX296, IMX219, IMX477, etc.) via CSI ribbon cable. Each camera
runs in its own instance with configurable resolution and frame rate.

GETTING STARTED
1. Connect camera via CSI ribbon cable
2. Enable camera interface in raspi-config
3. Enable "CSI Cameras" in Modules menu
4. Camera appears in Devices panel when detected
5. Click Connect to launch camera window

USER INTERFACE
Preview Display - Live feed at reduced resolution using ISP lores stream
Settings Window - Controls > Show Settings Window:
  Preview: Resolution (320x240-640x480), FPS (1-15)
  Record: Resolution (up to sensor max), FPS (1-60+)
IO Metrics - In/Rec/Tgt FPS, Queue depths, Wait time

OUTPUT FILES
Location: {session_dir}/CSICameras/{camera_id}/
  {prefix}_{camera_id}.avi - Video (AVI/MJPEG/YUV420P)
  {prefix}_{camera_id}_timing.csv - Per-frame timing

TIMING CSV COLUMNS
trial, device_time_unix, frame_index, capture_time_unix,
encode_time_mono, sensor_timestamp_ns, video_pts

SUPPORTED CAMERAS
  IMX296: Global shutter - no motion blur (precise timing)
  IMX219: Rolling shutter - Camera Module v2
  IMX477: Rolling shutter - High Quality Camera
  IMX708: Rolling shutter - Camera Module 3

All CSI cameras provide hardware timestamps (sensor_timestamp_ns),
precise frame rate control, ISP-accelerated preview, hardware exposure/gain.

DEFAULT SETTINGS
  Capture: 1280x720 @ 30fps, Preview: 320x180 @ 10fps, JPEG Quality: 80

TROUBLESHOOTING
Camera not detected: Check cable, raspi-config, 'libcamera-hello'
Laggy preview: Lower resolution/FPS, check CPU
Dropped frames: Lower FPS/resolution, use faster storage
Black video: Check cable/seating, test with 'libcamera-still -o test.jpg'
Color issues: Known IMX296 kernel bug - handled automatically
"""


class CSICamerasHelpDialog:
    """Dialog showing CSI Cameras quick start guide."""

    def __init__(self, parent):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("CSI Cameras Quick Start Guide")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        Theme.configure_toplevel(self.dialog)
        self.dialog.geometry("700x600")

        main_frame = ttk.Frame(self.dialog, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(main_frame, text="CSI Cameras Quick Start Guide").pack(pady=(0, 10))

        self.text_widget = scrolledtext.ScrolledText(ttk.Frame(main_frame), wrap=tk.WORD, state='disabled')
        Theme.configure_scrolled_text(self.text_widget, readonly=True)
        self.text_widget.master.pack(fill=tk.BOTH, expand=True)
        self.text_widget.pack(fill=tk.BOTH, expand=True)
        self.text_widget.config(state='normal')
        self.text_widget.insert('1.0', CSI_CAMERAS_HELP_TEXT)
        self.text_widget.config(state='disabled')

        ttk.Button(ttk.Frame(main_frame), text="Close", command=self.dialog.destroy).pack()
        self.dialog.protocol("WM_DELETE_WINDOW", self.dialog.destroy)
        x, y = parent.winfo_x() + parent.winfo_width() // 2 - 350, parent.winfo_y() + parent.winfo_height() // 2 - 300
        self.dialog.geometry(f"+{x}+{y}")
