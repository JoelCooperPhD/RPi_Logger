# Automation API Plan: Complete Programmatic Control

## Executive Summary

This document defines the comprehensive plan for ensuring **every module, every function, and every setting** in the Logger system is controllable via the REST API. The goal is to enable complete automated testing of all capabilities with verification through the existing logging system.

---

## Current State Analysis

### Existing API Infrastructure

The Logger system already has a foundational REST API implemented:

**Location:** `/home/joel/Development/Logger/rpi_logger/core/api/`

**Architecture:**
- `server.py` - aiohttp-based REST server (runs on port 8080)
- `controller.py` - APIController wrapping LoggerSystem
- `middleware.py` - Localhost-only security, error handling
- `routes/` - Route modules for different endpoint categories

**Current Route Coverage:**
| Route File | Status | Endpoints |
|------------|--------|-----------|
| `system.py` | IMPLEMENTED | health, status, platform, system_info, shutdown |
| `modules.py` | IMPLEMENTED | list, enable/disable, start/stop, commands, instances |
| `session.py` | IMPLEMENTED | session start/stop, trial start/stop, directory management |
| `devices.py` | NOT IMPLEMENTED | Referenced but file missing |
| `config.py` | NOT IMPLEMENTED | Referenced but file missing |
| `logs.py` | NOT IMPLEMENTED | Referenced but file missing |

---

## Modules Inventory

### Core Modules

| Module | Display Name | Type | Multi-Instance | Hardware Required |
|--------|--------------|------|----------------|-------------------|
| Audio | Audio | Internal | No | USB Microphone |
| Cameras | Cameras | External | Yes | USB Webcam |
| CSICameras | CSI Cameras | External | Yes | RPi CSI Camera |
| DRT | DRT | External | Yes | DRT Serial Device |
| VOG | VOG | External | Yes | VOG Serial Device |
| GPS | GPS | External | No | USB GPS Receiver |
| EyeTracker | EyeTracker-Neon | External | No | Pupil Labs Neon |
| Notes | Notes | Internal | No | None |

### Module Configuration Settings

#### Audio Module (`AudioSettings`)
| Setting | Type | Default | API Access |
|---------|------|---------|------------|
| mode | str | "gui" | NEEDED |
| output_dir | Path | "audio" | NEEDED |
| session_prefix | str | "audio" | NEEDED |
| log_level | str | "debug" | NEEDED |
| sample_rate | int | 48000 | NEEDED |
| console_output | bool | False | NEEDED |
| meter_refresh_interval | float | 0.08 | NEEDED |
| recorder_start_timeout | float | 3.0 | NEEDED |
| recorder_stop_timeout | float | 2.0 | NEEDED |
| shutdown_timeout | float | 15.0 | NEEDED |

#### Cameras Module (`CamerasConfig`)
| Setting Category | Settings | API Access |
|------------------|----------|------------|
| Preview | resolution, fps_cap, pixel_format, overlay, auto_start | NEEDED |
| Record | resolution, fps_cap, pixel_format, overlay | NEEDED |
| Guard | disk_free_gb_min, check_interval_ms | NEEDED |
| Retention | max_sessions, prune_on_start | NEEDED |
| Storage | base_path, per_camera_subdir | NEEDED |
| Telemetry | emit_interval_ms, include_metrics | NEEDED |
| UI | auto_start_preview | NEEDED |
| Backend | picam_controls (dict) | NEEDED |
| Logging | level, file | NEEDED |

#### GPS Module (`GPSConfig`)
| Setting | Type | Default | API Access |
|---------|------|---------|------------|
| output_dir | Path | "gps_data" | NEEDED |
| session_prefix | str | "gps" | NEEDED |
| log_level | str | "info" | NEEDED |
| offline_db | str | "offline_tiles.db" | NEEDED |
| center_lat | float | 40.7608 | NEEDED |
| center_lon | float | -111.8910 | NEEDED |
| zoom | float | 13.0 | NEEDED |
| serial_port | str | "/dev/serial0" | NEEDED |
| baud_rate | int | 9600 | NEEDED |
| reconnect_delay_s | float | 3.0 | NEEDED |
| nmea_history | int | 30 | NEEDED |
| view_show_io_panel | bool | False | NEEDED |
| view_show_logger | bool | True | NEEDED |

