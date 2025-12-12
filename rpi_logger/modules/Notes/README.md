# Notes Module

The Notes module allows you to add timestamped annotations during experiment sessions. Notes are synchronized with other data streams and saved to a CSV file for later analysis.

Use notes to mark events, observations, or participant comments during your experiments.

---

## Getting Started

1. Enable the Notes module from the Modules menu
2. Start a session from the main logger
3. Type your note in the text field
4. Press Enter or click "Post" to save

---

## User Interface

### History Panel

Displays previously entered notes with:

| Element | Description |
|---------|-------------|
| Timestamp | When the note was created (blue text) |
| Elapsed Time | Time since recording started (green text) |
| Module Tags | Which modules were recording (purple tags) |
| Note Content | Your annotation text |

### New Note Field

- Type your annotation text in the input field
- Press **Enter** to submit (Shift+Enter for newline)
- Click **"Post"** button to save

---

## Recording Notes

### Adding a Note

1. Type your observation in the text field
2. Press Enter or click "Post"
3. Note appears in history with timestamp
4. Data is immediately saved to file

### Note Content Tips

- Keep notes brief and descriptive
- Use consistent terminology across sessions
- Include relevant trial or condition info
- Note unexpected events or errors

### Auto-Recording

Notes recording starts automatically when:
- A session is active
- You type and submit a note

---

## Data Output

### File Location

```
{session_dir}/Notes/{timestamp}_NOTES_trial{NNN}.csv
```

Example: `20251208_143022_NOTES_trial001.csv`

### CSV Columns (4 fields)

| Column | Description |
|--------|-------------|
| Note | Row identifier (always "Note") |
| trial | Trial number (integer, 1-based) |
| Content | Your annotation text (string) |
| Timestamp | Unix timestamp (seconds with 6 decimal places) |

**Example row:**
```
Note,1,Participant started task,1733649123.456789
```

### Timing and Synchronization

**Timestamp Precision:**
- Unix timestamp with microsecond precision (6 decimal places)
- Recorded at the moment you press Enter/Post

**Cross-Module Synchronization:**
Use the Timestamp column to correlate notes with:
- Video frames (via camera `capture_time_unix`)
- Audio samples (via audio `write_time_unix`)
- DRT trials (via `Unix time in UTC`)
- Eye tracking data (via `record_time_unix`)
- GPS position (via `timestamp_unix`)

**Example: Finding video frame for a note**
1. Read note Timestamp (e.g., `1733649123.456789`)
2. Search camera timing CSV for nearest `capture_time_unix`
3. Use `frame_index` to locate frame in video file

---

## Configuration

| Setting | Description | Default |
|---------|-------------|---------|
| History Limit | Maximum notes displayed in history panel | 200 |
| Auto-Start | Automatically begin recording when session starts | Off |

---

## Best Practices

### During Experiments

- Note start/end of conditions or trials
- Record participant comments verbatim
- Mark equipment issues or interruptions
- Document environmental changes

### For Analysis

- Use consistent note formats across sessions
- Include trial/condition identifiers when relevant
- Timestamp critical events as they happen
- Note anything unusual for later reference

---

## Troubleshooting

### Notes not saving

1. Verify a session is active
2. Check the session directory is writable
3. Start session from main logger first
4. Review module logs for errors

### History not updating

1. Notes appear after pressing Enter/Post
2. Check that note field is not empty
3. Scroll to bottom of history panel
4. Restart module if display freezes

### "Session required" message

1. Start a session from the main RPi Logger first
2. Use "Start Session" button before adding notes

### Lost notes after crash

- Notes are saved immediately to disk
- Check session directory for CSV file
- Partial data should be recoverable
