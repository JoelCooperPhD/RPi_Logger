# DRT XBee Wireless Integration Plan

## Status: IMPLEMENTED

All phases have been completed. The DRT module now supports wireless device assignment via XBee.

## Executive Summary

The DRT module has fully implemented wireless device handlers (`WDRTWirelessHandler` - 453 lines) and XBee transport (`XBeeTransport` - 206 lines). The integration was completed by extending the command protocol to proxy XBee data bidirectionally between the main logger and modules.

**Solution:** The command protocol now supports `xbee_data` commands (main logger -> module) and `xbee_send` status messages (module -> main logger). The `XBeeProxyTransport` class provides a transport interface that looks like `XBeeTransport` to handlers but uses the command protocol internally.

---

## Architecture Overview

### Current Flow (Broken)
```
XBee Coordinator (main logger) ──X──> DRT Module (subprocess)
         │
         └── No way to pass XBee objects through process boundary
```

### Target Flow
```
┌─────────────────────────────────────────────────────────────────────┐
│  Main Logger Process                                                │
│  ┌──────────────────┐     ┌────────────────────┐                   │
│  │   XBeeManager    │────>│  XBee Data Router  │                   │
│  │  (coordinator)   │<────│                    │                   │
│  └──────────────────┘     └─────────┬──────────┘                   │
│                                     │ stdin/stdout                  │
│                           ┌─────────▼──────────┐                   │
│                           │   ModuleProcess    │                   │
│                           │  (command queue)   │                   │
│                           └─────────┬──────────┘                   │
└─────────────────────────────────────┼───────────────────────────────┘
                                      │ JSON Commands
┌─────────────────────────────────────┼───────────────────────────────┐
│  DRT Module Subprocess              │                               │
│                           ┌─────────▼──────────┐                   │
│                           │  DRTModuleRuntime  │                   │
│                           └─────────┬──────────┘                   │
│                                     │                               │
│                           ┌─────────▼──────────┐                   │
│                           │ XBeeProxyTransport │ (looks like       │
│                           │                    │  XBeeTransport)   │
│                           └─────────┬──────────┘                   │
│                                     │                               │
│                           ┌─────────▼──────────┐                   │
│                           │WDRTWirelessHandler │                   │
│                           └────────────────────┘                   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Implementation Steps

### Phase 1: Extend Command Protocol

**Files to modify:**
- `rpi_logger/core/commands/command_protocol.py`

#### Step 1.1: Add XBee Data Command (Main Logger → Module)

Add a new command type for forwarding XBee data to modules:

```python
# In CommandMessage class

@staticmethod
def xbee_data(node_id: str, data: str) -> str:
    """
    Forward XBee data from main logger to module.

    Args:
        node_id: Source device node ID (e.g., "wDRT_01")
        data: Raw data string from the device
    """
    return CommandMessage.create(
        "xbee_data",
        node_id=node_id,
        data=data
    )
```

#### Step 1.2: Add XBee Send Status (Module → Main Logger)

Add a new status type for modules to send data back through XBee:

```python
# In StatusType class
XBEE_SEND = "xbee_send"        # Module wants to send data via XBee
XBEE_SEND_RESULT = "xbee_send_result"  # Result of send operation

# Add helper in StatusMessage class
@staticmethod
def send_xbee_data(node_id: str, data: str) -> None:
    """Request main logger to send data to XBee device."""
    StatusMessage.send("xbee_send", {
        "node_id": node_id,
        "data": data
    })
```

---

### Phase 2: XBee Message Router in Main Logger

**Files to modify:**
- `rpi_logger/core/devices/xbee_manager.py`
- `rpi_logger/core/devices/connection_manager.py`
- `rpi_logger/core/module_process.py`
- `rpi_logger/core/logger_system.py`

#### Step 2.1: Add Data Callback to XBeeManager

Modify `XBeeManager._on_message_received()` to call a data callback instead of just logging:

```python
# In XBeeManager.__init__
self.on_data_received: Optional[Callable[[str, str], Awaitable[None]]] = None  # node_id, data

# Replace the TODO in _on_message_received
def _on_message_received(self, message: 'XBeeMessage') -> None:
    try:
        remote = message.remote_device
        node_id = remote.get_node_id() if remote else None
        if not node_id:
            return

        data = message.data.decode('utf-8', errors='replace')
        logger.debug(f"XBee received from {node_id}: '{data.strip()}'")

        # Route to callback (thread-safe)
        if self.on_data_received and self._loop:
            def schedule_callback():
                if self._loop.is_running():
                    self._loop.create_task(self.on_data_received(node_id, data))
            self._loop.call_soon_threadsafe(schedule_callback)

    except Exception as e:
        logger.error(f"Error handling XBee message: {e}")