#### DRT Module (`DRTConfig`)
| Setting | Type | Default | API Access |
|---------|------|---------|------------|
| output_dir | Path | "drt_data" | NEEDED |
| session_prefix | str | "drt" | NEEDED |
| log_level | str | "info" | NEEDED |
| device_vid | int | 0x239A | NEEDED |
| device_pid | int | 0x801E | NEEDED |
| baudrate | int | 9600 | NEEDED |
| window_geometry | str | "" | NEEDED |
| auto_start_recording | bool | False | NEEDED |
| gui_show_session_output | bool | True | NEEDED |

#### VOG Module (`VOGConfig`)
| Setting | Type | Default | API Access |
|---------|------|---------|------------|
| output_dir | Path | "vog_data" | NEEDED |
| session_prefix | str | "vog" | NEEDED |
| log_level | str | "info" | NEEDED |
| view_show_io_panel | bool | True | NEEDED |
| view_show_logger | bool | False | NEEDED |
| window_geometry | str | "320x200" | NEEDED |
| config_dialog_geometry | str | "" | NEEDED |

#### EyeTracker Module (`EyeTrackerConfig`)
| Setting | Type | Default | API Access |
|---------|------|---------|------------|
| output_dir | Path | "neon-eyetracker" | NEEDED |
| session_prefix | str | "neon_eyetracker" | NEEDED |
| target_fps | float | 10.0 | NEEDED |
| eyes_fps | float | 30.0 | NEEDED |
| resolution_width | int | 1280 | NEEDED |
| resolution_height | int | 720 | NEEDED |
| auto_start_recording | bool | False | NEEDED |
| preview_preset | int | 4 | NEEDED |
| preview_width | int | 640 | NEEDED |
| preview_height | int | 480 | NEEDED |
| discovery_timeout | float | 5.0 | NEEDED |
| discovery_retry | float | 3.0 | NEEDED |
| enable_recording_overlay | bool | True | NEEDED |
| include_gaze_in_recording | bool | True | NEEDED |
| overlay_font_scale | float | 0.6 | NEEDED |
| gaze_circle_radius | int | 60 | NEEDED |
| gaze_shape | str | "circle" | NEEDED |
| stream_video_enabled | bool | True | NEEDED |
| stream_gaze_enabled | bool | True | NEEDED |
| stream_eyes_enabled | bool | True | NEEDED |
| stream_imu_enabled | bool | True | NEEDED |
| stream_events_enabled | bool | True | NEEDED |
| stream_audio_enabled | bool | True | NEEDED |

#### Notes Module (`NotesConfig`)
| Setting | Type | Default | API Access |
|---------|------|---------|------------|
| output_dir | Path | "notes" | NEEDED |
| session_prefix | str | "notes" | NEEDED |
| auto_start | bool | True | NEEDED |
| history_limit | int | 100 | NEEDED |
| log_level | str | "info" | NEEDED |

---

## API Endpoints Implementation Plan

### Phase 1: Complete Missing Route Files (HIGH PRIORITY)

#### 1.1 Device Routes (`routes/devices.py`)

```
GET  /api/v1/devices                    - List all discovered devices
GET  /api/v1/devices/{id}               - Get specific device details
POST /api/v1/devices/{id}/connect       - Connect to a device
POST /api/v1/devices/{id}/disconnect    - Disconnect from a device
GET  /api/v1/devices/connected          - List connected devices
GET  /api/v1/devices/scanning           - Get scanning status
POST /api/v1/devices/scanning/start     - Start device scanning
POST /api/v1/devices/scanning/stop      - Stop device scanning
GET  /api/v1/connections                - List enabled connection types
PUT  /api/v1/connections/{interface}/{family} - Enable/disable connection type
GET  /api/v1/xbee/status                - Get XBee dongle status
POST /api/v1/xbee/rescan                - Trigger XBee network rescan
```

