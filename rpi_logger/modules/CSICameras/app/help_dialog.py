"""
CSI Cameras Module Quick Start Guide dialog.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext

from rpi_logger.core.ui.theme.styles import Theme


CSI_CAMERAS_HELP_TEXT = """
===================================================================
             CSI CAMERAS MODULE QUICK START GUIDE
===================================================================

OVERVIEW

The CSI Cameras module captures synchronized video from Raspberry Pi
camera modules (IMX296, IMX219, IMX477, etc.) connected via the CSI
(Camera Serial Interface) ribbon cable. Each camera runs in its own
module instance with configurable resolution and frame rate.

CSI cameras are discovered by the main logger and appear in the
Devices panel. Click Connect to launch a camera window.


-------------------------------------------------------------------
1. GETTING STARTED
-------------------------------------------------------------------

   1. Connect your camera via CSI ribbon cable
   2. Enable camera interface in raspi-config
   3. Enable "CSI Cameras" in the Modules menu
   4. The camera appears in the Devices panel when detected
   5. Click Connect to launch this camera's window
   6. Adjust settings if needed via the Controls menu
   7. Start a session to begin recording


-------------------------------------------------------------------
2. USER INTERFACE
-------------------------------------------------------------------

Preview Display
   Shows a live feed from this camera instance:
   * Preview runs at reduced resolution for performance
   * Uses ISP lores stream for efficient scaling
   * Each camera has its own dedicated window

Settings Window
   Access via Controls > Show Settings Window:
   * Preview Resolution: Display size (320x240 to 640x480)
   * Preview FPS: Live view frame rate (1-15)
   * Record Resolution: Capture size (up to sensor max)
   * Record FPS: Recording frame rate (1-60+)

IO Metrics Bar
   Shows real-time performance data:
   * Cam: Active camera ID
   * In: Input frame rate (from sensor)
   * Rec: Recording output rate
   * Tgt: Target recording FPS
   * Prv: Preview output rate
   * Q: Queue depths (preview/record)
   * Wait: Frame wait time (ms)


-------------------------------------------------------------------
3. OUTPUT FILES
-------------------------------------------------------------------

File Naming Convention
   {prefix}_{camera_id}.avi           - Video file
   {prefix}_{camera_id}_timing.csv    - Frame timing
   {prefix}_{camera_id}_metadata.csv  - Recording metadata

   Example: trial_001_picam_0_001.avi

Location
   {session_dir}/CSICameras/{camera_id}/

Video File Format
   Container:    AVI
   Codec:        MJPEG (Motion JPEG)
   Pixel Format: YUV420P
   Resolution:   Configurable (default 1280x720)
   Frame Rate:   Configurable (default 30 fps)

   Timestamp overlay shows: YYYY-MM-DDTHH:MM:SS.mmm #frame


-------------------------------------------------------------------
4. TIMING CSV FIELD REFERENCE
-------------------------------------------------------------------

The timing CSV contains per-frame timing for precise synchronization.

CSV Columns:
   trial             - Trial number (integer, may be empty)
   device_time_unix  - Device absolute time (Unix seconds, if available)
   frame_index       - 1-based frame number in video file
   capture_time_unix - Wall clock when captured (Unix seconds)
   encode_time_mono  - Monotonic time when encoded (9 decimals)
   sensor_timestamp_ns - Hardware sensor timestamp (nanoseconds)
   video_pts         - Presentation timestamp in video stream

Example Row:
   1,,1,1733649120.123456,123.456789012,1733649120123456789,1

Notes:
   * sensor_timestamp_ns: Hardware timestamp from Picamera2
     Provides precise timing from the sensor hardware
   * device_time_unix: May be empty if device does not provide an absolute clock
   * video_pts: Frame index used as PTS value
   * CSV row count = number of frames in video file


-------------------------------------------------------------------
5. TIMING & SYNCHRONIZATION
-------------------------------------------------------------------