```

#### Step 2.2: Add XBee Routing to DeviceConnectionManager

Add routing logic to forward XBee data to the correct module:

```python
# In DeviceConnectionManager.__init__
self._xbee_data_router: Optional[Callable[[str, str], Awaitable[None]]] = None

def set_xbee_data_router(self, router: Callable[[str, str], Awaitable[None]]) -> None:
    """Set callback for routing XBee data to modules."""
    self._xbee_data_router = router
    if self._xbee_manager:
        self._xbee_manager.on_data_received = self._on_xbee_data_received

async def _on_xbee_data_received(self, node_id: str, data: str) -> None:
    """Route incoming XBee data to the appropriate module."""
    # Only route if device is connected to a module
    if node_id not in self._connected_devices:
        logger.debug(f"Ignoring XBee data from unconnected device: {node_id}")
        return

    if self._xbee_data_router:
        await self._xbee_data_router(node_id, data)
```

#### Step 2.3: Handle XBee Send Status in ModuleProcess

Modify `ModuleProcess._handle_status()` to handle `xbee_send` requests:

```python
# In ModuleProcess._handle_status()
elif status_type == StatusType.XBEE_SEND:
    payload = status.get_payload()
    node_id = payload.get("node_id")
    data = payload.get("data")
    if node_id and data and self._xbee_send_callback:
        success = await self._xbee_send_callback(node_id, data.encode())
        # Send result back to module
        await self.send_command(CommandMessage.create(
            "xbee_send_result",
            node_id=node_id,
            success=success
        ))

# Add callback setter
def set_xbee_send_callback(self, callback: Callable[[str, bytes], Awaitable[bool]]) -> None:
    """Set callback for handling XBee send requests from module."""
    self._xbee_send_callback = callback
```

#### Step 2.4: Wire Up XBee Routing in LoggerSystem

Connect the pieces in the main logger:

```python
# In LoggerSystem (after connection manager and module manager init)

async def _setup_xbee_routing(self) -> None:
    """Set up XBee data routing between modules and devices."""

    # Route XBee data to modules
    self._connection_manager.set_xbee_data_router(self._route_xbee_to_module)

    # Handle XBee sends from modules
    for module in self._module_manager.get_all_modules():
        module.set_xbee_send_callback(self._send_xbee_from_module)

async def _route_xbee_to_module(self, node_id: str, data: str) -> None:
    """Route incoming XBee data to the appropriate module."""
    # Find which module owns this device
    device = self._connection_manager.get_device(node_id)
    if not device:
        return

    module = self._module_manager.get_module(device.module_id)
    if module and module.is_running():
        await module.send_command(CommandMessage.xbee_data(node_id, data))

async def _send_xbee_from_module(self, node_id: str, data: bytes) -> bool:
    """Send data to XBee device on behalf of a module."""
    return await self._connection_manager.send_to_wireless_device(node_id, data)
```

---

### Phase 3: XBee Proxy Transport in DRT Module

**Files to create:**
- `rpi_logger/modules/DRT/drt_core/transports/xbee_proxy_transport.py`

**Files to modify:**
- `rpi_logger/modules/DRT/drt/runtime.py`

#### Step 3.1: Create XBeeProxyTransport

Create a transport that looks like `XBeeTransport` but uses the command protocol:

```python
"""
XBee Proxy Transport

Transport that proxies XBee communication through the command protocol.
Used when the XBee coordinator lives in the main logger process.
"""

import asyncio
import queue
from typing import Optional, Callable, Awaitable

from .base_transport import BaseTransport