**Controller methods already exist:**
- `list_devices()`, `get_device()`, `connect_device()`, `disconnect_device()`
- `get_connected_devices()`, `start_scanning()`, `stop_scanning()`
- `get_scanning_status()`, `get_enabled_connections()`, `set_connection_enabled()`
- `get_xbee_status()`, `xbee_rescan()`

#### 1.2 Configuration Routes (`routes/config.py`)

```
GET  /api/v1/config                     - Get global configuration
PUT  /api/v1/config                     - Update global configuration
GET  /api/v1/config/path                - Get config file path
GET  /api/v1/modules/{name}/config      - Get module-specific config
PUT  /api/v1/modules/{name}/config      - Update module-specific config
GET  /api/v1/modules/{name}/preferences - Get module preferences snapshot
PUT  /api/v1/modules/{name}/preferences/{key} - Update specific preference
```

**Controller methods already exist:**
- `get_config()`, `update_config()`, `get_config_path()`

**New methods needed:**
- `get_module_config(name)` - Read module-specific config
- `update_module_config(name, updates)` - Update module-specific config
- `get_module_preferences(name)` - Get preferences snapshot
- `update_module_preference(name, key, value)` - Update single preference

#### 1.3 Log Routes (`routes/logs.py`)

```
GET  /api/v1/logs/paths                 - Get all log file paths
GET  /api/v1/logs/master                - Get master log content (paginated)
GET  /api/v1/logs/session               - Get session log content (paginated)
GET  /api/v1/logs/events                - Get event log content (paginated)
GET  /api/v1/logs/modules/{name}        - Get module-specific log
GET  /api/v1/logs/tail/{path}           - Tail a specific log file
WS   /api/v1/logs/stream                - WebSocket for real-time log streaming
```

**Controller methods already exist:**
- `get_log_paths()`

**New methods needed:**
- `read_log_file(path, offset, limit)` - Read log file with pagination
- `tail_log_file(path, lines)` - Get last N lines from log
- `stream_log_file(path)` - Generator for real-time streaming

---

### Phase 2: Module-Specific Commands (MEDIUM PRIORITY)

Each module needs specific commands exposed via the `/api/v1/modules/{name}/command` endpoint.

#### 2.1 Audio Module Commands

| Command | Parameters | Description |
|---------|------------|-------------|
| `start_recording` | trial_number, label | Start audio recording |
| `stop_recording` | - | Stop audio recording |
| `set_device` | device_index | Select audio input device |
| `get_devices` | - | List available audio devices |
| `get_levels` | - | Get current audio levels |
| `set_sample_rate` | rate | Change sample rate |

#### 2.2 Cameras Module Commands

| Command | Parameters | Description |
|---------|------------|-------------|
| `start_preview` | camera_id | Start camera preview |
| `stop_preview` | camera_id | Stop camera preview |
| `start_recording` | camera_id, trial_number, label | Start video recording |
| `stop_recording` | camera_id | Stop video recording |
| `set_resolution` | camera_id, width, height | Set capture resolution |
| `set_fps` | camera_id, fps | Set capture framerate |
| `get_capabilities` | camera_id | Get camera capabilities |
| `apply_settings` | camera_id, settings | Apply camera settings batch |

#### 2.3 GPS Module Commands

| Command | Parameters | Description |
|---------|------------|-------------|
| `start_recording` | trial_number, label | Start GPS logging |
| `stop_recording` | - | Stop GPS logging |
| `get_position` | - | Get current GPS position |
| `get_fix_status` | - | Get GPS fix status |
| `set_map_center` | lat, lon | Set map center position |
| `set_map_zoom` | zoom | Set map zoom level |

