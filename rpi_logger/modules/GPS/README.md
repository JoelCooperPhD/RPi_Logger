# GPS

The GPS module integrates an OzzMaker **BerryGPS** receiver with the logger shell.
It renders a live map preview (powered by offline tiles) together with real-time
BerryGPS telemetry streamed from `/dev/serial0`.

## Hardware setup (BerryGPS guide recap)

BerryGPS talks to the Raspberry Pi over the main UART header. Recent Raspberry Pi
OS images assign the default console to the UART, so free it up for GPS use:

1. Update the OS, reboot, and disable the serial console while enabling the serial port.
   ```bash
   sudo apt-get update && sudo apt-get upgrade
   sudo raspi-config  # Interfacing Options → Serial → "Login shell?": No, "Serial port?": Yes
   sudo reboot
   ```
2. Confirm that `/dev/serial0` points to the hardware UART (`ttyS0` on Pi 3, `ttyAMA0`
   elsewhere). `ls -l /dev/serial0` should show the correct alias.
3. **Pi 5** only: append `dtparam=uart0_console` to `/boot/firmware/config.txt`
   so the alias points at the right controller, then reboot.

### Validating the GPS feed

Once BerryGPS is soldered to the Pi headers and powered, you can watch the raw
NMEA stream before launching the logger:

```bash
cat /dev/serial0
sudo apt-get install -y minicom screen
minicom -b 9600 -o -D /dev/serial0
screen /dev/serial0 9600
```

BerryGPS defaults to 9600 baud and emits `$GPVTG`, `$GPGGA`, `$GPGLL`, `$GPGSA`,
`$GPGSV`, and `$GPRMC` sentences (among others). The `$GPRMC` and `$GPGGA`
messages provide the fix status, latitude/longitude, altitude, satellite count,
and HDOP information the module consumes.

If you prefer to run `gpsd`, install `gpsd gpsd-clients`, set `DEVICES="/dev/serial0"`
inside `/etc/default/gpsd`, and start the `gpsd.socket` unit. Tools such as `cgps`,
`gpsmon`, and `gpspipe -r` are handy for cross-checking the parsed values.

## Offline map cache

The preview stitches cached raster tiles into a zoomable mosaic so that GPS fixes
are visible even without an internet connection. Generate the cache once:

```bash
uv run python rpi_logger/modules/GPS/download_offline_tiles.py
```

Use `--offline-db`, `--center-lat`, `--center-lon`, and `--zoom` if you want to
point the module at a different cache or starting view during development.

## Runtime features

- Zoomable offline map preview with pan-free recentering whenever a fresh fix arrives.
- Live telemetry sidebar showing fix status, satellites, HDOP/PDOP/VDOP, speed/heading,
  altitude, and the most recent `$GP***` sentence.
- Scrollable NMEA transcript so you can correlate the parser output with the raw stream.
- Automatic reconnection if `/dev/serial0` momentarily disappears (e.g., rebooting the HAT).

CLI knobs exposed via `main_gps.py` (or the module config UI):

| Flag | Description |
| --- | --- |
| `--serial-port /dev/serial0` | BerryGPS UART device alias. |
| `--baud-rate 9600` | Baud rate handed to pyserial. |
| `--reconnect-delay 3` | Seconds to wait between connection attempts. |
| `--nmea-history 30` | Number of recent sentences kept in the diagnostics panel. |

These values are mirrored in `config.txt` so the master logger UI can persist them per system.

## Recording

When the logger issues `start_recording`, the module writes a CSV to
`<session_dir>/GPS/<session_timestamp>_GPS.csv` (e.g.,
`session_20240520_140945/GPS/20240520_140945_GPS.csv`). This mirrors the folders that
Notes and Cameras create so downstream tooling can ingest the same session layouts.

Each row represents a decoded NMEA update. The first columns follow the shared schema:

| Column | Meaning |
| --- | --- |
| `trial` | Active trial number supplied by the main logger. |
| `recorded_at_unix` | UTC unix time (float) when the row was written. |
| `gps_timestamp_iso` | Timestamp embedded in the NMEA sentence, ISO 8601 in UTC. |
| `latitude_deg` / `longitude_deg` | Decimal-degree coordinates. |

Remaining columns capture `altitude_m`, `speed_mps`, `speed_kmh`, `speed_knots`,
`speed_mph`, `course_deg`, `fix_quality`, `fix_mode`, `fix_valid`, satellite counts,
HDOP/PDOP/VDOP, the originating `$GP***` sentence type, and the raw NMEA string.

Stop recording (or shutting down the module) closes the CSV cleanly so it can be
ingested by downstream tooling.

## Standalone test

```bash
uv run python rpi_logger/modules/GPS/main_gps.py --enable-commands --console
```

## Troubleshooting

- Use `cat /dev/serial0` or `minicom -b 9600 -o -D /dev/serial0` to confirm the Pi
  can see the NMEA stream before launching the module.
- If the UI reports "Offline map unavailable", regenerate tiles via
  `download_offline_tiles.py` or copy the `offline_tiles.db` cache back into the module.
- When the `Recent NMEA` panel stops updating, ensure no other process (such as gpsd)
  owns `/dev/serial0`. Disable `gpsd.socket` or point it at a different device.
- For Raspberry Pi 5 boards, confirm `dtparam=uart0_console` lives in
  `/boot/firmware/config.txt` so `/dev/serial0` is wired to the BerryGPS header.

## Diagnostics

If the preview reports missing tiles, regenerate the cache via the downloader
script above.
