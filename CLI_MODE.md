# RPi Logger - CLI Interactive Mode

## Overview

The RPi Logger now supports **CLI Interactive Mode** for remote control and autonomous operation. This mode provides a command-line shell for managing the logger system without requiring a GUI, perfect for SSH access and automated deployment.

## Requirements

### Environment Setup

**IMPORTANT**: Module GUIs require a display. Set the `DISPLAY` environment variable:

```bash
# If running locally with X server
export DISPLAY=:0

# If connecting via SSH, use X11 forwarding
ssh -X user@raspberry-pi

# Or for automated scripts
DISPLAY=:0 python3 main_logger.py --mode interactive
```

## Usage

### Starting CLI Mode

```bash
# Basic usage
python3 main_logger.py --mode interactive

# With custom data directory
python3 main_logger.py --mode interactive --data-dir /path/to/data

# With DISPLAY set (required for module GUIs)
DISPLAY=:0 python3 main_logger.py --mode interactive
```

### Available Commands

Once in the interactive shell, you have access to these commands:

```
logger> help                          # Show all commands
logger> list                          # List available modules
logger> status                        # Show current system status
logger> start <module>                # Start a specific module
logger> stop <module>                 # Stop a module
logger> session start [directory]     # Start new session
logger> session stop                  # Stop current session
logger> record [label]                # Start recording a trial
logger> pause                         # Stop recording current trial
logger> quit                          # Graceful shutdown
```

## Complete Workflow Example

```bash
$ DISPLAY=:0 python3 main_logger.py --mode interactive

============================================================
RPi Logger - Interactive CLI
============================================================
Type 'help' for available commands, 'quit' to exit
============================================================

System Status:
------------------------------------------------------------
  Session: Inactive
  Running Modules (0):
    (none)
------------------------------------------------------------

logger> list

Available Modules:
------------------------------------------------------------
  Camera
  Audio
  GPS [enabled]        # Auto-starts on launch
  EyeTracker
  Notes [enabled]      # Auto-starts on launch
  DRT
------------------------------------------------------------

logger> status

System Status:
------------------------------------------------------------
  Session: Inactive
  Running Modules (2):
    - GPS
    - Notes
------------------------------------------------------------

logger> session start

Starting session...
✓ Session started
  Directory: /home/user/RPi_Logger/data/session_20251027_143052

logger> record "Highway test run"

Starting trial 1 (label: Highway test run)...
✓ Recording trial 1

logger> pause

Stopping trial...
✓ Trial 1 completed

logger> record "City driving"

Starting trial 2 (label: City driving)...
✓ Recording trial 2

logger> pause

Stopping trial...
✓ Trial 2 completed

logger> status

System Status:
------------------------------------------------------------
  Session: ACTIVE
    Directory: /home/user/RPi_Logger/data/session_20251027_143052
    Trials completed: 2
  Trial: Not recording

  Running Modules (2):
    - GPS
    - Notes
------------------------------------------------------------

logger> session stop

Stopping session...
✓ Session stopped

logger> quit

Shutting down...
```

## Features

### Auto-Start Modules

Modules marked as `enabled=true` in their config files will automatically start when the CLI launcher starts. This allows for autonomous operation.

**To enable auto-start for a module:**

Edit `Modules/<ModuleName>/config.txt`:
```ini
enabled = true
```

### Session Management

- **Automatic naming**: Sessions are automatically named with timestamp (e.g., `session_20251027_143052`)
- **Custom directory**: Use `session start /path/to/directory` to specify location
- **Event logging**: All actions are logged to `<session>/<timestamp>_CONTROL.csv`

### Trial Recording

- **Trial counter**: Automatically increments (trial 1, trial 2, ...)
- **Labels**: Add descriptive labels to trials: `record "Highway test"`
- **Automatic muxing**: A/V sync and muxing processes spawn automatically after each trial

### Error Handling

The CLI provides clear error messages for invalid operations:

```
logger> start InvalidModule
Error: Module 'InvalidModule' not found

logger> record
Error: No active session. Start a session first.

logger> pause
Error: No active trial

logger> session start
Starting session...
✓ Session started

logger> session start
Error: Session already active
```

## Deployment for Autonomous Operation

### Systemd Service (Auto-start on Boot)

Create `/etc/systemd/system/rpi-logger.service`:

```ini
[Unit]
Description=RPi Logger Autonomous System
After=network.target graphical.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/RPi_Logger
Environment="DISPLAY=:0"
ExecStart=/usr/bin/python3 /home/pi/RPi_Logger/main_logger.py --mode interactive
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable rpi-logger
sudo systemctl start rpi-logger
```