#### 2.4 DRT Module Commands

| Command | Parameters | Description |
|---------|------------|-------------|
| `start_recording` | trial_number, label | Start DRT recording |
| `stop_recording` | - | Stop DRT recording |
| `get_response_stats` | - | Get response statistics |
| `reset_trial` | - | Reset trial counter |

#### 2.5 VOG Module Commands

| Command | Parameters | Description |
|---------|------------|-------------|
| `start_recording` | trial_number, label | Start VOG recording |
| `stop_recording` | - | Stop VOG recording |
| `get_shutter_state` | - | Get current shutter state |
| `toggle_shutter` | - | Toggle shutter open/closed |

#### 2.6 EyeTracker Module Commands

| Command | Parameters | Description |
|---------|------------|-------------|
| `start_recording` | trial_number, label | Start eye tracking |
| `stop_recording` | - | Stop eye tracking |
| `start_preview` | - | Start preview stream |
| `stop_preview` | - | Stop preview stream |
| `get_gaze_data` | - | Get current gaze position |
| `get_calibration_status` | - | Get calibration status |
| `start_calibration` | - | Start calibration process |
| `set_stream_enabled` | stream_type, enabled | Enable/disable specific stream |

#### 2.7 Notes Module Commands

| Command | Parameters | Description |
|---------|------------|-------------|
| `add_note` | note_text, timestamp | Add a timestamped note |
| `start_recording` | trial_number | Start notes session |
| `stop_recording` | - | Stop notes session |
| `get_notes` | trial_number, limit | Get recent notes |
| `clear_history` | - | Clear notes display history |

---

### Phase 3: Settings Management API (MEDIUM PRIORITY)

#### 3.1 Per-Module Settings Endpoints

```
GET  /api/v1/modules/{name}/settings          - Get all module settings
PUT  /api/v1/modules/{name}/settings          - Update module settings (batch)
GET  /api/v1/modules/{name}/settings/{key}    - Get specific setting
PUT  /api/v1/modules/{name}/settings/{key}    - Update specific setting
POST /api/v1/modules/{name}/settings/reset    - Reset to defaults
GET  /api/v1/modules/{name}/settings/schema   - Get settings schema (types, ranges)
```

#### 3.2 Global Settings Endpoints

```
GET  /api/v1/settings                         - Get all global settings
PUT  /api/v1/settings                         - Update global settings
GET  /api/v1/settings/connection-types        - Get enabled connection types
PUT  /api/v1/settings/connection-types        - Update connection types
GET  /api/v1/settings/window-geometries       - Get saved window positions
```

---

### Phase 4: Window and UI Control (LOW PRIORITY)

```
POST /api/v1/modules/{name}/window/show       - Show module window (EXISTS)
POST /api/v1/modules/{name}/window/hide       - Hide module window (EXISTS)
GET  /api/v1/modules/{name}/window/geometry   - Get window geometry
PUT  /api/v1/modules/{name}/window/geometry   - Set window geometry
POST /api/v1/modules/{name}/window/focus      - Bring window to front
GET  /api/v1/windows                          - List all module windows
POST /api/v1/windows/arrange                  - Auto-arrange windows
```

---

### Phase 5: Testing and Verification Endpoints (LOW PRIORITY)

```
POST /api/v1/test/record-cycle               - Run complete record cycle test
POST /api/v1/test/module/{name}              - Run module-specific tests
GET  /api/v1/test/hardware-matrix            - Get hardware availability matrix
POST /api/v1/test/validate-session/{path}    - Validate recorded session data
GET  /api/v1/test/schemas                    - Get all data validation schemas
POST /api/v1/test/schema/{module}            - Validate data against schema
```

---

## Implementation Tasks

### Task Breakdown

