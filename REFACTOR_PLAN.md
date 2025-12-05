# RS Logger Major Refactor: Centralized Device Discovery

## Overview

This document outlines the architectural changes required to move device discovery from individual modules (VOG, DRT) into the main RS Logger application. This refactor introduces a new "Connections" menu with USB device scanning, a unified device panel in the main UI, and changes to module lifecycle management.

### Goals

1. **Centralized Device Discovery** - Move USB/XBee scanning from modules to main logger
2. **Unified Device Panel** - Display all discovered devices in main UI with connect/launch controls
3. **Decoupled Window Lifecycle** - Closing module window no longer stops the module process
4. **Extensible Connection Architecture** - Design for future connection types (network, serial, etc.)

---

## Project Structure Reference

```
/home/joel/Development/TheLogger/
├── rpi_logger/
│   ├── __init__.py
│   ├── __main__.py
│   ├── app/
│   │   └── master.py                    # Main application entry
│   ├── core/
│   │   ├── commands/
│   │   │   ├── __init__.py
│   │   │   ├── command_protocol.py      # JSON command/status protocol
│   │   │   └── base_handler.py
│   │   ├── ui/
│   │   │   ├── __init__.py
│   │   │   ├── main_window.py           # Main Tkinter window
│   │   │   ├── main_controller.py       # UI event handling
│   │   │   ├── timer_manager.py
│   │   │   └── help_dialogs.py
│   │   ├── logger_system.py             # Facade for module management
│   │   ├── module_manager.py            # Module lifecycle management
│   │   ├── module_process.py            # Subprocess management
│   │   ├── module_discovery.py          # Module auto-discovery
│   │   ├── session_manager.py
│   │   ├── config_manager.py
│   │   ├── window_manager.py
│   │   ├── shutdown_coordinator.py
│   │   └── paths.py                     # Path constants
│   ├── modules/
│   │   ├── base/
│   │   │   ├── gui_utils.py
│   │   │   └── constants.py
│   │   ├── VOG/
│   │   │   ├── main_vog.py              # Entry point
│   │   │   ├── config.txt
│   │   │   └── vog_core/
│   │   │       ├── vog_system.py        # VOG system coordinator
│   │   │       ├── connection_manager.py # USB/XBee device scanning
│   │   │       ├── vog_handler.py       # Device communication handler
│   │   │       ├── xbee_manager.py      # XBee wireless management
│   │   │       ├── device_types.py      # Device VID/PID registry
│   │   │       ├── protocols/
│   │   │       │   ├── __init__.py
│   │   │       │   ├── svog_protocol.py
│   │   │       │   └── wvog_protocol.py
│   │   │       ├── transports/
│   │   │       │   ├── __init__.py
│   │   │       │   ├── base_transport.py
│   │   │       │   ├── usb_transport.py
│   │   │       │   └── xbee_transport.py
│   │   │       └── interfaces/gui/
│   │   │           └── tkinter_gui.py
│   │   └── DRT/
│   │       ├── main_drt.py              # Entry point
│   │       ├── config.txt
│   │       └── drt_core/
│   │           ├── drt_system.py        # DRT system coordinator
│   │           ├── connection_manager.py # USB/XBee device scanning
│   │           ├── xbee_manager.py      # XBee wireless management
│   │           ├── device_types.py      # Device VID/PID registry
│   │           ├── protocols.py
│   │           ├── transports/
│   │           │   ├── __init__.py
│   │           │   ├── base_transport.py
│   │           │   ├── usb_transport.py
│   │           │   └── xbee_transport.py
│   │           └── handlers/
│   │               ├── base_handler.py
│   │               ├── sdrt_handler.py
│   │               └── wdrt_handler.py
│   └── tools/
└── config.txt                           # Main logger config
```

---

## Current Architecture

### How Modules Are Launched (module_process.py:62-151)

```python
# ModuleProcess.start() creates subprocess:
cmd = [sys.executable, str(self.module_info.entry_point)] + base_args
# base_args includes:
#   --mode gui|simple
#   --output-dir <session_dir>
#   --session-prefix <prefix>
#   --log-level <level>
#   --no-console
#   --enable-commands
#   --window-geometry <geometry>

self.process = await asyncio.create_subprocess_exec(
    *cmd,
    stdin=asyncio.subprocess.PIPE,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)
```

### JSON Command Protocol (command_protocol.py)

**Commands (Master → Module via stdin):**
```python
class CommandMessage:
    @staticmethod
    def create(command: str, **kwargs) -> str:
        message = {
            "command": command,
            "timestamp": datetime.datetime.now().isoformat(),
        }
        message.update(kwargs)
        return json.dumps(message) + "\n"

# Available commands:
# - start_session(session_dir)
# - stop_session()
# - record(session_dir, trial_number, trial_label)
# - pause()
# - get_status()
# - get_geometry()
# - toggle_preview(camera_id, enabled)
# - quit()
```

**Status Messages (Module → Master via stdout):**
```python
class StatusMessage:
    @staticmethod
    def send(status: str, data: Optional[Dict] = None) -> None:
        message = {
            "type": "status",
            "status": status,
            "timestamp": datetime.datetime.now().isoformat(),
            "data": data or {}
        }
        print(json.dumps(message), file=sys.stdout, flush=True)

# Status types (StatusType class):
# - INITIALIZING, INITIALIZED
# - DISCOVERING, DEVICE_DETECTED
# - RECORDING_STARTED, RECORDING_STOPPED
# - GEOMETRY_CHANGED
# - ERROR, WARNING, QUITTING
```

### Module State Machine (module_process.py:17-25)

```python
class ModuleState(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    INITIALIZING = "initializing"
    IDLE = "idle"
    RECORDING = "recording"
    STOPPING = "stopping"
    ERROR = "error"
    CRASHED = "crashed"
```

### Main Window Menu Structure (main_window.py:154-234)

```python
def _build_menubar(self) -> None:
    menubar = tk.Menu(self.root)
    self.root.config(menu=menubar)

    # Modules menu - dynamic checkbuttons for each module
    modules_menu = tk.Menu(menubar, tearoff=0)
    menubar.add_cascade(label="Modules", menu=modules_menu)
    for module_info in self.logger_system.get_available_modules():
        var = tk.BooleanVar(value=is_enabled)
        self.module_vars[module_info.name] = var
        modules_menu.add_checkbutton(
            label=module_info.display_name,
            variable=var,
            command=lambda name=module_info.name: self._schedule_task(...)
        )

    # View menu
    view_menu = tk.Menu(menubar, tearoff=0)
    menubar.add_cascade(label="View", menu=view_menu)
    view_menu.add_checkbutton(label="Show System Log", ...)

    # Help menu
    help_menu = tk.Menu(menubar, tearoff=0)
    menubar.add_cascade(label="Help", menu=help_menu)
```

### Main Window Layout (main_window.py:100-130)

```python
def build_ui(self) -> None:
    self.root = tk.Tk()
    self.root.title("RS Logger")

    # Grid layout:
    # Row 0: Header (logo) - weight=0, fixed height 80px
    # Row 1: Main content (controls + info) - weight=1, expandable
    # Row 2: Logger frame (system log) - weight=0, fixed height

    self.root.columnconfigure(0, weight=1)
    self.root.rowconfigure(0, weight=0)  # Header
    self.root.rowconfigure(1, weight=1)  # Main content
    self.root.rowconfigure(2, weight=0)  # Logger
```

---

## Device Registry - Exact Values

### VOG Devices (vog_core/device_types.py)

```python
class VOGDeviceType(Enum):
    SVOG = "sVOG"
    WVOG_USB = "wVOG_USB"
    WVOG_WIRELESS = "wVOG_Wireless"

DEVICE_REGISTRY: Dict[VOGDeviceType, DeviceSpec] = {
    VOGDeviceType.SVOG: DeviceSpec(
        vid=0x16C0,
        pid=0x0483,
        name='sVOG',
        baudrate=115200
    ),
    VOGDeviceType.WVOG_USB: DeviceSpec(
        vid=0xF057,
        pid=0x08AE,
        name='wVOG',
        baudrate=57600
    ),
}

XBEE_DONGLE = DeviceSpec(
    vid=0x0403,
    pid=0x6015,
    name='XBee',
    baudrate=57600
)
```

### DRT Devices (drt_core/device_types.py)

```python
class DRTDeviceType(Enum):
    SDRT = "sDRT"
    WDRT_USB = "wDRT_USB"
    WDRT_WIRELESS = "wDRT_Wireless"

DEVICE_REGISTRY: Dict[DRTDeviceType, DeviceSpec] = {
    DRTDeviceType.SDRT: DeviceSpec(
        vid=0x239A,
        pid=0x801E,
        name='sDRT',
        baudrate=9600
    ),
    DRTDeviceType.WDRT_USB: DeviceSpec(
        vid=0xF056,
        pid=0x0457,
        name='wDRT',
        baudrate=921600
    ),
}

XBEE_DONGLE = DeviceSpec(
    vid=0x0403,
    pid=0x6015,
    name='XBee',
    baudrate=921600  # Note: Different from VOG!
)
```

### XBee Wireless Device Node ID Patterns

