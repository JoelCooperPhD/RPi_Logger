# Notes Module Integration Plan

## Overview

Integrate the Notes module into the Logger's device-based workflow so it appears in the Devices panel alongside hardware modules (VOG, DRT, EyeTracker). Users will "Connect" to Notes the same way they connect to hardware devices, providing a consistent UX.

Additionally, update the Notes module UI to match the modern dark theme styling used by VOG, DRT, and the main application.

---

## Part 1: Device Panel Integration

### 1.1 Add "Internal" Device Family

**File:** `rpi_logger/core/devices/device_registry.py`

Add a new device family and device type for internal/virtual modules:

```python
class DeviceFamily(Enum):
    VOG = "VOG"
    DRT = "DRT"
    EYE_TRACKER = "EyeTracker"
    INTERNAL = "Internal"  # NEW: Software-only modules

class DeviceType(Enum):
    # ... existing types ...
    NOTES = "Notes"  # NEW: Virtual device for Notes module
```

Add to `DEVICE_REGISTRY`:

```python
DeviceType.NOTES: DeviceSpec(
    device_type=DeviceType.NOTES,
    family=DeviceFamily.INTERNAL,
    vid=None,
    pid=None,
    baudrate=0,
    display_name="Notes",
    module_id="Notes",
    is_virtual=True,  # NEW field
),
```

Update `DeviceSpec` dataclass to include:
```python
is_virtual: bool = False  # True for software-only "devices"
```

### 1.2 Create Internal Device Scanner

**New File:** `rpi_logger/core/devices/internal_scanner.py`

A simple scanner that immediately "discovers" all virtual devices defined in the registry:

```python
class InternalDeviceScanner:
    """Scanner for internal/virtual devices that are always available."""

    def __init__(self, on_device_found, on_device_lost):
        self._on_device_found = on_device_found
        self._on_device_lost = on_device_lost
        self._active_devices: Dict[str, DeviceInfo] = {}

    async def start(self) -> None:
        """Discover all virtual devices immediately."""
        for device_type, spec in DEVICE_REGISTRY.items():
            if getattr(spec, 'is_virtual', False):
                device_info = DeviceInfo(
                    device_id=f"internal_{spec.module_id.lower()}",
                    device_type=device_type,
                    display_name=spec.display_name,
                    port=None,  # No physical port
                    state=ConnectionState.DISCONNECTED,
                )
                self._active_devices[device_info.device_id] = device_info
                await self._on_device_found(device_info)

    async def stop(self) -> None:
        """Remove all virtual devices."""
        for device_id, device_info in self._active_devices.items():
            await self._on_device_lost(device_info)
        self._active_devices.clear()
```

### 1.3 Integrate Internal Scanner into DeviceConnectionManager

**File:** `rpi_logger/core/devices/device_connection_manager.py`

- Import and instantiate `InternalDeviceScanner`
- Start it alongside USB/XBee/Network scanners
- Handle internal devices in the device found/lost callbacks
- Route connect requests for internal devices to module manager

### 1.4 Add "INTERNAL" Section to Devices Panel

**File:** `rpi_logger/core/ui/devices_panel.py`

Add a new section for internal devices:

```python
class USBDevicesPanel(ttk.LabelFrame):
    def __init__(self, ...):
        # ... existing sections ...

        # NEW: Internal devices section
        self.internal_section = DeviceSection(
            self.scrollable_frame,
            "INTERNAL",
            self._on_connect_change,
            self._on_visibility_change,
        )
        self.internal_section.grid(row=3, column=0, sticky="ew")
```

Update `update_devices()` to accept and display internal devices:

```python
def update_devices(
    self,
    devices: List[DeviceInfo],
    dongles: List[XBeeDongleInfo],
    network_devices: Optional[List[DeviceInfo]] = None,
    internal_devices: Optional[List[DeviceInfo]] = None,  # NEW
) -> None:
```

### 1.5 Wire Up Connect/Disconnect for Internal Devices

**File:** `rpi_logger/core/main_controller.py` (or wherever device connections are handled)

When user clicks "Connect" on an internal device:
1. Look up the module_id from the device spec
2. Call `ModuleStateManager.set_desired_state(module_id, True)`
3. ModuleManager starts the module process
4. Update device state to CONNECTED

When user clicks "Disconnect":
1. Call `ModuleStateManager.set_desired_state(module_id, False)`
2. ModuleManager stops the module process
3. Update device state to DISCONNECTED

---

## Part 2: Notes Module Styling