#### Phase 1 Tasks (Immediate - Complete Missing Routes)

| ID | Task | Priority | Effort | Dependencies |
|----|------|----------|--------|--------------|
| P1-1 | Create `routes/devices.py` | HIGH | 2h | None |
| P1-2 | Create `routes/config.py` | HIGH | 2h | None |
| P1-3 | Create `routes/logs.py` | HIGH | 3h | None |
| P1-4 | Fix `routes/__init__.py` imports | HIGH | 15m | P1-1, P1-2, P1-3 |
| P1-5 | Add module config controller methods | HIGH | 2h | None |
| P1-6 | Add log reading controller methods | HIGH | 2h | None |
| P1-7 | Integration tests for new routes | HIGH | 3h | P1-1 through P1-6 |

#### Phase 2 Tasks (Module Commands)

| ID | Task | Priority | Effort | Dependencies |
|----|------|----------|--------|--------------|
| P2-1 | Document all module commands | MEDIUM | 2h | None |
| P2-2 | Add Audio module commands | MEDIUM | 2h | P2-1 |
| P2-3 | Add Cameras module commands | MEDIUM | 3h | P2-1 |
| P2-4 | Add GPS module commands | MEDIUM | 2h | P2-1 |
| P2-5 | Add DRT module commands | MEDIUM | 2h | P2-1 |
| P2-6 | Add VOG module commands | MEDIUM | 2h | P2-1 |
| P2-7 | Add EyeTracker module commands | MEDIUM | 3h | P2-1 |
| P2-8 | Add Notes module commands | MEDIUM | 1h | P2-1 |
| P2-9 | Module command tests | MEDIUM | 4h | P2-2 through P2-8 |

#### Phase 3 Tasks (Settings API)

| ID | Task | Priority | Effort | Dependencies |
|----|------|----------|--------|--------------|
| P3-1 | Create settings schema definitions | MEDIUM | 3h | None |
| P3-2 | Add per-module settings routes | MEDIUM | 3h | P3-1 |
| P3-3 | Add global settings routes | MEDIUM | 2h | P3-1 |
| P3-4 | Settings validation middleware | MEDIUM | 2h | P3-1 |
| P3-5 | Settings API tests | MEDIUM | 3h | P3-2, P3-3, P3-4 |

#### Phase 4 Tasks (Window Control)

| ID | Task | Priority | Effort | Dependencies |
|----|------|----------|--------|--------------|
| P4-1 | Add window geometry endpoints | LOW | 2h | None |
| P4-2 | Add window arrangement endpoint | LOW | 2h | None |
| P4-3 | Window control tests | LOW | 2h | P4-1, P4-2 |

#### Phase 5 Tasks (Testing Endpoints)

| ID | Task | Priority | Effort | Dependencies |
|----|------|----------|--------|--------------|
| P5-1 | Create test orchestration endpoint | LOW | 4h | Phase 1-3 |
| P5-2 | Create hardware matrix endpoint | LOW | 2h | None |
| P5-3 | Create data validation endpoint | LOW | 3h | None |
| P5-4 | Integration with pytest | LOW | 4h | P5-1 |

---

## Coverage Matrix

### Current API Coverage

| Category | Total Functions | API Covered | Missing | Coverage |
|----------|-----------------|-------------|---------|----------|
| System | 5 | 5 | 0 | 100% |
| Modules | 15 | 12 | 3 | 80% |
| Sessions | 8 | 8 | 0 | 100% |
| Trials | 4 | 4 | 0 | 100% |
| Devices | 12 | 0 | 12 | 0% |
| Config | 6 | 0 | 6 | 0% |
| Logs | 5 | 0 | 5 | 0% |
| Settings | 20+ | 0 | 20+ | 0% |

### Target Coverage After Implementation