```python
# VOG (xbee_manager.py:416-422):
match = re.match(r'^([a-zA-Z]+)[_\s]*(\d+)$', node_id.strip())
if device_type.lower() != 'wvog':
    return  # Ignore non-wVOG devices
# Matches: "wVOG_01", "wVOG 02", "wVOG_1"

# DRT (same pattern):
if device_type.lower() != 'wdrt':
    return  # Ignore non-wDRT devices
# Matches: "wDRT_01", "wDRT 02", "wDRT_1"
```

---

## Target Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Main Logger                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ ┌──────────┐ │
│  │ Module Menu │  │ Connections │  │ View Menu   │ │Help Menu │ │
│  │ ☑ Cameras   │  │ ☑ USB       │  │ ☑ Show Log  │ │          │ │
│  │ ☑ Audio     │  │ ☐ Network   │  │ ☑ Show USB  │ │          │ │
│  │ ☐ Notes     │  │   (future)  │  │   Devices   │ │          │ │
│  └─────────────┘  └─────────────┘  └─────────────┘ └──────────┘ │
│                                                                  │
│  [Start Session]  [Record]  Trial Label: [________]              │
│                                                                  │
│  Session Info Panel                                              │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ USB Devices                                          [Hide] │ │
│  │ ┌─────────────────────────────────────────────────────────┐ │ │
│  │ │ ☐ sVOG on /dev/ttyACM0              [Connect] [Window]  │ │ │
│  │ │ ☑ sDRT on /dev/ttyACM1              [Disconnect][Window]│ │ │
│  │ │ ▼ XBee Dongle on /dev/ttyUSB0       [Connected]         │ │ │
│  │ │   ├─ ☐ wVOG_01 (85%)                [Connect] [Window]  │ │ │
│  │ │   └─ ☑ wDRT_02 (72%)                [Disconnect][Window]│ │ │
│  │ └─────────────────────────────────────────────────────────┘ │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  System Log (toggleable)                                         │
└─────────────────────────────────────────────────────────────────┘
```

---

## Phases

### Phase 1: Core Infrastructure ✅ COMPLETE
- [x] **1.1** Create unified device registry in core (`rpi_logger/core/devices/`)
- [x] **1.2** Create USB scanner service
- [x] **1.3** Create XBee manager service (unified for VOG + DRT)
- [x] **1.4** Create device connection manager
- [x] **1.5** Define device-to-module mapping

### Phase 2: UI Changes ✅ COMPLETE
- [x] **2.1** Add "Connections" menu to main window
- [x] **2.2** Create USB Devices panel widget
- [x] **2.3** Add device row widget (checkbox, info, connect/disconnect, window buttons)
- [x] **2.4** Add XBee dongle expandable row with child devices
- [x] **2.5** Integrate panel into main window layout (new row between info and logger)
- [x] **2.6** Add panel show/hide toggle in View menu

### Phase 3: Module Lifecycle Changes ✅ COMPLETE
- [x] **3.1** Add new commands: `assign_device`, `unassign_device`, `show_window`, `hide_window`
- [x] **3.2** Modify module window close behavior (hide instead of quit) - handled in base_handler.py
- [x] **3.3** Update module state machine for new lifecycle - modules now wait for device assignments
- [x] **3.4** Handle device disconnect while module running - unassign_device command implemented

### Phase 4: VOG Module Refactor ✅ COMPLETE
- [x] **4.1** Remove USB scanning from VOG vog_system.py
- [x] **4.2** Remove USB monitor usage from VOG (XBee manager still exists but unused)
- [x] **4.3** Add device assignment command handler to VOG (assign_device/unassign_device in vog_system.py)
- [x] **4.4** Update VOG to work with assigned devices (creates transport from port info)
- [x] **4.5** Handle window hide/show commands in VOG GUI (handled by base_handler.py)

### Phase 5: DRT Module Refactor ✅ COMPLETE
- [x] **5.1** Remove USB scanning from DRT drt_system.py
- [x] **5.2** Remove ConnectionManager usage from DRT
- [x] **5.3** Add device assignment command handler to DRT (assign_device/unassign_device)
- [x] **5.4** Update DRT to work with assigned devices (creates transport from port info)
- [x] **5.5** Handle window hide/show commands in DRT GUI (handled by base_handler.py)

### Phase 6: Integration & Testing 🔲 NOT STARTED
- [ ] **6.1** End-to-end testing with sVOG device
- [ ] **6.2** End-to-end testing with sDRT device
- [ ] **6.3** End-to-end testing with XBee + wVOG wireless
- [ ] **6.4** End-to-end testing with XBee + wDRT wireless
- [ ] **6.5** Hot-plug testing (connect/disconnect during session)
- [ ] **6.6** Recording session testing with multiple devices
- [ ] **6.7** Update documentation

---

## Detailed Design

### Phase 1: Core Infrastructure

#### 1.1 Unified Device Registry

**New File:** `rpi_logger/core/devices/__init__.py`
**New File:** `rpi_logger/core/devices/device_registry.py`

```python
"""
Unified device registry for all supported USB and wireless devices.

This replaces the separate registries in:
- rpi_logger/modules/VOG/vog_core/device_types.py
- rpi_logger/modules/DRT/drt_core/device_types.py
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict

class DeviceFamily(Enum):
    """Top-level device family classification."""
    VOG = "VOG"
    DRT = "DRT"

class DeviceType(Enum):
    """All supported device types across all modules."""
    # VOG devices
    SVOG = "sVOG"
    WVOG_USB = "wVOG_USB"
    WVOG_WIRELESS = "wVOG_Wireless"

    # DRT devices
    SDRT = "sDRT"
    WDRT_USB = "wDRT_USB"
    WDRT_WIRELESS = "wDRT_Wireless"

    # Coordinator dongles
    XBEE_COORDINATOR = "XBee_Coordinator"

@dataclass(frozen=True)
class DeviceSpec:
    """Specification for a device type."""
    device_type: DeviceType
    family: DeviceFamily
    vid: Optional[int]          # USB Vendor ID (None for wireless)
    pid: Optional[int]          # USB Product ID (None for wireless)
    baudrate: int
    display_name: str
    module_id: str              # Which module handles this device ("vog" or "drt")
    is_coordinator: bool = False

# Complete registry of all supported devices
DEVICE_REGISTRY: Dict[DeviceType, DeviceSpec] = {
    # VOG devices
    DeviceType.SVOG: DeviceSpec(
        device_type=DeviceType.SVOG,
        family=DeviceFamily.VOG,
        vid=0x16C0,
        pid=0x0483,
        baudrate=115200,
        display_name="sVOG",
        module_id="vog",
    ),
    DeviceType.WVOG_USB: DeviceSpec(
        device_type=DeviceType.WVOG_USB,
        family=DeviceFamily.VOG,
        vid=0xF057,
        pid=0x08AE,
        baudrate=57600,
        display_name="wVOG (USB)",
        module_id="vog",
    ),
    DeviceType.WVOG_WIRELESS: DeviceSpec(
        device_type=DeviceType.WVOG_WIRELESS,
        family=DeviceFamily.VOG,
        vid=None,
        pid=None,
        baudrate=57600,
        display_name="wVOG (Wireless)",
        module_id="vog",
    ),

    # DRT devices
    DeviceType.SDRT: DeviceSpec(
        device_type=DeviceType.SDRT,
        family=DeviceFamily.DRT,
        vid=0x239A,
        pid=0x801E,
        baudrate=9600,
        display_name="sDRT",
        module_id="drt",
    ),
    DeviceType.WDRT_USB: DeviceSpec(
        device_type=DeviceType.WDRT_USB,
        family=DeviceFamily.DRT,
        vid=0xF056,
        pid=0x0457,
        baudrate=921600,
        display_name="wDRT (USB)",
        module_id="drt",
    ),
    DeviceType.WDRT_WIRELESS: DeviceSpec(
        device_type=DeviceType.WDRT_WIRELESS,
        family=DeviceFamily.DRT,
        vid=None,
        pid=None,
        baudrate=921600,
        display_name="wDRT (Wireless)",
        module_id="drt",
    ),

    # XBee coordinator (same VID/PID for both VOG and DRT)
    DeviceType.XBEE_COORDINATOR: DeviceSpec(
        device_type=DeviceType.XBEE_COORDINATOR,
        family=DeviceFamily.VOG,  # Arbitrary, handles both
        vid=0x0403,
        pid=0x6015,
        baudrate=921600,  # Use higher baudrate to support wDRT
        display_name="XBee Coordinator",
        module_id="",
        is_coordinator=True,
    ),
}

def identify_usb_device(vid: int, pid: int) -> Optional[DeviceSpec]:
    """
    Identify a USB device by VID/PID.

    Args:
        vid: USB Vendor ID
        pid: USB Product ID

    Returns:
        DeviceSpec if recognized, None otherwise
    """
    for spec in DEVICE_REGISTRY.values():
        if spec.vid == vid and spec.pid == pid:
            return spec
    return None

def get_spec(device_type: DeviceType) -> DeviceSpec:
    """Get specification for a device type."""
    return DEVICE_REGISTRY[device_type]

def parse_wireless_node_id(node_id: str) -> Optional[DeviceType]:
    """
    Parse XBee node ID to determine device type.

    Expected formats:
    - "wVOG_XX" or "wVOG XX" -> DeviceType.WVOG_WIRELESS
    - "wDRT_XX" or "wDRT XX" -> DeviceType.WDRT_WIRELESS

    Args:
        node_id: The XBee node identifier string

    Returns:
        DeviceType if recognized, None otherwise
    """
    import re
    match = re.match(r'^([a-zA-Z]+)[_\s]*(\d+)$', node_id.strip())
    if not match:
        return None

    device_type_str = match.group(1).lower()

    if device_type_str == 'wvog':
        return DeviceType.WVOG_WIRELESS
    elif device_type_str == 'wdrt':
        return DeviceType.WDRT_WIRELESS

    return None
```

#### 1.2 USB Scanner Service

**New File:** `rpi_logger/core/devices/usb_scanner.py`

This service continuously scans USB ports and emits callbacks when devices are found/lost.

Key implementation notes:
- Use `serial.tools.list_ports.comports()` (same as existing modules)
- Run in asyncio task with `asyncio.to_thread()` for blocking calls
- Default scan interval: 1.0 seconds (matches existing modules)
- Exclude XBee dongle from regular device list (handled separately)

```python
"""
USB port scanner for device discovery.