### 2.1 Import Theme System

**File:** `rpi_logger/modules/Notes/notes_runtime.py`

Add theme imports at the top:

```python
try:
    from rpi_logger.core.ui.theme.styles import Theme
    from rpi_logger.core.ui.theme.colors import Colors
    HAS_THEME = True
except ImportError:
    HAS_THEME = False
    Theme = None
    Colors = None
```

### 2.2 Apply Theme to Notes Window

In `_build_ui()` method, apply theme to the root window:

```python
def _build_ui(self) -> None:
    if not self.view or tk is None:
        return

    # Apply theme to window if available
    if HAS_THEME and Theme is not None:
        root = getattr(self.view, 'root', None)
        if root:
            Theme.configure_toplevel(root)
```

### 2.3 Update History Widget Styling

Replace hard-coded tag colors with theme colors:

**Current (broken on dark theme):**
```python
self._history_widget.tag_config("timestamp", foreground="#1a237e")  # Too dark
self._history_widget.tag_config("elapsed", foreground="#1b5e20")    # Too dark
self._history_widget.tag_config("modules", foreground="#4a148c")    # Too dark
```

**Updated:**
```python
# Use theme colors that work on dark background
if HAS_THEME and Colors is not None:
    timestamp_color = Colors.PRIMARY          # Blue (#3498db)
    elapsed_color = Colors.SUCCESS            # Green (#2ecc71)
    modules_color = Colors.WARNING            # Orange (#f39c12)
    text_fg = Colors.FG_PRIMARY               # Light gray (#ecf0f1)
    text_bg = Colors.BG_INPUT                 # Dark input bg (#3d3d3d)
else:
    # Fallback for light theme
    timestamp_color = "#1565c0"
    elapsed_color = "#2e7d32"
    modules_color = "#7b1fa2"
    text_fg = None
    text_bg = None

self._history_widget.tag_config("timestamp", foreground=timestamp_color)
self._history_widget.tag_config("elapsed", foreground=elapsed_color)
self._history_widget.tag_config("modules", foreground=modules_color)

# Configure text widget colors
if text_fg and text_bg:
    self._history_widget.configure(
        bg=text_bg,
        fg=text_fg,
        insertbackground=text_fg,
    )
```

### 2.4 Style the ScrolledText Widget

Apply theme configuration to the history widget:

```python
if HAS_THEME and Theme is not None:
    Theme.configure_scrolled_text(self._history_widget)
```

### 2.5 Style Entry and Button

Replace plain ttk widgets with styled versions:

**Entry:**
```python
self._note_entry = ttk.Entry(parent, style='TEntry')
# Entry styling is handled by Theme.apply()
```

**Button - Option A (RoundedButton):**
```python
try:
    from rpi_logger.core.ui.theme.widgets import RoundedButton
    self._post_button = RoundedButton(
        parent,
        text="Post",
        command=lambda: self._run_async(self._post_note_from_entry()),
        width=80,
        height=28,
        corner_radius=6,
        style='primary',  # Blue button for primary action
        bg=Colors.BG_FRAME if Colors else "#363636"
    )
except ImportError:
    # Fallback to ttk.Button
    self._post_button = ttk.Button(parent, text="Post", ...)
```

**Button - Option B (Keep ttk.Button with style):**
```python
self._post_button = ttk.Button(
    parent,
    text="Post",
    style='Primary.TButton',  # Defined in Theme
    command=lambda: self._run_async(self._post_note_from_entry()),
)
```

### 2.6 Style the Parent Frame

Ensure the containing frame uses proper styling:

```python
def builder(parent: tk.Widget) -> None:
    # Configure frame background
    if isinstance(parent, ttk.LabelFrame):
        parent.configure(text="Notes", padding="10")

    # Use Inframe style for nested frames
    if HAS_THEME:
        parent.configure(style='Inframe.TFrame')
```

### 2.7 Add Frame Border (Match VOG/DRT Style)

VOG and DRT use visible borders on their control panels:

```python
# In VOG view.py:
controls_panel = ttk.Frame(parent)
controls_panel.configure(
    borderwidth=1,
    relief="solid",
)
# Plus highlight attributes for border color
```

Apply similar styling to Notes:

```python
# Create a bordered container frame
container = tk.Frame(
    parent,
    bg=Colors.BG_FRAME if Colors else "#363636",
    highlightbackground=Colors.BORDER if Colors else "#404055",
    highlightcolor=Colors.BORDER if Colors else "#404055",
    highlightthickness=1,
)
```

---

