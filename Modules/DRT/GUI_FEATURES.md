# DRT Module GUI Features

## Overview
The DRT GUI replicates the original sDRT user interface with enhanced features for multi-device support and modern async architecture.

## Main Window Layout

### 1. Device Selection Dropdown
- Located at top of window
- Shows all connected sDRT devices
- Format: `"/dev/ttyACM0 - sDRT"`
- Auto-selects first device on connection
- Switch between multiple devices seamlessly

### 2. Real-Time Scrolling Plot (matplotlib)

#### Figure Configuration
- **Size**: 4x2 inches at 100 DPI
- **Title**: "DRT - Detection Response Task"
- **Time Range**: 60-second sliding window (-60 to 0 seconds)
- **Update Rate**: 10 FPS (100ms intervals)

#### Upper Subplot: Stimulus State
- **Y-Axis**: Binary (Off=0, On=1)
- **Y-Label**: "Stimulus" (right-aligned)
- **Y-Ticks**: ["Off", "On"]
- **Display**: Line plot showing stimulus on/off over time
- **Purpose**: Visual timeline of when stimulus was active

#### Lower Subplot: Reaction Times
- **Y-Axis**: Time in seconds (auto-scaling)
- **Y-Label**: "RT-Seconds" (right-aligned)
- **X-Label**: "Time (seconds)"
- **Display**: Dual-marker scatter plot
  - **Hits**: Circle markers (o) for successful responses
  - **Misses**: X markers for missed responses
- **Auto-scaling**: Y-axis expands to fit data range
- **Purpose**: Track reaction time performance over time

#### Multi-Device Support
- Each device gets unique colored lines
- Legend shows device identification
- All devices plotted simultaneously
- Independent data streams

### 3. Stimulus Controls
```
┌─────────────────┐
│   Stimulus      │
├────────┬────────┤
│   ON   │  OFF   │
└────────┴────────┘
```
- **ON Button**: Sends `stim_on` command to selected device
- **OFF Button**: Sends `stim_off` command to selected device
- Updates plot immediately to show state change
- Only affects currently selected device

### 4. Results Display
```
┌──────────────────────────┐
│        Results           │
├──────────────────────────┤
│ Trial Number:        12  │
│ Reaction Time:      342  │
│ Response Count:       3  │
└──────────────────────────┘
```
- **Trial Number**: Current trial count (default: "0")
- **Reaction Time**: Latest RT in milliseconds (default: "-1")
- **Response Count**: Number of clicks/responses (default: "0")
- Updates in real-time as device sends data
- Shows data for currently selected device only

### 5. Configure Button
- **Text**: "Configure Unit"
- **Width**: 25 characters
- **Action**: Opens configuration dialog
- Two modes:
  1. Single device: Opens config directly
  2. Multiple devices: Shows device selector first

## Configuration Window

### Device Selector (Multiple Devices)
- Modal dialog listing all connected devices
- Button for each device showing port and name
- Clicking device opens configuration for that device

### Configuration Dialog
- Modal window with device-specific settings
- Shows current device port in title
- Four configurable parameters:

#### Parameters
1. **Lower ISI** (Inter-Stimulus Interval)
   - Unit: milliseconds
   - Default: 3000ms
   - Purpose: Minimum time between stimuli

2. **Upper ISI** (Inter-Stimulus Interval)
   - Unit: milliseconds
   - Default: 5000ms
   - Purpose: Maximum time between stimuli

3. **Stimulus Duration**
   - Unit: milliseconds
   - Default: 1000ms
   - Purpose: How long stimulus is displayed

4. **Intensity**
   - Range: 0-255
   - Default: 255
   - Purpose: Stimulus brightness/intensity

#### Actions
- **Apply Button**: Sends individual parameter changes to device
- **Set ISO Standard**: Applies all four defaults with one click
- **Cancel/Close**: Closes without changes

### Commands Sent
Configuration sends these serial commands:
```
set_lowerISI 3000\n\r
set_upperISI 5000\n\r
set_stimDur 1000\n\r
set_intensity 255\n\r
```
(50ms delay between commands)

## Data Flow

### Device → GUI
1. Device sends data via serial: `type>value>value2`
2. Handler parses response and extracts data
3. Handler calls mode callback: `on_device_data(port, type, data)`
4. GUI mode forwards to GUI: `gui.on_device_data(port, type, data)`
5. GUI updates:
   - Results display (if current device)
   - Plot data arrays (all devices)
   - Visual refresh (100ms throttled)

### GUI → Device
1. User clicks button (Stimulus ON/OFF, Configure)
2. GUI looks up device handler for selected device
3. Async command sent: `handler.set_stimulus(True)`
4. Handler formats and transmits: `stim_on\n\r`
5. Device receives and responds (optional)

## Plot Update Mechanism

### Data Storage
- **Time array**: 600 elements (-60 to 0 seconds, 0.1s resolution)
- **RT arrays**: 600 elements per device (hit/miss separate)
- **State arrays**: 600 elements per device
- All arrays initialized with `np.nan`

### Rolling Buffer
New data shifts array left (oldest data dropped):
```python
array = np.roll(array, -1)  # Shift left
array[-1] = new_value        # Add new value at end
```

### Rendering
- matplotlib `FuncAnimation` not used
- Manual update in GUI update loop
- 100ms minimum between redraws
- `canvas.draw_idle()` for efficient rendering

## Recording Integration

### File Menu
- **Start Recording**: Begins trial logging
- **Stop Recording**: Ends trial logging
- Window title updates: "DRT Monitor (Recording)"

### Data Logging
- Automatic per-device CSV creation
- Format: `sDRT_<port>_<timestamp>.csv`
- Headers: `Timestamp,Port,TrialNumber,ReactionTime_ms`
- Async file I/O to prevent blocking

## Multi-Device Workflow

### Typical Use Case
1. Connect multiple sDRT devices
2. Each appears in dropdown automatically
3. Select device to control
4. View all devices in plot simultaneously
5. Control selected device (stimulus, config)
6. Results show selected device only
7. All devices log independently

### Visual Feedback
- Dropdown shows which device is selected
- Plot legend identifies each device by port
- Results update only for selected device
- Stimulus state visible in plot for all devices

## Technical Details

### Async Integration
- All button callbacks use `asyncio.create_task()`
- Command transmission never blocks GUI
- Plot updates on main thread (tkinter requirement)
- File I/O wrapped in `asyncio.to_thread()`

### Thread Safety
- GUI updates always on main thread
- Device data callbacks queued for GUI thread
- matplotlib canvas updates synchronized

### Performance
- Plot: 10 FPS (100ms intervals)
- Data arrays: 600 points × devices
- Memory: ~5KB per device for plot data
- CPU: Minimal when not recording/plotting

## Comparison to Original

### Preserved from Original
✅ Two-subplot design
✅ 60-second time window
✅ Stimulus On/Off buttons
✅ Results display layout
✅ Configure button
✅ ISO preset values
✅ Hit/Miss markers

### Enhanced Features
🆕 Multi-device support in single window
🆕 Device selection dropdown
🆕 Auto-device detection and connection
🆕 Hot-plug/unplug handling
🆕 Configuration dialog with device selector
🆕 Async architecture throughout
🆕 Integration with main logger system
🆕 Session-based data logging

### Architectural Improvements
- Modern asyncio instead of threading
- Proper separation: handler/system/GUI
- Reusable USB serial framework
- Type hints and logging throughout
- Clean MVC-style architecture