Replaces scanning in:
- rpi_logger/modules/VOG/vog_core/connection_manager.py:182-227
- rpi_logger/modules/DRT/drt_core/connection_manager.py (similar)
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Callable, Optional, Dict, Set
import serial.tools.list_ports

from .device_registry import DeviceSpec, DeviceType, identify_usb_device

logger = logging.getLogger(__name__)

@dataclass
class DiscoveredUSBDevice:
    """Represents a discovered USB device."""
    port: str                    # e.g., "/dev/ttyACM0"
    device_type: DeviceType
    spec: DeviceSpec
    serial_number: Optional[str]
    description: str             # e.g., "sVOG" or port description

class USBScanner:
    """
    Continuously scans USB ports for supported devices.

    Usage:
        scanner = USBScanner(
            on_device_found=handle_found,
            on_device_lost=handle_lost,
        )
        await scanner.start()
        # ... later ...
        await scanner.stop()
    """

    def __init__(
        self,
        scan_interval: float = 1.0,
        on_device_found: Optional[Callable[[DiscoveredUSBDevice], None]] = None,
        on_device_lost: Optional[Callable[[str], None]] = None,
    ):
        self._scan_interval = scan_interval
        self._on_device_found = on_device_found
        self._on_device_lost = on_device_lost

        self._known_devices: Dict[str, DiscoveredUSBDevice] = {}
        self._known_ports: Set[str] = set()
        self._scan_task: Optional[asyncio.Task] = None
        self._running = False

    @property
    def devices(self) -> Dict[str, DiscoveredUSBDevice]:
        """Get currently known devices (port -> device)."""
        return dict(self._known_devices)

    async def start(self) -> None:
        """Start the USB scanning loop."""
        if self._running:
            return
        self._running = True

        # Perform initial scan immediately
        await self._scan_ports()

        # Start continuous scanning
        self._scan_task = asyncio.create_task(self._scan_loop())
        logger.info("USB scanner started")

    async def stop(self) -> None:
        """Stop the USB scanning loop."""
        self._running = False
        if self._scan_task:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass
            self._scan_task = None

        self._known_devices.clear()
        self._known_ports.clear()
        logger.info("USB scanner stopped")

    async def _scan_loop(self) -> None:
        """Main scanning loop."""
        while self._running:
            try:
                await asyncio.sleep(self._scan_interval)
                await self._scan_ports()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in USB scan loop: {e}")

    async def _scan_ports(self) -> None:
        """Scan for USB devices and detect changes."""
        try:
            # Run blocking comports() in thread
            ports = await asyncio.to_thread(serial.tools.list_ports.comports)
            current_ports: Set[str] = set()

            for port_info in ports:
                port = port_info.device
                current_ports.add(port)

                # Skip if already known
                if port in self._known_devices:
                    continue

                # Skip if no VID/PID
                if port_info.vid is None or port_info.pid is None:
                    continue

                # Try to identify device
                spec = identify_usb_device(port_info.vid, port_info.pid)
                if spec is None:
                    continue

                # New supported device found
                device = DiscoveredUSBDevice(
                    port=port,
                    device_type=spec.device_type,
                    spec=spec,
                    serial_number=port_info.serial_number,
                    description=port_info.description or spec.display_name,
                )

                self._known_devices[port] = device
                logger.info(f"USB device found: {spec.display_name} on {port}")

                if self._on_device_found:
                    self._on_device_found(device)

            # Check for disconnected devices
            lost_ports = set(self._known_devices.keys()) - current_ports
            for port in lost_ports:
                device = self._known_devices.pop(port)
                logger.info(f"USB device lost: {device.spec.display_name} on {port}")

                if self._on_device_lost:
                    self._on_device_lost(port)

            self._known_ports = current_ports

        except Exception as e:
            logger.error(f"Error scanning USB ports: {e}")
```

#### 1.3 XBee Manager Service

**New File:** `rpi_logger/core/devices/xbee_manager.py`

This is a unified XBee manager that handles BOTH wVOG and wDRT devices (unlike existing separate managers).

Key differences from existing implementations:
- Single manager handles both device families
- Parses node_id to determine if wVOG or wDRT
- Uses higher baudrate (921600) to support wDRT
- Provides battery info via callbacks

Based on existing code at:
- `rpi_logger/modules/VOG/vog_core/xbee_manager.py`
- `rpi_logger/modules/DRT/drt_core/xbee_manager.py`

```python
"""
Unified XBee manager for wireless device discovery.

Combines functionality from:
- rpi_logger/modules/VOG/vog_core/xbee_manager.py
- rpi_logger/modules/DRT/drt_core/xbee_manager.py

Key difference: This manager handles BOTH wVOG and wDRT devices.
"""

import asyncio
import re
import logging
from dataclasses import dataclass
from typing import Dict, Optional, Callable, Awaitable, Set
from enum import Enum

import serial.tools.list_ports

from .device_registry import DeviceType, DeviceFamily, parse_wireless_node_id, get_spec

logger = logging.getLogger(__name__)

# XBee dongle identification
XBEE_VID = 0x0403
XBEE_PID = 0x6015
XBEE_BAUDRATE = 921600  # Higher baudrate to support wDRT

# Try to import digi-xbee library
try:
    from digi.xbee.devices import XBeeDevice, RemoteRaw802Device
    from digi.xbee.models.message import XBeeMessage
    XBEE_AVAILABLE = True
except ImportError:
    XBEE_AVAILABLE = False
    logger.warning("digi-xbee library not installed - XBee support disabled")

@dataclass
class WirelessDevice:
    """Represents a discovered wireless device."""
    node_id: str                 # e.g., "wVOG_01" or "wDRT_02"
    device_type: DeviceType
    family: DeviceFamily
    address_64bit: str
    battery_percent: Optional[int] = None

class XBeeManagerState(Enum):
    DISABLED = "disabled"
    SCANNING = "scanning"
    CONNECTED = "connected"
    DISCOVERING = "discovering"