## Part 3: Configuration Updates

### 3.1 Update Notes config.txt

**File:** `rpi_logger/modules/Notes/config.txt`

Add field to indicate this is an internal module:

```ini
display_name = Notes
enabled = true
internal = true    # NEW: Marks as internal/virtual device
visible = true     # Show in devices panel
# ... rest of config ...
```

### 3.2 Update ModuleInfo to Track Internal Status

**File:** `rpi_logger/core/module_discovery.py`

Add field to ModuleInfo:

```python
@dataclass
class ModuleInfo:
    name: str
    directory: Path
    entry_point: Path
    config_path: Optional[Path]
    display_name: str
    module_id: str = ""
    config_template_path: Optional[Path] = None
    is_internal: bool = False  # NEW: True for Notes, Audio, etc.
```

Parse from config in `discover_modules()`:

```python
is_internal = parse_bool(config.get('internal'), default=False)

info = ModuleInfo(
    # ... existing fields ...
    is_internal=is_internal,
)
```

---

## Part 4: Implementation Order

### Phase 1: Device Registry & Scanner
1. Add `INTERNAL` family and `NOTES` device type to registry
2. Add `is_virtual` field to `DeviceSpec`
3. Create `InternalDeviceScanner` class
4. Integrate scanner into `DeviceConnectionManager`

### Phase 2: Devices Panel UI
5. Add `INTERNAL` section to `USBDevicesPanel`
6. Update `update_devices()` signature and logic
7. Wire up connect/disconnect callbacks for internal devices

### Phase 3: Notes Styling
8. Import theme system in `notes_runtime.py`
9. Update tag colors to theme colors
10. Style ScrolledText with theme
11. Style Entry widget
12. Replace/style Post button
13. Add frame border styling

### Phase 4: Config & Discovery
14. Update Notes `config.txt` with `internal = true`
15. Add `is_internal` to `ModuleInfo` dataclass
16. Parse `internal` field in `discover_modules()`

### Phase 5: Testing & Polish
17. Test Notes appears in INTERNAL section
18. Test Connect/Disconnect flow
19. Test Show/Hide window visibility
20. Verify styling matches VOG/DRT
21. Test graceful fallback when theme unavailable

---

## Visual Reference

### Current Notes UI (Unstyled)
- White/light background
- Dark blue timestamp text (invisible on dark theme)
- Plain ttk Entry and Button
- No visual hierarchy

### Target Notes UI (Styled)
- Dark background (`#363636`)
- Blue timestamps (`#3498db`)
- Green elapsed time (`#2ecc71`)
- Orange module tags (`#f39c12`)
- Light text (`#ecf0f1`)
- Styled entry with dark background
- RoundedButton or styled ttk.Button for "Post"
- 1px border matching VOG/DRT panels

### Devices Panel with Internal Section
```
┌─────────────────────────────────────┐
│  Devices                            │
├─────────────────────────────────────┤
│  INTERNAL                           │
│    ○ Notes          [Connect] [Show]│
│                                     │
│  USB                                │
│    ● VOG (sVOG)  [Disconnect] [Hide]│
│                                     │
│  WIRELESS                           │
│    (No devices)                     │
│                                     │
│  NETWORK                            │
│    (No devices)                     │
└─────────────────────────────────────┘
```

---

## Files Modified

| File | Changes |
|------|---------|
| `rpi_logger/core/devices/device_registry.py` | Add INTERNAL family, NOTES type, is_virtual field |
| `rpi_logger/core/devices/internal_scanner.py` | NEW FILE - Virtual device scanner |
| `rpi_logger/core/devices/device_connection_manager.py` | Integrate internal scanner |
| `rpi_logger/core/ui/devices_panel.py` | Add INTERNAL section |
| `rpi_logger/core/main_controller.py` | Handle internal device connect/disconnect |
| `rpi_logger/core/module_discovery.py` | Add is_internal field to ModuleInfo |
| `rpi_logger/modules/Notes/notes_runtime.py` | Apply theme styling |
| `rpi_logger/modules/Notes/config.txt` | Add internal=true |

---

## Notes

- The "Connect" terminology is maintained for consistency - users don't need to know Notes is internal
- Internal devices are always "discovered" (available) - no hardware scanning needed
- The same Show/Hide window visibility pattern applies to Notes as to VOG/DRT
- Theme imports use try/except for graceful degradation if theme unavailable
- Colors chosen to provide good contrast on dark backgrounds while maintaining semantic meaning (blue=info, green=timing, orange=context)
