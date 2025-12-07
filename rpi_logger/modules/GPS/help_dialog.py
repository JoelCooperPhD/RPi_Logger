"""
GPS Module Quick Start Guide dialog.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext

from rpi_logger.core.ui.theme.styles import Theme


GPS_HELP_TEXT = """
═══════════════════════════════════════════════════════════════════
                    GPS MODULE QUICK START GUIDE
═══════════════════════════════════════════════════════════════════

OVERVIEW

The GPS module records location, speed, and heading data from
a GPS receiver during experiment sessions. It provides real-time
position tracking and can display routes on an offline map.

GPS devices connect via UART serial port.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. GETTING STARTED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   1. Connect your GPS receiver (UART or USB-serial)
   2. Ensure GPS has clear sky view for satellite lock
   3. Enable the GPS module from the Modules menu
   4. Wait for device detection and satellite fix
   5. Start a session to begin recording


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2. USER INTERFACE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Map Display
   Shows current position on an offline map:
   • Blue dot indicates current location
   • Trail shows recent path
   • Map tiles cached for offline use

Telemetry Panel
   Real-time GPS data:
   • Latitude/Longitude: Current coordinates
   • Speed: Current velocity (km/h or mph)
   • Heading: Direction of travel (degrees)
   • Altitude: Height above sea level
   • Satellites: Number of satellites in view
   • Fix Quality: GPS fix status


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3. RECORDING SESSIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Starting a Session
   When you start a recording session:
   • GPS data logging begins
   • Position updates recorded at configured rate
   • Status shows connection and fix quality

During Recording
   Each data point captures:
   • Timestamp (UTC from GPS)
   • Latitude and longitude
   • Speed and heading
   • Altitude and fix quality
   • Number of satellites

Data Output
   GPS data is saved as CSV:
   {session_dir}/GPS/{timestamp}_GPS_trial{N}.csv

   NMEA sentences (raw data):
   {session_dir}/GPS/{timestamp}_NMEA_trial{N}.txt


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
4. CONFIGURATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Serial Port
   Default: /dev/serial0 (Raspberry Pi UART)
   May vary depending on GPS receiver connection.

Baud Rate
   Common values: 9600, 38400, 115200
   Must match GPS receiver settings.

Update Rate
   How often GPS reports position (1-10 Hz).
   Higher rates provide more detail but larger files.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5. GPS FIX QUALITY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

No Fix
   Insufficient satellites visible.
   Ensure clear view of sky.

2D Fix
   Position available (lat/lon) but no altitude.
   Minimum 3 satellites required.

3D Fix
   Full position including altitude.
   Minimum 4 satellites required.

DGPS Fix
   Differential correction applied.
   Higher accuracy (sub-meter possible).


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
6. OFFLINE MAPS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

The module uses pre-downloaded map tiles for offline display.

To download tiles for your area:
   python -m rpi_logger.modules.GPS.download_offline_tiles

Tiles are stored in:
   ~/.cache/rpi_logger/map_tiles/

Supported tile sources:
   • OpenStreetMap (default)
   • Custom tile servers


═══════════════════════════════════════════════════════════════════
                        TROUBLESHOOTING
═══════════════════════════════════════════════════════════════════

Device not detected:
   1. Check UART/serial connection
   2. Verify correct serial port in config
   3. Check baud rate matches GPS receiver
   4. Run 'cat /dev/serial0' to test (Ctrl+C to stop)

No GPS fix:
   1. Move to area with clear sky view
   2. Wait 1-2 minutes for cold start acquisition
   3. Check antenna connection if using external antenna
   4. Verify GPS receiver LED indicates searching

Inaccurate position:
   1. Check number of satellites (need 4+ for 3D fix)
   2. Move away from buildings/obstructions
   3. Use external antenna for better reception
   4. Wait for DGPS correction if available

Map not displaying:
   1. Download offline tiles for your area
   2. Check internet connection for initial download
   3. Verify tile cache directory exists
   4. Check available disk space


"""


class GPSHelpDialog:
    """Dialog showing GPS quick start guide."""

    def __init__(self, parent):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("GPS Quick Start Guide")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        Theme.configure_toplevel(self.dialog)

        self.dialog.geometry("700x600")

        main_frame = ttk.Frame(self.dialog, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        title_label = ttk.Label(
            main_frame,
            text="GPS Quick Start Guide"
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
        self.text_widget.insert('1.0', GPS_HELP_TEXT)
        self.text_widget.config(state='disabled')