Timestamp Precision:
   capture_time_unix   - Microsecond precision (6 decimals)
   encode_time_mono    - Nanosecond precision (9 decimals)
   sensor_timestamp_ns - Nanosecond precision (hardware)

Frame Timing Accuracy:
   * CSI cameras use hardware-enforced frame timing via
     FrameDurationLimits control
   * Provides consistent, accurate inter-frame timing

Synchronization:
   * Use sensor_timestamp_ns for highest precision sync
   * Use encode_time_mono for cross-module sync
   * Frame index in CSV matches video frame position
   * Periodic flush every 600 frames for data safety

Calculating Video Position:
   To find frame at time T:
   1. Search timing CSV for nearest capture_time_unix
   2. Use frame_index to seek in video file


-------------------------------------------------------------------
6. METADATA CSV REFERENCE
-------------------------------------------------------------------

The metadata CSV records session-level information.

CSV Columns:
   camera_id         - Camera identifier (e.g., "picam_0")
   backend           - Camera type ("picam")
   start_time_unix   - Session start (Unix seconds)
   end_time_unix     - Session end (Unix seconds)
   target_fps        - FPS used for encoding
   resolution_width  - Video frame width (pixels)
   resolution_height - Video frame height (pixels)
   video_path        - Path to video file
   timing_path       - Path to timing CSV


-------------------------------------------------------------------
7. SUPPORTED CAMERAS
-------------------------------------------------------------------

Raspberry Pi Camera Modules (CSI)
   * IMX296: Global shutter - no motion blur, ideal for
     fast-moving subjects and precise timing studies
   * IMX219: Rolling shutter - Raspberry Pi Camera Module v2
   * IMX477: Rolling shutter - High Quality Camera
   * IMX708: Rolling shutter - Camera Module 3

All CSI cameras provide:
   * Hardware sensor timestamps (sensor_timestamp_ns)
   * Precise frame rate control via FrameDurationLimits
   * ISP-accelerated preview scaling (lores stream)
   * Hardware-level exposure and gain control


-------------------------------------------------------------------
8. CONFIGURATION
-------------------------------------------------------------------

Default Settings:
   Capture Resolution:  1280x720
   Capture FPS:         30.0
   Record FPS:          30.0
   Preview Size:        320x180
   Preview FPS:         10.0
   JPEG Quality:        80

Preview Settings (for live display)
   * Resolution: Lower = smoother preview (320x240 recommended)
   * FPS: 5-10 is usually sufficient for monitoring

Record Settings (for saved video)
   * Resolution: Use native sensor resolution for best quality
   * FPS: Match your experiment requirements (30 or 60 typical)


===================================================================
                        TROUBLESHOOTING
===================================================================

Camera not appearing in Devices panel:
   1. Check ribbon cable connection and orientation
   2. Verify camera is enabled in raspi-config
   3. Enable "CSI Cameras" in the Modules menu
   4. Run 'libcamera-hello' to test camera detection
   5. Check /boot/config.txt for camera_auto_detect=1

Preview is laggy:
   1. Lower preview resolution (320x240)
   2. Reduce preview FPS (5 fps)
   3. Check CPU usage on the system
   4. Close other applications

Recording drops frames:
   1. Lower record FPS or resolution
   2. Use a faster SD card or SSD
   3. Check available disk space
   4. Monitor the Q (queue) metrics

Black or corrupted video:
   1. Check camera ribbon cable for damage
   2. Verify camera module is seated properly
   3. Test with 'libcamera-still -o test.jpg'
   4. Check for correct cable orientation (blue side up)

Color issues (red/blue swapped):
   This is a known kernel bug with some sensors (IMX296).
   The module automatically handles color format labeling.


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

        title_label = ttk.Label(
            main_frame,
            text="CSI Cameras Quick Start Guide"
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
        self.text_widget.insert('1.0', CSI_CAMERAS_HELP_TEXT)
        self.text_widget.config(state='disabled')
