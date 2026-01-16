# GPS Module

The GPS module records location, speed, and heading data from a GPS receiver during experiment sessions. It provides real-time position tracking and can display your route on an offline map.

GPS devices connect via UART serial port (typically `/dev/serial0` on Raspberry Pi).

---

## Getting Started

1. Connect your GPS receiver (UART or USB-serial)
2. Ensure GPS has clear sky view for satellite lock
3. Enable the GPS module from the Modules menu
4. Wait for device detection and satellite fix
5. Start a session to begin recording

---

## User Interface

### Map Display

Shows current position on an offline map:
- Blue dot indicates current location
- Trail shows recent path
- Map tiles are cached for offline use

### Telemetry Panel

Real-time GPS data:

| Field | Description |
|-------|-------------|
| Latitude/Longitude | Current coordinates in decimal degrees |
| Speed | Current velocity (km/h or mph) |
| Heading | Direction of travel (0-360 degrees) |
| Altitude | Height above sea level (meters) |
| Satellites | Number of satellites in view |
| Fix Quality | GPS fix status (No Fix, 2D, 3D, DGPS) |

---

## Recording Sessions

### Starting Recording

When you start a recording session:
- GPS data logging begins immediately
- Position updates recorded at receiver rate (typically 1-10 Hz)
- Status shows connection and fix quality

### During Recording

Each data point captures:
- Timestamp (UTC from GPS satellites)
- Latitude and longitude
- Speed and heading
- Altitude and fix quality
- Number of satellites and accuracy metrics

---

## Data Output

### File Location

```
{session_dir}/GPS/
```

### Files Generated

| File | Description |
|------|-------------|
| `{timestamp}_GPS_{device_id}.csv` | Parsed GPS data (appended per session) |
| `{timestamp}_NMEA_trial{NNN}.txt` | Raw NMEA sentences (optional) |

Example: `20251208_143022_GPS_serial0.csv` (trial number is stored in the CSV data column)

### GPS CSV Columns (25 fields)

| Column | Description |
|--------|-------------|
| trial | Trial number (integer, 1-based) |
| module | Module name ("GPS") |
| device_id | GPS device identifier |
| label | Optional label (blank if unused) |
| record_time_unix | Host capture time (Unix seconds, 6 decimals) |
| record_time_mono | Host capture time (seconds, 9 decimals, `perf_counter`) |
| device_time_unix | GPS UTC time (Unix seconds) |
| latitude_deg | Latitude (decimal degrees, + = North) |
| longitude_deg | Longitude (decimal degrees, + = East) |
| altitude_m | Altitude above mean sea level (meters) |
| speed_mps | Speed over ground (m/s) |
| speed_kmh | Speed over ground (km/h) |
| speed_knots | Speed over ground (knots) |
| speed_mph | Speed over ground (mph) |
| course_deg | True course (degrees 0-360) |
| fix_quality | Fix type (0=None, 1=GPS, 2=DGPS, etc.) |
| fix_mode | Fix mode (1=None, 2=2D, 3=3D) |
| fix_valid | Fix valid flag (0/1) |
| satellites_in_use | Satellites in position solution |
| satellites_in_view | Total satellites visible |
| hdop | Horizontal dilution of precision |
| pdop | Position dilution of precision |
| vdop | Vertical dilution of precision |
| sentence_type | NMEA sentence type (GGA, RMC, etc.) |
| raw_sentence | Raw NMEA sentence |

**Example row:**
```
1,GPS,GPS:serial0,,1733665822.500000,12345.678901234,1733665822.500000,-37.8136,144.9631,42.5,12.3,44.3,23.9,27.5,185.2,1,3,1,8,12,1.2,1.8,2.1,GGA,$GPGGA,...
```

### Timing and Synchronization

**Timestamp Types:**

| Timestamp | Source | Use Case |
|-----------|--------|----------|
| device_time_unix | GPS satellites (Unix seconds) | Most accurate absolute time (atomic clock derived, ±100 ns) |
| record_time_unix | Host wall clock | Cross-system time reference |
| record_time_mono | Host monotonic clock | Cross-module synchronization |

**Cross-Module Synchronization:**
Use `record_time_mono` to correlate GPS with other modules.
- Audio `record_time_mono`
- Use `record_time_unix` for absolute time reference

**DOP Values (Dilution of Precision):**

| DOP | Quality | Position Accuracy |
|-----|---------|-------------------|
| < 1.0 | Ideal | Sub-meter |
| 1-2 | Excellent | ~1-2 meters |
| 2-5 | Good | ~5-10 meters |
| 5-10 | Moderate | ~50 meters |
| > 10 | Poor | Consider waiting for better fix |

---

## GPS Fix Quality

| Fix Type | Satellites | Description |
|----------|------------|-------------|
| No Fix | < 3 | Insufficient satellites visible |
| 2D Fix | 3 | Position available (lat/lon) but no altitude |
| 3D Fix | 4+ | Full position including altitude |
| DGPS | 4+ | Differential correction applied (sub-meter accuracy) |

---

## Configuration

| Setting | Default | Notes |
|---------|---------|-------|
| Serial Port | `/dev/serial0` | Raspberry Pi UART; may vary by connection |
| Baud Rate | 9600 | Must match GPS receiver (common: 9600, 38400, 115200) |
| Update Rate | Receiver dependent | Typically 1-10 Hz; higher = more detail but larger files |

---

## Offline Maps

The module uses pre-downloaded map tiles for offline display.

**Download tiles for your area:**
```bash
python -m rpi_logger.modules.GPS.download_offline_tiles
```

**Tile storage location:**
```
~/.cache/rpi_logger/map_tiles/
```

---

## Troubleshooting

### Device not detected

1. Check UART/serial or USB-serial connection
2. Verify correct serial port in config
3. Check baud rate matches GPS receiver (typically 9600)
4. Test serial connection with a terminal program (e.g., PuTTY, screen, minicom)

### No GPS fix

1. Move to area with clear sky view
2. Wait 1-2 minutes for cold start acquisition
3. Check antenna connection if using external antenna
4. Verify GPS receiver LED indicates searching

### Inaccurate position

1. Check number of satellites (need 4+ for 3D fix)
2. Move away from buildings/obstructions
3. Use external antenna for better reception
4. Wait for DGPS correction if available

### Map not displaying

1. Download offline tiles for your area
2. Check internet connection for initial download
3. Verify tile cache directory exists
4. Check available disk space

---

## Hardware Setup

### Serial Port Configuration

| Platform | Typical Port | Notes |
|----------|--------------|-------|
| Windows | COM3, COM4, etc. | Check Device Manager > Ports |
| macOS | /dev/tty.usbserial-* | Check System Information > USB |
| Linux | /dev/ttyUSB0, /dev/ttyACM0 | Check `ls /dev/tty*` |
| Raspberry Pi | /dev/serial0 | UART header or USB-serial adapter |

### Raspberry Pi UART Setup (BerryGPS)

For Raspberry Pi users with OzzMaker BerryGPS or similar UART GPS:

1. Enable serial port in `raspi-config`:
   - Interfacing Options > Serial
   - Login shell: No
   - Serial port: Yes
2. Reboot
3. Verify `/dev/serial0` points to the hardware UART

**Pi 5 only:** Add `dtparam=uart0_console` to `/boot/firmware/config.txt`

### Verifying GPS Connection

Test with a terminal program before launching:
- You should see NMEA sentences like `$GPRMC`, `$GPGGA`, etc.
- Data arrives at the configured baud rate (typically 9600)