class XBeeManager:
    """
    Manages XBee coordinator and wireless device discovery.

    Handles both wVOG and wDRT wireless devices through a single coordinator.
    """

    DEFAULT_SCAN_INTERVAL = 1.0
    DEFAULT_REDISCOVERY_INTERVAL = 30.0

    def __init__(
        self,
        scan_interval: float = DEFAULT_SCAN_INTERVAL,
        rediscovery_interval: float = DEFAULT_REDISCOVERY_INTERVAL,
        on_dongle_connected: Optional[Callable[[str], Awaitable[None]]] = None,
        on_dongle_disconnected: Optional[Callable[[], Awaitable[None]]] = None,
        on_device_discovered: Optional[Callable[[WirelessDevice], Awaitable[None]]] = None,
        on_device_lost: Optional[Callable[[str], Awaitable[None]]] = None,
        on_battery_update: Optional[Callable[[str, int], Awaitable[None]]] = None,
    ):
        if not XBEE_AVAILABLE:
            raise RuntimeError("digi-xbee library not installed")

        self._scan_interval = scan_interval
        self._rediscovery_interval = rediscovery_interval

        # Callbacks
        self._on_dongle_connected = on_dongle_connected
        self._on_dongle_disconnected = on_dongle_disconnected
        self._on_device_discovered = on_device_discovered
        self._on_device_lost = on_device_lost
        self._on_battery_update = on_battery_update

        # State
        self._state = XBeeManagerState.DISABLED
        self._enabled = True
        self._coordinator: Optional['XBeeDevice'] = None
        self._coordinator_port: Optional[str] = None
        self._discovered_devices: Dict[str, WirelessDevice] = {}
        self._remote_devices: Dict[str, 'RemoteRaw802Device'] = {}

        # Tasks
        self._scan_task: Optional[asyncio.Task] = None
        self._rediscovery_task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @property
    def is_connected(self) -> bool:
        return self._coordinator is not None and self._coordinator.is_open()

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    @property
    def coordinator_port(self) -> Optional[str]:
        return self._coordinator_port if self.is_connected else None

    @property
    def discovered_devices(self) -> Dict[str, WirelessDevice]:
        return dict(self._discovered_devices)

    async def start(self) -> None:
        """Start XBee manager (enable dongle scanning)."""
        if not self._enabled:
            logger.info("XBee manager disabled, not starting")
            return

        self._state = XBeeManagerState.SCANNING
        self._loop = asyncio.get_running_loop()
        self._scan_task = asyncio.create_task(self._scan_loop())
        logger.info("XBee manager started")

    async def stop(self) -> None:
        """Stop XBee manager and disconnect coordinator."""
        # Cancel tasks
        for task in [self._scan_task, self._rediscovery_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._scan_task = None
        self._rediscovery_task = None

        # Close coordinator
        await self._close_coordinator()

        self._state = XBeeManagerState.DISABLED
        logger.info("XBee manager stopped")

    def disable(self) -> None:
        """Disable for mutual exclusion with USB devices."""
        self._enabled = False
        self._state = XBeeManagerState.DISABLED

    def enable(self) -> None:
        """Re-enable after disable."""
        self._enabled = True

    async def _scan_loop(self) -> None:
        """Scan for XBee dongle."""
        while self._enabled:
            try:
                await self._check_dongle()
                await asyncio.sleep(self._scan_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in XBee scan loop: {e}")

    async def _check_dongle(self) -> None:
        """Check for XBee dongle presence."""
        try:
            ports = await asyncio.to_thread(serial.tools.list_ports.comports)

            dongle_port = None
            for port_info in ports:
                if port_info.vid == XBEE_VID and port_info.pid == XBEE_PID:
                    dongle_port = port_info.device
                    break

            if dongle_port and not self.is_connected:
                await self._initialize_coordinator(dongle_port)
            elif not dongle_port and self.is_connected:
                await self._close_coordinator()

        except Exception as e:
            logger.error(f"Error checking for XBee dongle: {e}")

    async def _initialize_coordinator(self, port: str) -> None:
        """Initialize XBee coordinator on given port."""
        try:
            logger.info(f"Initializing XBee coordinator on {port}")

            self._coordinator = await asyncio.to_thread(
                XBeeDevice, port, XBEE_BAUDRATE
            )
            await asyncio.to_thread(self._coordinator.open)
            self._coordinator_port = port
            self._state = XBeeManagerState.CONNECTED

            # Set up message callback
            self._coordinator.add_data_received_callback(self._on_message_received)

            if self._on_dongle_connected:
                await self._on_dongle_connected(port)

            # Start network discovery
            await self._start_discovery()

            # Start periodic rediscovery
            self._rediscovery_task = asyncio.create_task(
                self._periodic_rediscovery()
            )

        except Exception as e:
            logger.error(f"Failed to initialize XBee coordinator: {e}")
            self._coordinator = None
            self._coordinator_port = None

    async def _close_coordinator(self) -> None:
        """Close coordinator and notify about lost devices."""
        # Cancel rediscovery
        if self._rediscovery_task:
            self._rediscovery_task.cancel()
            try:
                await self._rediscovery_task
            except asyncio.CancelledError:
                pass
            self._rediscovery_task = None

        # Notify about lost devices
        for node_id in list(self._discovered_devices.keys()):
            if self._on_device_lost:
                await self._on_device_lost(node_id)
        self._discovered_devices.clear()
        self._remote_devices.clear()

        # Close coordinator
        if self._coordinator:
            try:
                if self._coordinator.is_open():
                    await asyncio.to_thread(self._coordinator.close)
            except Exception as e:
                logger.error(f"Error closing coordinator: {e}")
            finally:
                self._coordinator = None
                self._coordinator_port = None

        if self._on_dongle_disconnected:
            await self._on_dongle_disconnected()

    async def _start_discovery(self) -> None:
        """Start XBee network discovery."""
        if not self.is_connected:
            return

        try:
            logger.info("Starting XBee network discovery")
            self._state = XBeeManagerState.DISCOVERING

            network = self._coordinator.get_network()
            network.add_discovery_process_finished_callback(
                self._on_discovery_finished
            )
            await asyncio.to_thread(network.start_discovery_process)

        except Exception as e:
            logger.error(f"Error starting discovery: {e}")

    async def _periodic_rediscovery(self) -> None:
        """Periodically trigger network rediscovery."""
        while self._enabled and self.is_connected:
            try:
                await asyncio.sleep(self._rediscovery_interval)
                if self.is_connected:
                    await self._start_discovery()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic rediscovery: {e}")

    def _on_discovery_finished(self, status) -> None:
        """Callback when discovery completes (called from XBee thread)."""
        if not self.is_connected or not self._loop:
            return

        try:
            network = self._coordinator.get_network()
            devices = network.get_devices()
            logger.info(f"Network discovery found {len(devices)} device(s)")

            for device in devices:
                self._loop.call_soon_threadsafe(
                    lambda d=device: asyncio.create_task(
                        self._handle_device_discovered(d)
                    )
                )

        except Exception as e:
            logger.error(f"Error processing discovery: {e}")

    async def _handle_device_discovered(self, remote_device) -> None:
        """Handle a discovered XBee device."""
        try:
            node_id = remote_device.get_node_id()
            if not node_id:
                return

            # Skip if already known
            if node_id in self._discovered_devices:
                return

            # Parse to determine type (wVOG or wDRT)
            device_type = parse_wireless_node_id(node_id)
            if not device_type:
                logger.debug(f"Ignoring unknown device: {node_id}")
                return

            spec = get_spec(device_type)
            address = str(remote_device.get_64bit_addr())

            device = WirelessDevice(
                node_id=node_id,
                device_type=device_type,
                family=spec.family,
                address_64bit=address,
            )

            self._discovered_devices[node_id] = device
            self._remote_devices[node_id] = remote_device

            logger.info(f"Discovered wireless device: {node_id} ({device_type.value})")

            if self._on_device_discovered:
                await self._on_device_discovered(device)

        except Exception as e:
            logger.error(f"Error handling discovered device: {e}")

    def _on_message_received(self, message) -> None:
        """Handle received XBee message (called from XBee thread)."""
        # Route to appropriate handler based on sender
        # This will be used for battery updates, etc.
        pass

    async def trigger_rediscovery(self) -> None:
        """Manually trigger network rediscovery."""
        if self.is_connected:
            await self._start_discovery()

    async def sync_rtc_all(self) -> int:
        """Sync RTC on all discovered devices. Returns count synced."""
        # Implementation needed
        return 0
```

#### 1.4 Device Connection Manager

**New File:** `rpi_logger/core/devices/connection_manager.py`

Central coordinator that:
- Manages USB scanner and XBee manager
- Tracks device connection state
- Handles mutual exclusion (USB w-device disables XBee)
- Provides unified interface for UI

```python
"""
Central device connection manager.

Coordinates USB scanning, XBee management, and provides unified interface for UI.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Callable, Optional, Dict, Set
from enum import Enum

from .device_registry import DeviceType, DeviceFamily, get_spec
from .usb_scanner import USBScanner, DiscoveredUSBDevice
from .xbee_manager import XBeeManager, WirelessDevice, XBEE_AVAILABLE

logger = logging.getLogger(__name__)

class ConnectionState(Enum):
    """Device connection state from UI perspective."""
    DISCOVERED = "discovered"    # Found but not connected to module
    CONNECTING = "connecting"    # Connection in progress
    CONNECTED = "connected"      # Actively connected to module
    ERROR = "error"              # Connection failed

@dataclass
class DeviceInfo:
    """Device information for UI display."""
    device_id: str               # Unique ID (port for USB, node_id for wireless)
    device_type: DeviceType
    family: DeviceFamily
    display_name: str
    port: Optional[str]          # USB port, or None for wireless
    state: ConnectionState = ConnectionState.DISCOVERED
    battery_percent: Optional[int] = None
    error_message: Optional[str] = None
    parent_id: Optional[str] = None  # For wireless: the dongle port

@dataclass
class XBeeDongleInfo:
    """XBee dongle information for UI."""
    port: str
    state: ConnectionState = ConnectionState.DISCOVERED
    child_devices: Dict[str, DeviceInfo] = field(default_factory=dict)

class DeviceConnectionManager:
    """
    Central manager for all device connections.

    Coordinates USB scanning, XBee management, and device-to-module routing.
    """

    def __init__(self):
        # Initialize scanners
        self._usb_scanner = USBScanner(
            on_device_found=self._on_usb_device_found,
            on_device_lost=self._on_usb_device_lost,
        )

        self._xbee_manager: Optional[XBeeManager] = None
        if XBEE_AVAILABLE:
            self._xbee_manager = XBeeManager(
                on_dongle_connected=self._on_xbee_dongle_connected,
                on_dongle_disconnected=self._on_xbee_dongle_disconnected,
                on_device_discovered=self._on_wireless_device_discovered,
                on_device_lost=self._on_wireless_device_lost,
                on_battery_update=self._on_wireless_battery_update,
            )

        # Device tracking
        self._usb_devices: Dict[str, DeviceInfo] = {}
        self._xbee_dongles: Dict[str, XBeeDongleInfo] = {}
        self._connected_devices: Set[str] = set()

        # UI callback
        self._on_devices_changed: Optional[Callable[[], None]] = None

        # State
        self._usb_scanning_enabled = False

    def set_devices_changed_callback(self, callback: Callable[[], None]) -> None:
        """Set callback for when device list changes (for UI updates)."""
        self._on_devices_changed = callback

    async def start_usb_scanning(self) -> None:
        """Start USB device scanning."""
        if self._usb_scanning_enabled:
            return

        self._usb_scanning_enabled = True
        await self._usb_scanner.start()

        if self._xbee_manager:
            await self._xbee_manager.start()

        logger.info("USB scanning enabled")

    async def stop_usb_scanning(self) -> None:
        """Stop USB device scanning."""
        if not self._usb_scanning_enabled:
            return

        self._usb_scanning_enabled = False
        await self._usb_scanner.stop()

        if self._xbee_manager:
            await self._xbee_manager.stop()

        self._usb_devices.clear()
        self._xbee_dongles.clear()
        self._notify_changed()

        logger.info("USB scanning disabled")

    @property
    def is_scanning(self) -> bool:
        return self._usb_scanning_enabled

    def get_all_devices(self) -> list[DeviceInfo]:
        """Get all discovered USB devices (excluding dongles)."""
        return list(self._usb_devices.values())

    def get_xbee_dongles(self) -> list[XBeeDongleInfo]:
        """Get all XBee dongles with their child devices."""
        return list(self._xbee_dongles.values())

    def is_device_connected(self, device_id: str) -> bool:
        """Check if device is connected to a module."""
        return device_id in self._connected_devices

    async def connect_device(self, device_id: str) -> bool:
        """Connect to a device (prepare for module assignment)."""
        device = self._find_device(device_id)
        if not device:
            logger.error(f"Device not found: {device_id}")
            return False

        device.state = ConnectionState.CONNECTING
        self._notify_changed()

        # TODO: Actual connection logic - create transport, assign to module
        # For now, just mark as connected
        device.state = ConnectionState.CONNECTED
        self._connected_devices.add(device_id)
        self._notify_changed()

        return True

    async def disconnect_device(self, device_id: str) -> None:
        """Disconnect from a device."""
        device = self._find_device(device_id)
        if device:
            device.state = ConnectionState.DISCOVERED
            self._connected_devices.discard(device_id)
            self._notify_changed()

    # --- Internal callbacks ---

    def _on_usb_device_found(self, device: DiscoveredUSBDevice) -> None:
        """Handle new USB device discovery."""
        # Check if XBee dongle
        if device.device_type == DeviceType.XBEE_COORDINATOR:
            self._xbee_dongles[device.port] = XBeeDongleInfo(port=device.port)
        else:
            self._usb_devices[device.port] = DeviceInfo(
                device_id=device.port,
                device_type=device.device_type,
                family=device.spec.family,
                display_name=f"{device.spec.display_name} on {device.port}",
                port=device.port,
            )

            # Mutual exclusion: USB w-device disables XBee
            if device.device_type in (DeviceType.WVOG_USB, DeviceType.WDRT_USB):
                if self._xbee_manager:
                    self._xbee_manager.disable()

        self._notify_changed()

    def _on_usb_device_lost(self, port: str) -> None:
        """Handle USB device disconnection."""
        device = self._usb_devices.pop(port, None)
        self._xbee_dongles.pop(port, None)

        if device:
            self._connected_devices.discard(port)

            # Re-enable XBee if no USB w-devices remain
            if device.device_type in (DeviceType.WVOG_USB, DeviceType.WDRT_USB):
                has_usb_w = any(
                    d.device_type in (DeviceType.WVOG_USB, DeviceType.WDRT_USB)
                    for d in self._usb_devices.values()
                )
                if not has_usb_w and self._xbee_manager:
                    self._xbee_manager.enable()
                    asyncio.create_task(self._xbee_manager.start())

        self._notify_changed()

    async def _on_xbee_dongle_connected(self, port: str) -> None:
        """Handle XBee dongle connection."""
        if port in self._xbee_dongles:
            self._xbee_dongles[port].state = ConnectionState.CONNECTED
            self._notify_changed()

    async def _on_xbee_dongle_disconnected(self) -> None:
        """Handle XBee dongle disconnection."""
        for dongle in self._xbee_dongles.values():
            for device_id in dongle.child_devices:
                self._connected_devices.discard(device_id)
            dongle.child_devices.clear()
            dongle.state = ConnectionState.DISCOVERED
        self._notify_changed()

    async def _on_wireless_device_discovered(self, device: WirelessDevice) -> None:
        """Handle wireless device discovery."""
        dongle_port = self._xbee_manager.coordinator_port if self._xbee_manager else None
        if dongle_port and dongle_port in self._xbee_dongles:
            dongle = self._xbee_dongles[dongle_port]
            dongle.child_devices[device.node_id] = DeviceInfo(
                device_id=device.node_id,
                device_type=device.device_type,
                family=device.family,
                display_name=device.node_id,
                port=None,
                battery_percent=device.battery_percent,
                parent_id=dongle_port,
            )
            self._notify_changed()

    async def _on_wireless_device_lost(self, node_id: str) -> None:
        """Handle wireless device loss."""
        for dongle in self._xbee_dongles.values():
            if node_id in dongle.child_devices:
                dongle.child_devices.pop(node_id)
                self._connected_devices.discard(node_id)
                self._notify_changed()
                return

    async def _on_wireless_battery_update(self, node_id: str, percent: int) -> None:
        """Handle wireless device battery update."""
        for dongle in self._xbee_dongles.values():
            if node_id in dongle.child_devices:
                dongle.child_devices[node_id].battery_percent = percent
                self._notify_changed()
                return

    def _find_device(self, device_id: str) -> Optional[DeviceInfo]:
        """Find device by ID."""
        if device_id in self._usb_devices:
            return self._usb_devices[device_id]
        for dongle in self._xbee_dongles.values():
            if device_id in dongle.child_devices:
                return dongle.child_devices[device_id]
        return None

    def _notify_changed(self) -> None:
        """Notify UI of device list change."""
        if self._on_devices_changed:
            self._on_devices_changed()
```

---

### Phase 2: UI Changes

#### 2.1 Connections Menu

**Modify:** `rpi_logger/core/ui/main_window.py`

Add new menu between "Modules" and "View" (around line 159):

```python
def _build_menubar(self) -> None:
    menubar = tk.Menu(self.root)
    self.root.config(menu=menubar)

    # Modules menu (existing)
    modules_menu = tk.Menu(menubar, tearoff=0)
    menubar.add_cascade(label="Modules", menu=modules_menu)
    # ... existing module checkbuttons ...

    # NEW: Connections menu
    connections_menu = tk.Menu(menubar, tearoff=0)
    menubar.add_cascade(label="Connections", menu=connections_menu)

    self.usb_scan_var = tk.BooleanVar(value=False)
    connections_menu.add_checkbutton(
        label="USB",
        variable=self.usb_scan_var,
        command=lambda: self._schedule_task(
            self.controller.on_usb_scan_toggle()
        )
    )

    # Future: Network scanning
    # connections_menu.add_checkbutton(label="Network", state="disabled")

    # View menu (existing)
    view_menu = tk.Menu(menubar, tearoff=0)
    menubar.add_cascade(label="View", menu=view_menu)
    # ... existing view options ...

    # NEW: Add USB Devices panel toggle to View menu
    self.show_devices_var = tk.BooleanVar(value=False)
    view_menu.add_checkbutton(
        label="Show USB Devices",
        variable=self.show_devices_var,
        command=self._toggle_devices_panel
    )

    # Help menu (existing)
    # ...
```

#### 2.2-2.4 USB Devices Panel Widget

**New File:** `rpi_logger/core/ui/devices_panel.py`

```python
"""
USB Devices panel for main window.

Displays discovered USB devices with connect/disconnect and window controls.
"""

import tkinter as tk
from tkinter import ttk
from typing import Callable, Dict, List, Optional

from ..devices.connection_manager import DeviceInfo, XBeeDongleInfo, ConnectionState


class DeviceRow(ttk.Frame):
    """Single device row with connect checkbox and window button."""

    def __init__(
        self,
        parent,
        device: DeviceInfo,
        on_connect_toggle: Callable[[str, bool], None],
        on_show_window: Callable[[str], None],
        indent: int = 0,
    ):
        super().__init__(parent)
        self.device = device
        self._on_connect_toggle = on_connect_toggle
        self._on_show_window = on_show_window

        # Layout
        self.columnconfigure(1, weight=1)

        col = 0

        # Indent for child devices (wireless under dongle)
        if indent > 0:
            ttk.Label(self, text="    " * indent + "├─ ").grid(row=0, column=col, sticky="w")
            col += 1

        # Connect checkbox
        self.connect_var = tk.BooleanVar(
            value=device.state == ConnectionState.CONNECTED
        )
        self.connect_cb = ttk.Checkbutton(
            self,
            variable=self.connect_var,
            command=self._on_connect_click,
        )
        self.connect_cb.grid(row=0, column=col, sticky="w")
        col += 1

        # Device info label
        info_text = device.display_name
        if device.battery_percent is not None:
            info_text += f" ({device.battery_percent}%)"

        self.info_label = ttk.Label(self, text=info_text, anchor="w")
        self.info_label.grid(row=0, column=col, sticky="ew", padx=(5, 10))
        col += 1

        # Status label
        status_text = device.state.value
        self.status_label = ttk.Label(self, text=status_text, width=12)
        self.status_label.grid(row=0, column=col, padx=5)
        col += 1

        # Window button
        self.window_btn = ttk.Button(
            self,
            text="Window",
            command=self._on_window_click,
            width=8,
        )
        self.window_btn.grid(row=0, column=col, padx=2)

        self._update_button_states()

    def _on_connect_click(self) -> None:
        self._on_connect_toggle(self.device.device_id, self.connect_var.get())

    def _on_window_click(self) -> None:
        self._on_show_window(self.device.device_id)

    def _update_button_states(self) -> None:
        connected = self.device.state == ConnectionState.CONNECTED
        self.window_btn.configure(state="normal" if connected else "disabled")

    def update(self, device: DeviceInfo) -> None:
        """Update with new device info."""
        self.device = device
        self.connect_var.set(device.state == ConnectionState.CONNECTED)

        info_text = device.display_name
        if device.battery_percent is not None:
            info_text += f" ({device.battery_percent}%)"
        self.info_label.configure(text=info_text)

        self.status_label.configure(text=device.state.value)
        self._update_button_states()


class XBeeDongleRow(ttk.Frame):
    """XBee dongle row with expandable child devices."""

    def __init__(
        self,
        parent,
        dongle: XBeeDongleInfo,
        on_connect_toggle: Callable[[str, bool], None],
        on_show_window: Callable[[str], None],
    ):
        super().__init__(parent)
        self.dongle = dongle
        self._on_connect_toggle = on_connect_toggle
        self._on_show_window = on_show_window
        self._child_rows: Dict[str, DeviceRow] = {}
        self._expanded = True

        self.columnconfigure(0, weight=1)

        # Header row
        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        # Expand/collapse button
        self.expand_btn = ttk.Button(
            header,
            text="▼" if self._expanded else "▶",
            width=2,
            command=self._toggle_expand,
        )
        self.expand_btn.grid(row=0, column=0)

        # Dongle info
        ttk.Label(
            header,
            text=f"XBee Dongle on {dongle.port}",
            anchor="w",
        ).grid(row=0, column=1, sticky="ew", padx=5)

        # Status
        self.status_label = ttk.Label(header, text=dongle.state.value, width=12)
        self.status_label.grid(row=0, column=2, padx=5)

        # Children container
        self.children_frame = ttk.Frame(self)
        self.children_frame.grid(row=1, column=0, sticky="ew", padx=(20, 0))

        self._rebuild_children()

    def _toggle_expand(self) -> None:
        self._expanded = not self._expanded
        self.expand_btn.configure(text="▼" if self._expanded else "▶")
        if self._expanded:
            self.children_frame.grid()
        else:
            self.children_frame.grid_remove()

    def _rebuild_children(self) -> None:
        for row in self._child_rows.values():
            row.destroy()
        self._child_rows.clear()

        for device_id, device in self.dongle.child_devices.items():
            row = DeviceRow(
                self.children_frame,
                device,
                self._on_connect_toggle,
                self._on_show_window,
                indent=1,
            )
            row.pack(fill=tk.X, pady=1)
            self._child_rows[device_id] = row

    def update(self, dongle: XBeeDongleInfo) -> None:
        self.dongle = dongle
        self.status_label.configure(text=dongle.state.value)
        self._rebuild_children()


class USBDevicesPanel(ttk.LabelFrame):
    """Panel showing all discovered USB devices."""

    def __init__(
        self,
        parent,
        on_connect_toggle: Callable[[str, bool], None],
        on_show_window: Callable[[str], None],
        on_hide: Callable[[], None],
    ):
        super().__init__(parent, text="USB Devices")
        self._on_connect_toggle = on_connect_toggle
        self._on_show_window = on_show_window
        self._on_hide = on_hide

        self._device_rows: Dict[str, DeviceRow] = {}
        self._dongle_rows: Dict[str, XBeeDongleRow] = {}

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # Header with hide button
        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew", padx=5, pady=2)
        header.columnconfigure(0, weight=1)

        ttk.Button(
            header,
            text="Hide",
            command=self._on_hide,
            width=6,
        ).grid(row=0, column=1)

        # Scrollable device list
        container = ttk.Frame(self)
        container.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(container, height=120)
        self.scrollbar = ttk.Scrollbar(
            container, orient="vertical", command=self.canvas.yview
        )
        self.scrollable_frame = ttk.Frame(self.canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")

        # Empty state label
        self.empty_label = ttk.Label(
            self.scrollable_frame,
            text="No USB devices detected. Connect a supported device.",
            foreground="gray",
        )
        self.empty_label.pack(pady=20)

    def update_devices(
        self,
        devices: List[DeviceInfo],
        dongles: List[XBeeDongleInfo],
    ) -> None:
        """Update the device list display."""
        # Clear existing
        for row in self._device_rows.values():
            row.destroy()
        for row in self._dongle_rows.values():
            row.destroy()
        self._device_rows.clear()
        self._dongle_rows.clear()

        # Show/hide empty label
        if not devices and not dongles:
            self.empty_label.pack(pady=20)
        else:
            self.empty_label.pack_forget()

        # Add device rows
        for device in devices:
            row = DeviceRow(
                self.scrollable_frame,
                device,
                self._on_connect_toggle,
                self._on_show_window,
            )
            row.pack(fill=tk.X, pady=1)
            self._device_rows[device.device_id] = row

        # Add dongle rows
        for dongle in dongles:
            row = XBeeDongleRow(
                self.scrollable_frame,
                dongle,
                self._on_connect_toggle,
                self._on_show_window,
            )
            row.pack(fill=tk.X, pady=2)
            self._dongle_rows[dongle.port] = row
```

#### 2.5-2.6 Main Window Integration

**Modify:** `rpi_logger/core/ui/main_window.py`

Update `build_ui()` to include the devices panel:

```python
def build_ui(self) -> None:
    # ... existing code ...

    # Grid layout - ADD new row for devices panel
    self.root.columnconfigure(0, weight=1)
    self.root.rowconfigure(0, weight=0)  # Header
    self.root.rowconfigure(1, weight=1)  # Main content
    self.root.rowconfigure(2, weight=0)  # USB Devices panel (NEW)
    self.root.rowconfigure(3, weight=0)  # Logger frame

    self._build_menubar()
    self._build_header()
    self._build_main_content()
    self._build_devices_panel()  # NEW
    self._build_logger_frame()  # Update row index to 3

def _build_devices_panel(self) -> None:
    """Build the USB devices panel (initially hidden)."""
    from .devices_panel import USBDevicesPanel

    self.devices_panel = USBDevicesPanel(
        self.root,
        on_connect_toggle=lambda device_id, connect: self._schedule_task(
            self.controller.on_device_connect_toggle(device_id, connect)
        ),
        on_show_window=lambda device_id: self._schedule_task(
            self.controller.on_device_show_window(device_id)
        ),
        on_hide=self._hide_devices_panel,
    )
    # Don't grid initially - shown when USB scanning enabled
    # self.devices_panel.grid(row=2, column=0, sticky="ew", padx=5, pady=5)

def _toggle_devices_panel(self) -> None:
    """Toggle USB devices panel visibility."""
    if self.show_devices_var.get():
        self.devices_panel.grid(row=2, column=0, sticky="ew", padx=5, pady=5)
    else:
        self.devices_panel.grid_remove()

def _hide_devices_panel(self) -> None:
    """Hide the USB devices panel."""
    self.show_devices_var.set(False)
    self.devices_panel.grid_remove()
```

---

### Phase 3: Module Lifecycle Changes

#### 3.1 New Commands

**Modify:** `rpi_logger/core/commands/command_protocol.py`

Add new commands:

```python
class CommandMessage:
    # ... existing methods ...

    @staticmethod
    def assign_device(device_id: str, device_type: str, port: Optional[str] = None) -> str:
        """Assign a device to the module."""
        kwargs = {
            "device_id": device_id,
            "device_type": device_type,
        }
        if port:
            kwargs["port"] = port
        return CommandMessage.create("assign_device", **kwargs)

    @staticmethod
    def unassign_device(device_id: str) -> str:
        """Remove a device from the module."""
        return CommandMessage.create("unassign_device", device_id=device_id)

    @staticmethod
    def show_window() -> str:
        """Show the module window."""
        return CommandMessage.create("show_window")

    @staticmethod
    def hide_window() -> str:
        """Hide the module window."""
        return CommandMessage.create("hide_window")


class StatusType:
    # ... existing status types ...

    # NEW status types
    WINDOW_SHOWN = "window_shown"
    WINDOW_HIDDEN = "window_hidden"
    DEVICE_ASSIGNED = "device_assigned"
    DEVICE_UNASSIGNED = "device_unassigned"
```

#### 3.2-3.4 Module Window Behavior Changes

Modules need to be updated to:
1. Handle window close by hiding instead of quitting
2. Respond to `show_window` and `hide_window` commands
3. Accept device assignment via `assign_device` command

This requires changes in each module's GUI class. Example pattern:

```python
# In module's tkinter_gui.py

def _setup_window(self) -> None:
    # Change close behavior: hide instead of quit
    self.root.protocol("WM_DELETE_WINDOW", self._on_window_close)

def _on_window_close(self) -> None:
    """Hide window instead of quitting."""
    self.root.withdraw()
    StatusMessage.send(StatusType.WINDOW_HIDDEN, {})

async def handle_show_window(self) -> None:
    """Show the module window."""
    self.root.deiconify()
    self.root.lift()
    StatusMessage.send(StatusType.WINDOW_SHOWN, {})

async def handle_hide_window(self) -> None:
    """Hide the module window."""
    self.root.withdraw()
    StatusMessage.send(StatusType.WINDOW_HIDDEN, {})
```

---

## File Changes Summary

### New Files to Create

| File | Description |
|------|-------------|
| `rpi_logger/core/devices/__init__.py` | Package init |
| `rpi_logger/core/devices/device_registry.py` | Unified device type registry |
| `rpi_logger/core/devices/usb_scanner.py` | USB port scanning service |
| `rpi_logger/core/devices/xbee_manager.py` | Unified XBee coordinator manager |
| `rpi_logger/core/devices/connection_manager.py` | Central device connection coordinator |
| `rpi_logger/core/ui/devices_panel.py` | USB devices panel widget |

### Files to Modify

| File | Changes |
|------|---------|
| `rpi_logger/core/ui/main_window.py` | Add Connections menu, devices panel, new row layout |
| `rpi_logger/core/ui/main_controller.py` | Add handlers for USB toggle, device connect, show window |
| `rpi_logger/core/commands/command_protocol.py` | Add assign_device, show_window, hide_window commands |
| `rpi_logger/core/module_process.py` | Handle new commands, window state tracking |
| `rpi_logger/core/logger_system.py` | Integration with DeviceConnectionManager |
| `rpi_logger/modules/VOG/vog_core/vog_system.py` | Remove scanning, add device assignment |
| `rpi_logger/modules/VOG/vog_core/connection_manager.py` | Remove or repurpose (no longer scans) |
| `rpi_logger/modules/VOG/vog_core/xbee_manager.py` | Remove (handled by core) |
| `rpi_logger/modules/VOG/vog_core/interfaces/gui/tkinter_gui.py` | Window hide/show, device assignment |
| `rpi_logger/modules/DRT/drt_core/drt_system.py` | Remove scanning, add device assignment |
| `rpi_logger/modules/DRT/drt_core/connection_manager.py` | Remove or repurpose |
| `rpi_logger/modules/DRT/drt_core/xbee_manager.py` | Remove (handled by core) |
| `rpi_logger/modules/DRT/drt_core/interfaces/gui/tkinter_gui.py` | Window hide/show, device assignment |

---

## Migration Strategy

### Greenfield Approach

**This is a breaking refactor.** No backward compatibility is required.

- Modules will ONLY work with centralized device discovery
- Old scanning code in modules will be deleted, not disabled
- No `--managed-devices` flag needed
- Standalone module execution will not be supported

### Configuration Changes

Add to main `config.txt`:

```ini
# USB Device Scanning
usb_scan_interval = 1.0
xbee_rediscovery_interval = 30.0
```

---

## Key Technical Details to Remember

### pyserial Port Scanning

```python
import serial.tools.list_ports

# Get all ports
ports = serial.tools.list_ports.comports()

# Each port_info has:
# - device: str (e.g., "/dev/ttyACM0")
# - vid: Optional[int] (USB Vendor ID)
# - pid: Optional[int] (USB Product ID)
# - serial_number: Optional[str]
# - description: str
```

### XBee Library Usage

```python
from digi.xbee.devices import XBeeDevice, RemoteRaw802Device

# Initialize coordinator
coordinator = XBeeDevice(port, baudrate)
coordinator.open()

# Add message callback
coordinator.add_data_received_callback(on_message)

# Network discovery
network = coordinator.get_network()
network.add_discovery_process_finished_callback(on_finished)
network.start_discovery_process()

# Get discovered devices
devices = network.get_devices()
for device in devices:
    node_id = device.get_node_id()  # e.g., "wVOG_01"
    addr = device.get_64bit_addr()
```

### Tkinter Patterns Used

```python
# Grid layout with weights
frame.columnconfigure(0, weight=1)
frame.rowconfigure(0, weight=0)  # Fixed height
frame.rowconfigure(1, weight=1)  # Expandable

# Show/hide frame
frame.grid(row=0, column=0, sticky="ew")
frame.grid_remove()  # Hide (remembers grid options)
frame.grid()  # Show again

# Window hide/show
root.withdraw()   # Hide
root.deiconify()  # Show
root.lift()       # Bring to front

# Close handler
root.protocol("WM_DELETE_WINDOW", handler)
```

---

## Design Decisions (Greenfield)

Since this is a greenfield refactor, we're making the following decisions:

### D1: XBee Baudrate
**Decision:** Use 921600 unified. Test with hardware; if wVOG doesn't work at 921600, we'll address it then.

### D2: Device-to-Module Mapping
**Decision:** Device-driven lifecycle:
- Clicking "Connect" on a device auto-starts the associated module if not running
- Module window appears when first device is connected
- Module stops when last device is disconnected (or user manually stops)
- One module instance handles all devices of its family (e.g., one VOG module for all VOG devices)

### D3: Transport Handoff
**Decision:** Option A - Module creates transport from port info.
- Main logger sends `assign_device(device_id, device_type, port, baudrate)`
- Module creates its own transport using the port path
- Main logger's role is discovery and UI coordination only

### D4: Window Lifecycle
**Decision:** Device-driven:
- Module window hidden by default until device connected
- Closing window hides it (module keeps running)
- "Window" button in device panel shows/hides module window
- Module fully stops only when all its devices disconnected OR user unchecks in Modules menu

### D5: Battery Updates
**Decision:** Include battery_percent field but leave unimplemented for now. XBee message parsing can be added later when we know the firmware format.

### D6: Callback Signatures
**Decision:** Define new unified signatures in Phase 1. Old module code will be deleted and rewritten to use new signatures in Phase 4/5.

### D7: Session Directory
**Decision:** Include in assign_device command:
```python
assign_device(device_id, device_type, port, baudrate, session_dir=None)
```
If session already active, pass current session_dir. Module handles appropriately.

### D8: Mutual Exclusion
**Decision:** Preserve behavior - USB w-device disables XBee scanning. Log to system log when this happens.

### D9: Error Reporting
**Decision:** System log + device panel error state. No status bar for now.

---

## Timeline Tracking

| Phase | Status | Notes |
|-------|--------|-------|
| **Phase 1: Core Infrastructure** | ✅ COMPLETE | |
| 1.1 Device Registry | ✅ Complete | `rpi_logger/core/devices/device_registry.py` |
| 1.2 USB Scanner | ✅ Complete | `rpi_logger/core/devices/usb_scanner.py` |
| 1.3 XBee Manager | ✅ Complete | `rpi_logger/core/devices/xbee_manager.py` |
| 1.4 Connection Manager | ✅ Complete | `rpi_logger/core/devices/connection_manager.py` |
| 1.5 Device-Module Mapping | ✅ Complete | In device_registry.py |
| **Phase 2: UI Changes** | ✅ COMPLETE | |
| 2.1 Connections Menu | ✅ Complete | In main_window.py |
| 2.2 Devices Panel Widget | ✅ Complete | `rpi_logger/core/ui/devices_panel.py` |
| 2.3 Device Row Widget | ✅ Complete | In devices_panel.py |
| 2.4 XBee Dongle Row | ✅ Complete | In devices_panel.py |
| 2.5 Main Window Integration | ✅ Complete | Updated main_window.py grid layout |
| 2.6 View Menu Toggle | ✅ Complete | In main_window.py |
| **Phase 3: Module Lifecycle** | ✅ COMPLETE | |
| 3.1 New Commands | ✅ Complete | command_protocol.py, base_handler.py |
| 3.2 Window Close Behavior | ✅ Complete | In base_handler.py |
| 3.3 Module State Machine | ✅ Complete | Modules wait for device assignments |
| 3.4 Device Disconnect Handling | ✅ Complete | unassign_device in systems |
| **Phase 4: VOG Refactor** | ✅ COMPLETE | |
| 4.1 Remove USB Scanning | ✅ Complete | vog_system.py updated |
| 4.2 Remove XBee Manager | ✅ Complete | No longer used in VOG |
| 4.3 Device Assignment Handler | ✅ Complete | assign_device/unassign_device |
| 4.4 Pre-connected Device Support | ✅ Complete | Creates transport from port |
| 4.5 Window Commands | ✅ Complete | Handled by base_handler.py |
| **Phase 5: DRT Refactor** | ✅ COMPLETE | |
| 5.1 Remove USB Scanning | ✅ Complete | drt_system.py updated |
| 5.2 Remove XBee Manager | ✅ Complete | No longer used in DRT |
| 5.3 Device Assignment Handler | ✅ Complete | assign_device/unassign_device |
| 5.4 Pre-connected Device Support | ✅ Complete | Creates transport from port |
| 5.5 Window Commands | ✅ Complete | Handled by base_handler.py |
| **Phase 6: Integration & Testing** | 🔲 NOT STARTED | Requires hardware |
| 6.1 Test sVOG | 🔲 Not Started | |
| 6.2 Test sDRT | 🔲 Not Started | |
| 6.3 Test XBee + wVOG | 🔲 Not Started | |
| 6.4 Test XBee + wDRT | 🔲 Not Started | |
| 6.5 Hot-plug Testing | 🔲 Not Started | |
| 6.6 Recording Session Test | 🔲 Not Started | |
| 6.7 Documentation Update | 🔲 Not Started | |

---

---

# VOG Config Window Refactoring Plan

## Problem Summary

The VOG config window fails to populate with device configuration values. The root causes are:

1. **Placeholder System Object** - `_SystemPlaceholder.get_device_handler()` always returns `None`
2. **Race Condition** - Runtime binding happens after GUI creation, but config window may be opened before binding completes
3. **Broken Async Pattern** - Config window bypasses async layer with direct serial access
4. **Hard-coded Timing** - 2-second delay for UI update is arbitrary and unreliable
5. **No Event-Driven Updates** - Config responses aren't propagated to the config window

## Architecture Overview

```
Current Flow (Broken):
User clicks "Configure" → VOGConfigWindow created → system.get_device_handler() → None → Error

Desired Flow:
User clicks "Configure" → VOGConfigWindow created → runtime.get_device_handler() → VOGHandler
  → Request config via handler → Handler read loop processes response → Event dispatched
  → Config window receives event → UI updated with values
```

## Refactoring Plan

### Phase 1: Fix Runtime Binding (Critical - Must Fix First)

**Goal:** Ensure `self.system` in VOGTkinterGUI is always the real runtime when config window opens.

**Files:** `view.py`

**Changes:**

1. **Add `_runtime_bound` flag to VOGTkinterGUI**
   ```python
   def __init__(self, ...):
       self._runtime_bound = False
       self.system = _SystemPlaceholder(args)
   ```

2. **Update `bind_runtime()` to set flag**
   ```python
   def bind_runtime(self, runtime):
       self._runtime = runtime
       self._runtime_bound = True
       if self.gui:
           self.gui.system = runtime
   ```

3. **Disable "Configure Unit" button until runtime bound**
   - In `_create_device_tab()`, initially disable the button
   - Enable when `_runtime_bound` becomes True
   - Or: Check in `_on_configure_clicked()` and show message if not bound

4. **Guard `_on_configure_clicked()`**
   ```python
   def _on_configure_clicked(self, port: str):
       if not self._runtime_bound:
           messagebox.showwarning("Not Ready", "System not initialized. Please wait.")
           return
       # ... rest of method
   ```

### Phase 2: Refactor Config Window to Use Event-Driven Updates

**Goal:** Replace hard-coded 2-second delay with event-driven config updates.

**Files:** `config_window.py`, `vog_handler.py`

**Changes:**

1. **Add config update callback to VOGHandler**
   ```python
   class VOGHandler:
       def __init__(self, ...):
           self._config_callback: Optional[Callable[[Dict[str, Any]], None]] = None

       def set_config_callback(self, callback: Callable[[Dict[str, Any]], None]):
           self._config_callback = callback

       def clear_config_callback(self):
           self._config_callback = None
   ```

2. **Call callback when config response processed**
   ```python
   # In _process_response(), after updating self._config:
   elif parsed.response_type == ResponseType.CONFIG:
       self.protocol.update_config_from_response(parsed, self._config)
       if self._config_callback:
           self._config_callback(dict(self._config))
   ```

3. **Refactor config_window.py to register callback**
   ```python
   def _load_config(self):
       handler = self.system.get_device_handler(self.port)
       if not handler:
           messagebox.showerror("Error", f"Device not connected on {self.port}")
           return

       # Register for config updates
       handler.set_config_callback(self._on_config_received)

       # Show any cached config immediately
       cached = handler.get_config()
       if cached:
           self._update_ui_from_config(cached)

       # Request fresh config via async bridge (proper async)
       if self.async_bridge:
           self.async_bridge.run_coroutine(handler.get_device_config())

   def _on_config_received(self, config: Dict[str, Any]):
       """Called by handler when config response arrives."""
       # Schedule UI update on main thread
       self.dialog.after(0, lambda: self._safe_update_ui(config))
   ```

4. **Clean up callback on dialog close**
   ```python
   def __init__(self, ...):
       # ... existing code ...
       self.dialog.protocol("WM_DELETE_WINDOW", self._on_close)

   def _on_close(self):
       handler = self.system.get_device_handler(self.port)
       if handler:
           handler.clear_config_callback()
       self.dialog.destroy()
   ```

### Phase 3: Remove Direct Serial Access

**Goal:** Use proper async transport layer instead of bypassing it.

**Files:** `config_window.py`

**Changes:**

1. **Delete `_send_config_request_sync()` method entirely**

2. **Use async bridge for all device communication**
   ```python
   def _load_config(self):
       handler = self.system.get_device_handler(self.port)
       if not handler:
           messagebox.showerror("Error", f"Device not connected on {self.port}")
           return

       handler.set_config_callback(self._on_config_received)

       cached = handler.get_config()
       if cached:
           self._update_ui_from_config(cached)

       # Request config through proper async channel
       if self.async_bridge:
           self.async_bridge.run_coroutine(handler.get_device_config())
       else:
           self.logger.warning("No async bridge - cannot request device config")
   ```

### Phase 4: Remove Debug Logging Noise

**Goal:** Clean up temporary debug code.

**Files:** `config_window.py`

**Changes:**

1. Remove all `with open("/tmp/vog_config_debug.log", ...)` blocks
2. Keep proper `self.logger.debug()` calls for actual debugging needs

### Phase 5: Add Loading State Indicator

**Goal:** Provide visual feedback while waiting for config response.

**Files:** `config_window.py`

**Changes:**

1. **Add loading state UI**
   ```python
   def _load_config(self):
       self._show_loading(True)
       # ... request config ...

   def _on_config_received(self, config: Dict[str, Any]):
       self._show_loading(False)
       self.dialog.after(0, lambda: self._safe_update_ui(config))

   def _show_loading(self, loading: bool):
       """Show/hide loading indicator."""
       if loading:
           self.status_label.config(text="Loading configuration...")
       else:
           self.status_label.config(text="")
   ```

2. **Add timeout for slow responses**
   ```python
   def _load_config(self):
       # ... existing code ...
       # Schedule timeout check
       self._config_timeout_id = self.dialog.after(5000, self._on_config_timeout)

   def _on_config_received(self, config: Dict[str, Any]):
       # Cancel timeout
       if self._config_timeout_id:
           self.dialog.after_cancel(self._config_timeout_id)
           self._config_timeout_id = None
       # ... update UI ...

   def _on_config_timeout(self):
       self._show_loading(False)
       self.logger.warning("Config request timed out")
       # Show cached values with warning
   ```

### Phase 6: Input Validation

**Goal:** Validate config values before sending to device.

**Files:** `config_window.py`

**Changes:**

1. **Add validation for numeric fields**
   ```python
   def _validate_numeric(self, value: str, field_name: str, min_val: int = 0, max_val: int = None) -> Optional[int]:
       try:
           val = int(value)
           if val < min_val:
               raise ValueError(f"{field_name} must be at least {min_val}")
           if max_val and val > max_val:
               raise ValueError(f"{field_name} must be at most {max_val}")
           return val
       except ValueError as e:
           messagebox.showerror("Invalid Value", str(e), parent=self.dialog)
           return None
   ```

2. **Validate before apply**
   ```python
   async def _apply_svog_config(self, handler):
       max_open = self.config_vars['max_open'].get()
       if max_open:
           validated = self._validate_numeric(max_open, "Max Open", 0, 60000)
           if validated is None:
               return  # Validation failed
           await handler.set_config_value('max_open', str(validated))
   ```

## Implementation Order

1. **Phase 1** - Fix runtime binding (unblocks everything)
2. **Phase 4** - Remove debug logging (quick cleanup)
3. **Phase 3** - Remove direct serial access (simplifies code)
4. **Phase 2** - Event-driven updates (proper solution)
5. **Phase 5** - Loading state (UX improvement)
6. **Phase 6** - Input validation (robustness)

## Testing Checklist

- [ ] Config window opens without error
- [ ] Fields populate with device values
- [ ] Refresh button reloads values
- [ ] Apply button sends values to device
- [ ] Changes persist after dialog close/reopen
- [ ] Works for sVOG devices
- [ ] Works for wVOG devices
- [ ] Handles device disconnection gracefully
- [ ] Shows appropriate error when device not connected

## Files to Modify

| File | Changes |
|------|---------|
| `view.py` | Add runtime bound check, guard configure button |
| `config_window.py` | Event-driven updates, remove direct serial, add validation |
| `vog_handler.py` | Add config callback mechanism |

## Estimated Impact

- **Lines removed:** ~50 (debug logging, sync serial code)
- **Lines added:** ~80 (callback mechanism, validation, loading state)
- **Net change:** +30 lines with much cleaner architecture

---

## Known TODOs in Implementation

The following items are marked as TODO in the code and need to be addressed during testing:

1. **Wireless device assignment** - `vog_system.py:119-121` and `drt_system.py:119-121` return False with "not yet implemented" for wireless devices
2. **Battery update parsing** - Field exists in DeviceInfo but XBee message parsing not implemented
3. **XBee baudrate testing** - Using 921600; needs hardware verification for wVOG compatibility