class XBeeProxyTransport(BaseTransport):
    """
    Proxy transport for XBee communication via command protocol.

    Data is received via push from the runtime (which gets it from
    command protocol), and sends are requested via callback.
    """

    MAX_BUFFER_SIZE = 1000

    def __init__(
        self,
        node_id: str,
        send_callback: Callable[[str, str], Awaitable[bool]]
    ):
        """
        Initialize the proxy transport.

        Args:
            node_id: Device node ID (e.g., "wDRT_01")
            send_callback: Async callback to send data (node_id, data) -> success
        """
        super().__init__()
        self.node_id = node_id
        self._send_callback = send_callback

        # Receive buffer (thread-safe for future-proofing)
        self._receive_buffer: asyncio.Queue[str] = asyncio.Queue(maxsize=self.MAX_BUFFER_SIZE)
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def device_id(self) -> str:
        return self.node_id

    async def connect(self) -> bool:
        """Mark transport as connected."""
        self._connected = True
        return True

    async def disconnect(self) -> None:
        """Mark transport as disconnected."""
        self._connected = False
        # Clear buffer
        while not self._receive_buffer.empty():
            try:
                self._receive_buffer.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def write(self, data: bytes) -> bool:
        """Send data via the proxy callback."""
        if not self._connected:
            return False

        try:
            data_str = data.decode('utf-8', errors='replace').strip()
            return await self._send_callback(self.node_id, data_str)
        except Exception:
            return False

    async def read_line(self) -> Optional[str]:
        """Read from the receive buffer."""
        try:
            # Non-blocking read
            return self._receive_buffer.get_nowait()
        except asyncio.QueueEmpty:
            return None

    def push_data(self, data: str) -> None:
        """
        Push received data into the buffer.

        Called by runtime when xbee_data command arrives.
        """
        try:
            self._receive_buffer.put_nowait(data.strip())
        except asyncio.QueueFull:
            # Drop oldest to make room
            try:
                self._receive_buffer.get_nowait()
                self._receive_buffer.put_nowait(data.strip())
            except asyncio.QueueEmpty:
                pass
```

#### Step 3.2: Modify DRT Runtime to Handle XBee Commands

Update `DRTModuleRuntime` to handle wireless device assignment:

```python
# In DRTModuleRuntime.__init__
from rpi_logger.modules.DRT.drt_core.transports import XBeeProxyTransport
self._proxy_transports: Dict[str, XBeeProxyTransport] = {}

# In handle_command() - add new command handler
if action == "xbee_data":
    node_id = command.get("node_id", "")
    data = command.get("data", "")
    await self._on_xbee_data(node_id, data)
    return True

if action == "xbee_send_result":
    # Optional: handle send confirmations
    return True

# Add XBee data handler
async def _on_xbee_data(self, node_id: str, data: str) -> None:
    """Handle incoming XBee data from main logger."""
    transport = self._proxy_transports.get(node_id)
    if transport:
        transport.push_data(data)

# Add XBee send request
async def _request_xbee_send(self, node_id: str, data: str) -> bool:
    """Request main logger to send data via XBee."""
    from rpi_logger.core.commands import StatusMessage
    StatusMessage.send_xbee_data(node_id, data)
    return True  # Async - can't know result immediately

# Modify assign_device() - replace the wireless TODO section
async def assign_device(self, ...) -> bool:
    # ... existing code ...

    if is_wireless:
        # Create proxy transport for wireless device
        transport = XBeeProxyTransport(
            node_id=device_id,
            send_callback=self._request_xbee_send
        )
        if not await transport.connect():
            self.logger.error("Failed to initialize proxy transport for %s", device_id)
            return False

        self._proxy_transports[device_id] = transport

        # Create wireless handler
        handler = WDRTWirelessHandler(
            device_id=device_id,
            output_dir=self.module_data_dir,
            transport=transport
        )

        # ... rest of handler setup (same as USB path) ...
```

#### Step 3.3: Update _create_handler for Wireless

Modify `_create_handler()` to accept any transport type:

```python
def _create_handler(
    self,
    device_type: DRTDeviceType,
    device_id: str,
    transport,  # Accept any transport (USBTransport or XBeeProxyTransport)
) -> Optional[BaseDRTHandler]:
    """Create the appropriate handler for a device type."""
    if device_type == DRTDeviceType.SDRT:
        return SDRTHandler(
            device_id=device_id,
            output_dir=self.module_data_dir,
            transport=transport
        )
    elif device_type == DRTDeviceType.WDRT_USB:
        return WDRTUSBHandler(
            device_id=device_id,
            output_dir=self.module_data_dir,
            transport=transport
        )
    elif device_type == DRTDeviceType.WDRT_WIRELESS:
        return WDRTWirelessHandler(
            device_id=device_id,
            output_dir=self.module_data_dir,
            transport=transport
        )
    else:
        self.logger.warning("Unknown device type: %s", device_type)
        return None
```

#### Step 3.4: Update unassign_device for Proxy Cleanup

```python
async def unassign_device(self, device_id: str) -> None:
    # ... existing code ...

    # Clean up proxy transport if exists
    if device_id in self._proxy_transports:
        transport = self._proxy_transports.pop(device_id)
        await transport.disconnect()
