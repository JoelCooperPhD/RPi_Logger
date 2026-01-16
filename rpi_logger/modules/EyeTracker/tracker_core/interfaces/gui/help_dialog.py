"""Eye Tracker Quick Start Guide dialog."""

import tkinter as tk
from tkinter import ttk, scrolledtext

from rpi_logger.core.ui.theme.styles import Theme


EYETRACKER_HELP_TEXT = """
═══════════════════════════════════════════════════════════════════
             EYETRACKER-NEON MODULE QUICK START GUIDE
═══════════════════════════════════════════════════════════════════

OVERVIEW

The EyeTracker-Neon module captures gaze data and scene video from
Pupil Labs Neon eye tracking glasses. It records where participants
are looking in real-time, synchronized with other data streams.

The Neon tracker connects via network (WiFi or USB tethering).


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. GETTING STARTED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   1. Power on your Pupil Labs Neon glasses
   2. Connect via WiFi (same network as host) or USB tethering
   3. Enable the EyeTracker-Neon module from the Modules menu
   4. Wait for device connection (status shows "Connected")
   5. Calibrate if needed using Pupil Capture
   6. Start a session to begin recording


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2. USER INTERFACE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Preview Display
   Shows the scene camera feed with gaze overlay:
   • Red circle indicates current gaze position
   • Scene video shows participant's view

Device Status Panel
   • Device: Connected device name
   • Status: Connection state (Connected/Disconnected)
   • Recording: Current recording state (Active/Idle)

Controls
   • Configure: Open device settings dialog


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3. RECORDING SESSIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Starting a Session
   When you start a recording session:
   • Gaze data recording begins
   • Scene video capture starts
   • Status shows "Active"

During Recording
   Each trial captures:
   • Gaze coordinates (x, y) normalized to scene
   • Pupil diameter for each eye
   • Confidence values for gaze estimation
   • Scene video with embedded timestamps


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3.5. OUTPUT FILES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

File Naming Convention
   {timestamp}_EYETRACKER-NEON_{type}_trial{NNN}.{ext}

   Types: GAZEDATA, GAZE, EVENT, IMU, FRAME, AUDIO_TIMING,
          DEVICESTATUS, SCENE

   Example: 20251208_143022_EYETRACKER-NEON_GAZEDATA_trial001.csv
            20251208_143022_EYETRACKER-NEON_SCENE_trial001.mp4

Location
   {session_dir}/EyeTracker-Neon/

Scene Video Format
   Container:    MP4
   Codec:        H.264
   Resolution:   Configurable (default 1280x720)
   Frame Rate:   Configurable (default 5 fps for preview)


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3.6. CSV FIELD REFERENCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

All CSVs use the standard prefix: trial, module, device_id, label,
record_time_unix, record_time_mono followed by device-specific fields.

GAZE CSV (36 fields):
   trial               - Trial number (1-based)
   module              - Module name ("EyeTracker")
   device_id           - Device identifier ("eye_tracker")
   label               - Optional trial label
   record_time_unix    - System capture time (Unix seconds, 6 decimals)
   record_time_mono    - Monotonic capture time (seconds, 9 decimals)
   device_time_unix    - Device gaze timestamp (Unix seconds)
   device_time_ns      - Device timestamp in nanoseconds
   stream_type         - Data stream type
   worn                - Glasses worn status (0/1)
   x, y                - Normalized gaze position (0-1)
   left_x, left_y      - Left eye gaze (0-1)
   right_x, right_y    - Right eye gaze (0-1)
   pupil_diameter_left/right  - Pupil diameter (mm)
   eyeball_center_*    - 3D eye center positions (x/y/z for left/right)
   optical_axis_*      - 3D gaze direction vectors (x/y/z for left/right)
   eyelid_angle_*      - Eyelid angles (top/bottom for left/right)
   eyelid_aperture_*   - Eyelid openness (left/right)

EVENTS CSV (24 fields):
   trial               - Trial number (1-based)
   module              - Module name ("EyeTracker")
   device_id           - Device identifier ("eye_tracker")
   label               - Optional trial label
   record_time_unix    - System capture time (Unix seconds, 6 decimals)
   record_time_mono    - Monotonic capture time (seconds, 9 decimals)
   device_time_unix    - Device event timestamp (Unix seconds)
   device_time_ns      - Device timestamp in nanoseconds
   event_type          - Event type: fixation, blink, or saccade
   event_subtype       - Event category
   confidence          - Event confidence (0-1)
   duration            - Event duration (seconds)
   start_time_ns, end_time_ns - Event time range
   start_gaze_x/y, end_gaze_x/y - Gaze positions
   mean_gaze_x/y       - Average gaze position
   amplitude_pixels/angle_deg - Saccade amplitude
   mean_velocity, max_velocity - Saccade velocity

IMU CSV (19 fields):
   trial               - Trial number (1-based)
   module              - Module name ("EyeTracker")
   device_id           - Device identifier ("eye_tracker")
   label               - Optional trial label
   record_time_unix    - System capture time (Unix seconds, 6 decimals)
   record_time_mono    - Monotonic capture time (seconds, 9 decimals)
   device_time_unix    - Device IMU timestamp (Unix seconds)
   device_time_ns      - Device timestamp in nanoseconds
   gyro_x/y/z          - Gyroscope (rad/s)
   accel_x/y/z         - Accelerometer (m/s²)
   quat_w/x/y/z        - Orientation quaternion
   temperature         - Sensor temperature

FRAME CSV (6 fields):
   Module              - Always "EyeTracker-Neon"
   trial               - Trial number (1-based)
   frame_index         - 1-based frame number in video
   capture_timestamp   - Device capture time (Unix seconds)
   record_time_unix    - System time when recorded
   record_time_mono    - Monotonic time (seconds, 9 decimals)


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3.7. TIMING & SYNCHRONIZATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Timestamp Types:
   gaze_timestamp      - Pupil Labs device clock (Unix seconds)
   record_time_unix    - Host system wall clock (may drift)
   record_time_mono    - Host monotonic clock (never jumps)

Timing Accuracy:
   Gaze samples:       ~5-10 ms between samples (device-dependent)
   Frame timestamps:   Frame-accurate from RTSP stream
   Audio timestamps:   Chunk-based (typically 1024 samples)

Cross-Module Synchronization:
   Use record_time_mono for precise cross-module sync:
   • Correlate with camera encode_time_mono
   • Correlate with audio record_time_mono
   • Correlate with DRT record_time_mono/record_time_unix

Video-Gaze Alignment:
   Use FRAME CSV to correlate video frames with gaze data:
   1. Find frame_index for desired video position
   2. Match capture_timestamp to gaze_timestamp
   3. Gaze samples between frames belong to that period


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
4. CONFIGURATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Click "Configure" to access device settings.

Available Settings:
   • Scene Camera Resolution
   • Gaze Sample Rate
   • Pupil Detection Threshold
   • Network Connection Settings


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5. DATA INTERPRETATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Gaze Position (norm_x, norm_y)
   Normalized coordinates (0-1) in scene camera view.
   (0,0) is top-left, (1,1) is bottom-right.

Confidence
   Quality of gaze estimate (0-1).
   Higher values indicate more reliable tracking.

Pupil Diameter
   Measured in millimeters.
   Changes reflect cognitive load and lighting.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
6. CALIBRATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

For accurate gaze data, calibrate before each session:

   1. Open Pupil Capture on the host computer
   2. Select appropriate calibration method
   3. Follow on-screen instructions
   4. Verify accuracy with validation targets

Recalibrate if:
   • Glasses are repositioned on face
   • Significant time has passed
   • Gaze accuracy appears poor


═══════════════════════════════════════════════════════════════════
                        TROUBLESHOOTING
═══════════════════════════════════════════════════════════════════

Device not detected:
   1. Check USB cable connection
   2. Verify Pupil Capture is running
   3. Check network settings if using WiFi
   4. Restart the module if needed

No gaze data appearing:
   1. Ensure calibration was completed
   2. Check pupil detection in Pupil Capture
   3. Verify adequate lighting conditions
   4. Clean eye camera lenses

Scene video not recording:
   1. Check scene camera connection
   2. Verify camera is not in use by other app
   3. Check available disk space
   4. Review module logs for errors

Poor gaze accuracy:
   1. Recalibrate the tracker
   2. Ensure glasses fit snugly
   3. Check for reflections on lenses
   4. Verify pupil detection is stable


"""


class EyeTrackerHelpDialog:
    """Dialog showing EyeTracker-Neon quick start guide."""

    def __init__(self, parent):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("EyeTracker-Neon Quick Start Guide")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        Theme.configure_toplevel(self.dialog)

        self.dialog.geometry("700x600")

        main_frame = ttk.Frame(self.dialog, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        title_label = ttk.Label(
            main_frame,
            text="EyeTracker-Neon Quick Start Guide"
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
        self.text_widget.insert('1.0', EYETRACKER_HELP_TEXT)
        self.text_widget.config(state='disabled')
