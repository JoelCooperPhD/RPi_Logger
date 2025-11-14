# GPS (Stub)

GPS logger module built on the stub (codex) VMC stack. This port reuses the
legacy GPS handler/recording components while adopting the shared controller,
logging, and window management used by the other stubbed modules.

## Features

- Async serial handling via `serial_asyncio` and the existing `GPSHandler`
- GUI embedding inside the stub placeholder window with map, status, and raw NMEA
- Optional offline tile database support (`offline_tiles.db`)
- Manual zoom controls (with persistence to `config.txt`)
- Recording management identical to the original module (CSV per trial)

## Usage

```bash
uv run python rpi_logger/modules/GPS\ \(stub\)/main_gps_stub.py \
    --enable-commands \
    --mode gui
```

The module is intended to be launched by the main logger controller, which
supplies `--enable-commands`, output/session directories, and command routing.

Key configuration values live in `config.txt` and include the serial port,
baud rate, discovery timeouts, and default map position. Offline tiles default
to a local `offline_tiles.db` file inside this module; if it is missing the
runtime automatically copies `modules/GPS/offline_tiles.db` so existing downloads
continue to work.

## Offline tiles workflow

The OpenStreetMap tile database is **not** committed to Git. Create or copy it
locally before launching the module:

1. Generate a seed database via the original GPS module helper:
   ```bash
   cd rpi_logger/modules/GPS
   uv run python download_offline_tiles.py
   ```
2. Copy the resulting `offline_tiles.db` into `rpi_logger/modules/GPS (stub)/`.
   The runtime also copies the file automatically if it detects
   `modules/GPS/offline_tiles.db`.
3. Keep these databases out of Git history (they are ignored via `.gitignore`).

Without the file the stub automatically falls back to online tiles, so normal
testing still works even when you skip the download step.

## Requirements

- `serial_asyncio` (pyserial async transport) for GPS communication
- `tkinter` and `tkintermapview` for GUI rendering (GUI mode only)
- Optional `offline_tiles.db` (auto-copied from `modules/GPS/offline_tiles.db`
  when available)