| Category | Target Coverage |
|----------|-----------------|
| System | 100% |
| Modules | 100% |
| Sessions | 100% |
| Trials | 100% |
| Devices | 100% |
| Config | 100% |
| Logs | 100% |
| Settings | 100% |
| **Overall** | **100%** |

---

## Testing Strategy

### Automated Test Categories

1. **Unit Tests** - Individual endpoint handlers
2. **Integration Tests** - Full API request/response cycles
3. **End-to-End Tests** - Complete workflows (session -> record -> stop)
4. **Hardware Tests** - Tests requiring physical devices (marked with fixtures)

### Test Fixtures

```python
@pytest.fixture
def api_client():
    """Create test client for API server."""

@pytest.fixture
def mock_logger_system():
    """Mock LoggerSystem for isolated testing."""

@pytest.fixture
def sample_session():
    """Create sample session with recorded data."""
```

### Log Verification

All API operations should be verified through the logging system:

1. **Event Logger** - Records all button presses and state changes
2. **Master Log** - Records system-wide events
3. **Module Logs** - Records module-specific operations
4. **Session Logs** - Records session-specific data

---

## Security Considerations

1. **Localhost Only** - API only accepts connections from 127.0.0.1 (existing middleware)
2. **No Authentication** - By design for local automation (consider token auth for network access)
3. **Rate Limiting** - Consider adding for production use
4. **Input Validation** - All endpoints should validate input parameters

---

## Usage Examples

### Start Recording Session

```bash
# 1. Check system health
curl http://localhost:8080/api/v1/health

# 2. Enable required modules
curl -X POST http://localhost:8080/api/v1/modules/Audio/enable
curl -X POST http://localhost:8080/api/v1/modules/GPS/enable

# 3. Start session
curl -X POST http://localhost:8080/api/v1/session/start \
  -H "Content-Type: application/json" \
  -d '{"directory": "/data/recordings/test_session"}'

# 4. Start trial recording
curl -X POST http://localhost:8080/api/v1/trial/start \
  -H "Content-Type: application/json" \
  -d '{"label": "baseline_01"}'

# 5. Wait for data collection...

# 6. Stop trial
curl -X POST http://localhost:8080/api/v1/trial/stop

# 7. Stop session
curl -X POST http://localhost:8080/api/v1/session/stop

# 8. Verify logs
curl http://localhost:8080/api/v1/logs/events
```

### Module Configuration

```bash
# Get module settings
curl http://localhost:8080/api/v1/modules/Cameras/settings

# Update specific setting
curl -X PUT http://localhost:8080/api/v1/modules/Cameras/settings/record.resolution \
  -H "Content-Type: application/json" \
  -d '{"value": "1920x1080"}'
```

---

## Success Criteria

1. **Complete Coverage** - Every module, function, and setting accessible via API
2. **Log Verification** - All operations logged and verifiable
3. **Test Suite** - Automated tests covering all endpoints
4. **Documentation** - OpenAPI/Swagger spec generated
5. **Reliability** - API handles edge cases gracefully

---

## Timeline Estimate

| Phase | Duration | Start | End |
|-------|----------|-------|-----|
| Phase 1 (Missing Routes) | 2 days | Day 1 | Day 2 |
| Phase 2 (Module Commands) | 3 days | Day 3 | Day 5 |
| Phase 3 (Settings API) | 2 days | Day 6 | Day 7 |
| Phase 4 (Window Control) | 1 day | Day 8 | Day 8 |
| Phase 5 (Testing) | 2 days | Day 9 | Day 10 |
| **Total** | **10 days** | | |

---

## References

- Existing API: `/home/joel/Development/Logger/rpi_logger/core/api/`
- Module Configs: `/home/joel/Development/Logger/rpi_logger/modules/*/config.py`
- Data Validation Plan: `/home/joel/Development/Logger/docs/DATA_VALIDATION_TEST_PLAN.md`
- Task Breakdown: `/home/joel/Development/Logger/docs/TASK_BREAKDOWN.md`