Check status:
```bash
sudo systemctl status rpi-logger
journalctl -u rpi-logger -f
```

### Remote SSH Control

When deployed autonomously, you can SSH in and attach to the running logger:

```bash
# SSH with X11 forwarding
ssh -X user@vehicle-pi

# Check if logger is running
sudo systemctl status rpi-logger

# View logs
tail -f /home/pi/RPi_Logger/logs/master.log

# For manual control, stop the service and run interactively
sudo systemctl stop rpi-logger
DISPLAY=:0 python3 main_logger.py --mode interactive
```

## Output Files

### Session Directory Structure

```
data/
└── session_20251027_143052/
    ├── 20251027_143052_CONTROL.csv      # Event log
    ├── 20251027_143052_NOTES.txt        # Notes taken during session
    ├── 20251027_143052_GPS_trial001.csv # GPS data
    ├── 20251027_143052_CAM_trial001_CAM0_1920x1080_30fps.mp4
    ├── 20251027_143052_CAMTIMING_trial001_CAM0.csv
    ├── 20251027_143052_AUDIO_trial001_MIC0_USB.wav
    ├── 20251027_143052_AUDIOTIMING_trial001_MIC0.csv
    ├── 20251027_143052_SYNC_trial001.json   # Sync metadata
    └── 20251027_143052_AV_trial001.mp4      # Muxed audio/video
```

### Event Log Format (CONTROL.csv)

```csv
timestamp,event_type,details
2025-10-27 14:30:52,session_start,path=data/session_20251027_143052
2025-10-27 14:31:05,trial_start,"trial=1, label=Highway test"
2025-10-27 14:35:12,trial_stop,trial=1
2025-10-27 14:36:20,trial_start,"trial=2, label=City driving"
2025-10-27 14:40:05,trial_stop,trial=2
2025-10-27 14:41:00,session_stop,
```

## Troubleshooting

### Module Windows Not Appearing

**Problem**: Modules fail to start or windows don't appear

**Solution**: Ensure `DISPLAY` environment variable is set
```bash
echo $DISPLAY  # Should show ":0" or similar
export DISPLAY=:0
```

### Modules Not Auto-Starting

**Problem**: Enabled modules don't start automatically

**Solution**: Check module config files
```bash
grep "enabled" Modules/*/config.txt
```

### Slow Shutdown

**Problem**: Modules take long time to stop

**Solution**: This is normal if modules are saving data. Wait for graceful shutdown or check logs:
```bash
tail -f logs/master.log
```

### "No Display" Error

**Problem**: `no display name and no $DISPLAY environment variable`

**Solution**:
1. If running locally: `export DISPLAY=:0`
2. If via SSH: Use `ssh -X` for X11 forwarding
3. If headless server: Install Xvfb virtual display

## Comparison: GUI vs CLI Mode

| Feature | GUI Mode | CLI Mode |
|---------|----------|----------|
| Interface | Tkinter windows | Command-line shell |
| Display required | Yes | Yes (for module GUIs) |
| Auto-start modules | ✓ | ✓ |
| Session control | Mouse/keyboard | Commands |
| Remote access | X11 forwarding | SSH + X11 forwarding |
| Logging | GUI + files | Files only |
| Autonomous operation | Requires interaction | Full automation possible |
| System service | Difficult | Easy (systemd) |

## Known Limitations

1. **Display Required**: Module GUIs require X server (DISPLAY must be set)
2. **Hardware Dependencies**: Some modules (GPS, Audio, Camera) require hardware
3. **Module Errors**: Hardware-dependent modules may fail gracefully without hardware
4. **Simultaneous Access**: Only one instance should control the logger at a time

## Advanced Usage

### Script Automation

You can pipe commands to the CLI for automated workflows:

```bash
cat << 'EOF' | DISPLAY=:0 python3 main_logger.py --mode interactive
session start
record "Automated test run"
pause
session stop
quit
EOF
```

### Integration with External Systems

The CLI can be integrated with other systems:
```bash
# Example: Start recording when GPS detects movement
while true; do
  if gps_moving; then
    echo "record 'Movement detected'" | ...
  fi
done
```

## Summary

CLI Interactive Mode provides:
- ✅ Full remote control via SSH
- ✅ Autonomous operation capability
- ✅ Auto-start enabled modules
- ✅ Comprehensive error handling
- ✅ Event logging
- ✅ Session and trial management
- ✅ Clean shutdown coordination

Perfect for in-vehicle deployment with remote monitoring and control capabilities.
