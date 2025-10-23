# NoteTaker Module

Timestamped note-taking module for car logging sessions. Allows researchers to log observations and events during data collection with precise timestamps and session context.

## Features

- **Timestamped Notes**: Each note captures absolute timestamp and session elapsed time
- **Module State Tracking**: Records which modules (Camera, Audio, EyeTracker) are actively recording when note is added
- **Quick Entry**: Keyboard shortcuts for rapid note-taking while driving
- **Note History**: View all notes from current session in real-time
- **CSV Export**: Notes saved in CSV format for easy analysis with standard data science tools
- **Session Integration**: Notes saved to session directory alongside other module data

## Usage

### Standalone Mode

Launch the module directly:

```bash
# GUI mode
python main_notes.py --mode gui

# With custom output directory
python main_notes.py --mode gui --output-dir /path/to/notes

# Enable console output
python main_notes.py --mode gui --console
```

### Master Logger Integration

The module can be launched via the main logger system:

1. Enable in `config.txt`: `enabled = true`
2. Launch master logger: `python main_logger.py`
3. Select "NoteTaker" from module menu

## GUI Controls

### Recording Controls

- **File → Start Recording** (Ctrl+R): Start note recording session
- **File → Stop Recording** (Ctrl+R): Stop note recording session
- **File → Quit** (Ctrl+Q): Close window

### Note Entry

- **Ctrl+N**: Focus note entry text box
- **Enter**: Add note (when in entry box)
- **Shift+Enter**: New line in note text

### Display

- **View → Show Note History**: Toggle note history display

## Configuration

Edit `config.txt` to customize behavior:

```
# Module settings
enabled = false                    # Auto-start with master logger
window_x = 0                       # Window position (auto-saved)
window_y = 0
window_width = 600
window_height = 500

# Output settings
output_dir = notes                 # Output directory
session_prefix = notes             # Session prefix
log_level = info                   # Logging level
console_output = false             # Console output

# Recording settings
auto_start_recording = false       # Auto-start recording on launch

# GUI settings
gui_show_note_history = true       # Show note history by default
max_displayed_notes = 100          # Max notes to display
```

## Output Format

Notes are saved to CSV file: `session_notes.csv`

### CSV Columns

| Column | Description | Example |
|--------|-------------|---------|
| `timestamp` | Absolute timestamp (millisecond precision) | `2025-10-22 14:32:15.123` |
| `session_elapsed_time` | Time since session start (HH:MM:SS) | `00:05:23` |
| `note_text` | Text content of the note | `Sharp turn at intersection` |
| `recording_modules` | Modules recording when note was added | `Camera, Audio` |

### Example CSV Output

```csv
timestamp,session_elapsed_time,note_text,recording_modules
2025-10-22 14:30:00.123,00:00:00,Session started - clear weather,Camera, Audio, EyeTracker
2025-10-22 14:32:15.456,00:02:15,Sharp left turn at Main St,Camera, Audio
2025-10-22 14:35:42.789,00:05:42,Traffic light - full stop,Camera, Audio, EyeTracker
```

## Session Directory Structure

```
data/
└── session_20251022_143000/        # Session directory
    ├── master.log                   # Master logger log
    ├── NoteTaker/                   # NoteTaker subdirectory
    │   ├── notes.log               # Module log
    │   └── session_notes.csv       # Notes CSV file
    ├── Camera/                      # Other modules
    ├── Audio/
    └── EyeTracker/
```

## Architecture

The module follows the standard RPi_Logger architecture:

- **NotesSupervisor**: Manages system lifecycle with automatic retry on failures
- **NotesSystem**: Core system implementing BaseSystem interface
- **NotesHandler**: Note-taking logic and module state queries
- **RecordingManager**: CSV file writing and note storage
- **GUIMode**: GUI mode implementation with async tkinter integration
- **TkinterGUI**: GUI window with note entry and history display
- **CommandHandler**: Handles commands from master logger

## Dependencies

- Python 3.9+
- tkinter (GUI)
- Standard library: csv, asyncio, logging, datetime, json

## Integration with Other Modules

The NoteTaker module automatically detects which other modules are recording by reading the `running_modules.json` file maintained by the master logger. This allows notes to capture the current recording context without requiring direct communication with other modules.

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| Ctrl+R | Start/Stop Recording |
| Ctrl+N | Focus note entry |
| Enter | Add note (in entry box) |
| Shift+Enter | New line in note |
| Ctrl+Q | Quit application |

## Use Cases

### In-Car Logging

- Log observations during test drives
- Mark important events (turns, stops, traffic situations)
- Annotate specific moments for later video/audio review
- Track experimenter notes with precise timestamps

### Data Analysis

- Export CSV for correlation with video timestamps
- Filter notes by recording module combinations
- Calculate event frequencies by parsing note text
- Generate timeline visualizations

## Tips

- Keep notes concise for quick entry while driving
- Use consistent terminology for easier filtering later
- Start recording before beginning driving session
- Notes are automatically timestamped - no need to include time in text
- Multi-line notes are supported (use Shift+Enter)
