# Logging System

This document describes the Logger project's centralized logging architecture, log levels, file locations, and troubleshooting guidance.

---

## Log Level Definitions

| Level | When to Use | Examples |
|-------|-------------|----------|
| **DEBUG** | Verbose diagnostics for developers. First-time initialization, state changes, configuration details. Never in hot loops. | "Module registered: X", "Stream connected", "Config loaded from X" |
| **INFO** | Significant operational events the user should see. Start/stop of major components, successful completions, user-triggered actions. | "Recording started", "Device connected", "Scanner started" |
| **WARNING** | Something unexpected but recoverable happened. Degraded functionality, fallbacks used, deprecated usage. Operation continues. | "Device reconnecting", "Fallback to default config", "Rate limited" |
| **ERROR** | Operation failed but application continues. Specific operation couldn't complete, but other operations unaffected. | "Failed to save file", "Device communication error", "API request failed" |
| **CRITICAL** | Application-wide failure, likely to cause shutdown. Should be extremely rare. | "Database corrupted", "Cannot allocate memory" |

---

## Log File Locations

Log files are stored in platform-specific directories following OS conventions:

| Platform | Location |
|----------|----------|
| **Linux** | `~/.local/state/rpi_logger/logs/` |
| **macOS** | `~/Library/Logs/RPILogger/` |
| **Windows** | `%LOCALAPPDATA%\RPILogger\logs\` |

### Directory Structure

```
logs/
├── master.log           # Main application log
└── modules/             # Per-module log files
    ├── Audio.log
    ├── Cameras.log
    ├── DRT.log
    └── ...
```

### Environment Override

Set `RPI_LOGGER_STATE_DIR` to override the default log location:

```bash
export RPI_LOGGER_STATE_DIR=/custom/path
# Logs will be written to /custom/path/logs/
```

---

## Log Rotation

Log files use rotating file handlers to prevent unbounded growth:

| Setting | Default | Description |
|---------|---------|-------------|
| Max file size | 300 KB | File rotates when this size is reached |
| Backup count | 3 | Number of rotated files kept (e.g., `master.log.1`, `master.log.2`) |

File logging always captures at **DEBUG** level regardless of UI display settings, ensuring full diagnostics are available for troubleshooting.

---

## Controlling Log Levels

### UI: View Menu

In the main application window, use **View > Log Level** to control what's shown in the log panel:

- Debug (most verbose)
- Info (default)
- Warning
- Error
- Critical (least verbose)

This only affects UI display. File logging remains at DEBUG.

### CLI: Module Arguments

When running modules standalone, use the `--log-level` argument:

```bash
python -m rpi_logger.modules.Cameras.main_cameras --log-level debug
python -m rpi_logger.modules.DRT.main_drt --log-level warning
```

Valid values: `debug`, `info`, `warning`, `error`, `critical`

### API: Debug Endpoints

Toggle debug mode at runtime via the API:

```bash
# Check current mode
curl http://localhost:8080/api/v1/debug/mode

# Enable debug mode
curl -X POST http://localhost:8080/api/v1/debug/mode -d '{"enabled": true}'
```

---

## Architecture

### Master-Module Logging

The Logger uses a multi-process architecture where each module runs as a subprocess:

```
Master Process                    Module Subprocess
┌──────────────────┐              ┌───────────────────────┐
│ MainWindow       │              │ ModuleLogManager      │
│ - Log Panel UI   │◄─────────────│ - File: DEBUG always  │
│ - Log Level Menu │  forwarding  │ - Console: varies     │
└──────────────────┘              │ - UI forward: varies  │
                                  └───────────────────────┘
```

**Key behaviors:**

1. **File handler** - Always captures DEBUG level for full diagnostics
2. **Console handler** - Respects user-configured level
3. **Forwarding handler** - Optionally sends logs to master for unified UI display

### Log Format

All logs use a consistent format:

```
2026-01-15 14:30:22 | INFO     | rpi_logger.core.logger_system | [LoggerSystem] Session started
```

Format: `%(asctime)s | %(levelname)-8s | %(name)s | %(message)s`

### StructuredLogger

The project uses `StructuredLogger` wrappers that add component prefixes:

```python
from rpi_logger.core.logging_utils import get_module_logger

logger = get_module_logger("MyModule")
logger.info("Operation completed")  # Output: [MyModule] Operation completed
```

---

## Troubleshooting with Logs

### Common Issues

**Module not starting:**
1. Check `logs/modules/<ModuleName>.log` for startup errors
2. Look for ERROR or CRITICAL level messages
3. Check for missing dependencies or configuration issues

**Device not detected:**
1. Set log level to DEBUG via View > Log Level
2. Check for device discovery messages in the log panel
3. Look for USB/serial connection errors

**Recording issues:**
1. Check module-specific log file during recording
2. Look for file I/O errors or disk space warnings
3. Verify session directory permissions

### Reading Log Files

```bash
# View recent master log entries
tail -100 ~/.local/state/rpi_logger/logs/master.log

# Follow log in real-time
tail -f ~/.local/state/rpi_logger/logs/master.log

# Search for errors
grep -i error ~/.local/state/rpi_logger/logs/master.log

# View specific module log
cat ~/.local/state/rpi_logger/logs/modules/DRT.log
```

### Log Analysis Tips

1. **Correlate timestamps** - Use `record_time_unix` from CSV files to find corresponding log entries
2. **Check rotation** - If investigating old issues, check `.log.1`, `.log.2` backup files
3. **Filter by level** - Use `grep "ERROR\|CRITICAL"` to find problems quickly
4. **Module prefix** - Log messages include `[ModuleName]` prefix for easy filtering

---

## Best Practices for Developers

### When to Log

| Do Log | Don't Log |
|--------|-----------|
| State transitions | Every loop iteration |
| Configuration loading | Routine polling |
| External connections | Successful health checks |
| User-triggered actions | High-frequency data |
| Errors with context | Duplicate messages |

### Log Message Guidelines

```python
# Good - includes context
logger.info("Recording started: session=%s, trial=%d", session_id, trial_num)

# Bad - no context
logger.info("Started")

# Good - actionable error
logger.error("Failed to open device %s: %s", device_path, str(e))

# Bad - vague error
logger.error("Device error")
```

### Performance Considerations

- Avoid logging in hot loops (frame capture, audio buffers)
- Use DEBUG level for detailed diagnostics, not INFO
- Check `logger.isEnabledFor(logging.DEBUG)` before expensive string formatting
- File handler is async-safe but still has I/O cost

---

## Configuration Reference

### logging_config.py

```python
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"
```

### ModuleLogManager Options

| Parameter | Default | Description |
|-----------|---------|-------------|
| `log_file` | Module-specific | Path for rotating log file |
| `console_level` | INFO | Initial console output level |
| `max_bytes` | 300 KB | Max file size before rotation |
| `backup_count` | 3 | Number of backup files |
| `enable_forwarding` | False | Forward logs to master UI |

---

## See Also

- [README.md](../README.md) - Main project documentation
- [Debug API Routes](../rpi_logger/core/api/routes/debug.py) - API endpoint details
- [Module Log Manager](../rpi_logger/core/module_log_manager.py) - Subprocess logging implementation