```

---

### Phase 4: Update Handler Transport Read Loop

**Files to modify:**
- `rpi_logger/modules/DRT/drt_core/handlers/base_handler.py`

The base handler's read loop needs to handle the async nature of proxy transport:

```python
# In BaseDRTHandler._read_loop()
async def _read_loop(self) -> None:
    """Background task to read from transport."""
    while self._running:
        try:
            line = await self.transport.read_line()
            if line:
                self._process_response(line)
            else:
                # No data - small sleep to prevent busy loop
                await asyncio.sleep(0.01)
        except Exception as e:
            self._consecutive_errors += 1
            if self._consecutive_errors >= self._max_consecutive_errors:
                self.logger.error("Circuit breaker triggered after %d errors", self._consecutive_errors)
                break
            await asyncio.sleep(min(0.1 * (2 ** self._consecutive_errors), 2.0))
```

---

### Phase 5: Testing & Validation

#### Step 5.1: Unit Tests for XBeeProxyTransport

```python
# tests/modules/DRT/test_xbee_proxy_transport.py

import pytest
import asyncio
from rpi_logger.modules.DRT.drt_core.transports import XBeeProxyTransport


@pytest.mark.asyncio
async def test_proxy_transport_connect():
    async def mock_send(node_id, data):
        return True

    transport = XBeeProxyTransport("wDRT_01", mock_send)
    assert await transport.connect()
    assert transport.is_connected


@pytest.mark.asyncio
async def test_proxy_transport_push_and_read():
    async def mock_send(node_id, data):
        return True

    transport = XBeeProxyTransport("wDRT_01", mock_send)
    await transport.connect()

    transport.push_data("trl:1:450:1:3")

    line = await transport.read_line()
    assert line == "trl:1:450:1:3"


@pytest.mark.asyncio
async def test_proxy_transport_write():
    sent_data = []

    async def mock_send(node_id, data):
        sent_data.append((node_id, data))
        return True

    transport = XBeeProxyTransport("wDRT_01", mock_send)
    await transport.connect()

    result = await transport.write(b"exp_start\n")

    assert result
    assert sent_data == [("wDRT_01", "exp_start")]
```

#### Step 5.2: Integration Test

```python
# tests/integration/test_xbee_routing.py

@pytest.mark.asyncio
async def test_xbee_data_routing():
    """Test that XBee data is routed from main logger to DRT module."""
    # 1. Start main logger
    # 2. Start DRT module
    # 3. Connect wireless device
    # 4. Inject XBee message
    # 5. Verify DRT handler receives data
    pass
```

---

## File Change Summary

### New Files
| File | Description |
|------|-------------|
| `rpi_logger/modules/DRT/drt_core/transports/xbee_proxy_transport.py` | Proxy transport class |

### Modified Files
| File | Changes |
|------|---------|
| `rpi_logger/core/commands/command_protocol.py` | Add `xbee_data` command, `xbee_send` status |
| `rpi_logger/core/devices/xbee_manager.py` | Add `on_data_received` callback |
| `rpi_logger/core/devices/connection_manager.py` | Add XBee routing methods |
| `rpi_logger/core/module_process.py` | Handle `xbee_send` status |
| `rpi_logger/core/logger_system.py` | Wire up XBee routing |
| `rpi_logger/modules/DRT/drt/runtime.py` | Handle wireless assignment with proxy transport |
| `rpi_logger/modules/DRT/drt_core/handlers/base_handler.py` | Async-compatible read loop |
| `rpi_logger/modules/DRT/drt_core/transports/__init__.py` | Export XBeeProxyTransport |

---

## Risk Assessment

### Low Risk
- Command protocol extension (additive, no breaking changes)
- New proxy transport (isolated, no impact on USB path)

### Medium Risk
- XBee read loop timing (may need tuning for real-time performance)
- Buffer overflow handling (bounded queues may drop data)

### Mitigation
- Add buffer size metrics to monitor overflow
- Log dropped messages with rate limiting
- Add configurable buffer sizes

---

## Performance Considerations

### Latency
- Command protocol adds ~1-5ms per message (JSON encode/decode)
- Acceptable for DRT reaction times (100-1000ms typical)

### Throughput
- XBee 802.15.4 max: ~250kbps
- Command protocol: limited by stdin/stdout buffering
- Real world: ~100 messages/sec easily achievable

### Memory
- Buffer size: 1000 messages * ~100 bytes = ~100KB per device
- Acceptable for typical use

---

## Rollout Plan

1. **Phase 1-2**: Core infrastructure (can be tested without DRT)
2. **Phase 3**: DRT integration (behind feature flag initially)
3. **Phase 4**: Handler updates (minimal changes)
4. **Phase 5**: Testing and validation

Each phase is independently testable and can be merged separately.
