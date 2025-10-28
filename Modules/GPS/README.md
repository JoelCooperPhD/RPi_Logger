# GPS2 Module

Simple GPS map viewer with offline tile support.

## Features

- ✅ TkinterMapView integration
- ✅ Automatic offline/online mode switching
- ✅ Async operations support via `async_handler`
- ✅ Works with main logger system

## Setup

### Download Offline Tiles (Optional but Recommended)

For offline operation, download map tiles:

```bash
cd Modules/GPS2
uv run python download_offline_tiles.py
```

This will:
- Download OpenStreetMap tiles for Salt Lake City area
- Create `offline_tiles.db` (~100MB)
- Take several minutes to complete

**Customize the region:** Edit `download_offline_tiles.py` and change:
```python
top_left_position = (40.9, -112.1)      # Your northwest corner
bottom_right_position = (40.5, -111.7)   # Your southeast corner
zoom_max = 16  # Higher = more detail but larger file
```

## Usage

### Standalone Mode

```bash
uv run python Modules/GPS2/main_GPS2.py
```

### With Main Logger

Enable in `Modules/GPS2/config.txt`:
```ini
enabled = true
```

Then launch the main logger.

## How It Works

- **Offline tiles exist:** Uses `offline_tiles.db` (no internet needed)
- **No offline tiles:** Downloads tiles from OpenStreetMap (internet required)
- Check logs to see which mode is active

## Adding Async Operations

Use `async_handler` for button callbacks:

```python
from async_tkinter_loop import async_handler

button = ttk.Button(
    frame,
    text="Do Something",
    command=async_handler(self._async_operation)
)

async def _async_operation(self):
    await asyncio.sleep(2)  # Non-blocking!
    # Update UI here
```

## Log Files

Logs are in `Modules/GPS2/logs/gps2.log`
