# Device Window State Logic

## State Variables

For each device, we track:
1. **Connection State** (dot color): DISCONNECTED (dark) or CONNECTED (green)
2. **Window Visibility** (button text): Hidden (Show) or Visible (Hide)
3. **Module Running**: Whether the module process is running

## State Transitions

### User Clicks "Show" Button

| Current State | Action |
|---------------|--------|
| Disconnected, Window Hidden | Connect device → Start module → Window opens → Button says "Hide" |
| Connected, Module Not Running, Window Hidden | Start module → Window opens → Button says "Hide" |
| Connected, Module Running, Window Hidden | Send show_window command → Button says "Hide" |
| Connected, Module Running, Window Visible | No-op (already visible) |

### User Clicks "Hide" Button

| Current State | Action |
|---------------|--------|
| Window Visible | Send hide_window command → Button says "Show" |
| Window Hidden | No-op (already hidden) |

### User Clicks "Connect" Button (dot or Connect button)

| Current State | Action |
|---------------|--------|
| Disconnected | Connect device → Start module → Window opens → Dot green, Button says "Hide" |
| Connected | Disconnect device → Stop module → Window closes → Dot dark, Button says "Show" |

### User Clicks "X" on Module Window

| Current State | Action |
|---------------|--------|
| Window Visible | Module sends window_hidden status → Button says "Show" (module keeps running) |

### Module Crashes/Stops Unexpectedly

| Current State | Action |
|---------------|--------|
| Module Running | Detect crash → Dot stays green (device still connected), Button says "Show" |

### Device Physically Disconnected

| Current State | Action |
|---------------|--------|
| Connected | Device removed → Module stops → Dot dark, Button says "Show" |

## Key Invariants

1. **Button text reflects window state**: "Hide" if window is visible, "Show" if hidden
2. **Dot reflects connection state**: Green if connected, dark if disconnected
3. **Show always succeeds**: Clicking Show must always result in a visible window (connecting and starting if needed)
4. **Window state is tracked locally in DeviceRow**: `_window_visible` tracks current state
5. **External changes update UI**: Module window_hidden/window_shown events update button text via callback

## Implementation Notes

### toggle_device_window(device_id, visible=True) Logic:
```
if visible:
    if device not connected:
        connect_device()  # This starts module and shows window
        return

    if module not running:
        start_module()  # Window opens on start
        return

    send_show_window_command()
else:
    send_hide_window_command()
```

### Button Click Handler:
```
on_show_click():
    new_visible = not _window_visible
    _window_visible = new_visible  # Optimistic update
    update_button_text()
    call toggle_device_window(device_id, new_visible)
```

### Window Visibility Callback (from module):
```
on_window_visibility_changed(device_id, visible):
    device_row.set_window_visible(visible)  # Updates button text
```

## Problem Areas to Fix

1. **Optimistic update issue**: Button text changes before action completes - if action fails, button is wrong
2. **Race conditions**: Multiple clicks can cause inconsistent state
3. **Module already running but window hidden**: Need to send show_window command, not try to start module
4. **Button text not updated when module window opens via connect**: Need to set _window_visible = True
