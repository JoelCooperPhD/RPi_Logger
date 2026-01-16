# Master Device Architecture Plan

## Executive Summary

This document outlines the architectural refactoring to introduce a **Master Device Registry** that treats physical devices as first-class entities with multiple capabilities, rather than treating each interface (video, audio) as separate devices.

## Implementation Status

| Phase | Status | Notes |
|-------|--------|-------|
| Phase 1: Core Infrastructure | Complete | `master_device.py`, `master_registry.py`, `physical_id.py` implemented |
| Phase 2: Scanner Integration | In Progress | Scanners exist, integration ongoing |
| Phase 3: Module Updates | In Progress | Partial capability support |
| Phase 4: Cleanup | Not Started | Legacy family-based code remains |

*Last updated: 2026-01-15*

---

## The Problem

A USB webcam is one physical device with two interfaces:
- Video interface (`/dev/video0`)
- Audio interface (ALSA/sounddevice)

The current architecture treats these as separate, unrelated devices:
- `USBCameraScanner` discovers the video interface
- `AudioScanner` discovers the audio interface
- No awareness that they belong to the same physical device

**Result**: Users cannot record audio from their webcam's built-in microphone via the camera module, and webcam mics pollute the standalone Audio device list.

---

## The Solution

Introduce a **Master Device Registry** that:
1. Tracks **physical devices** (identified by USB bus path)
2. Aggregates **capabilities** (video, audio, serial) onto physical devices
3. Allows modules to query "devices with video" or "audio-only devices"
4. Enables the Cameras module to optionally capture audio from webcams
5. Filters webcam audio out of the Audio module's device list

---

## Core Concepts

### Physical Device vs Interface

| Concept | Example | Identifier |
|---------|---------|------------|
| Physical Device | Logitech C920 webcam | USB bus path "1-2" |
| Video Interface | /dev/video0 | Device path |
| Audio Interface | ALSA card 3 | sounddevice index |

A physical device can have multiple interfaces. The USB bus path is stable and shared by all interfaces of the same physical device.

### Capability Model

Instead of "device families" (CAMERA_USB, AUDIO), we track "capabilities" - what a device can do:

| Capability | Description | Example Devices |
|------------|-------------|-----------------|
| VIDEO_USB | USB video capture | Webcams, capture cards |
| VIDEO_CSI | CSI camera interface | Raspberry Pi cameras |
| AUDIO_INPUT | Audio recording | Microphones, webcam mics, audio interfaces |
| SERIAL_DRT | DRT serial protocol | DRT hardware |
| SERIAL_VOG | VOG serial protocol | VOG hardware |
| NETWORK | Network connectivity | Pupil Labs Neon |

A webcam with built-in mic has both VIDEO_USB and AUDIO_INPUT capabilities.

### Device Classification

| Device Type | Has Video | Has Audio | Where It Appears |
|-------------|-----------|-----------|------------------|
| Webcam with mic | Yes | Yes | Cameras panel (with audio checkbox) |
| Webcam without mic | Yes | No | Cameras panel |
| Standalone USB mic | No | Yes | Audio panel |
| CSI camera | Yes | No | Cameras panel |
| Audio interface | No | Yes | Audio panel |

---

## Architecture Overview

### New Components

| Component | Purpose |
|-----------|---------|
| MasterDevice | Represents a physical device with its capabilities |
| MasterDeviceRegistry | Single source of truth for all physical devices |
| USBPhysicalIdResolver | Links interfaces by USB bus path |

### Data Flow: Current vs New

**Current Flow:**
```
Video Scanner → DeviceFamily.CAMERA_USB → UI shows camera
Audio Scanner → DeviceFamily.AUDIO → UI shows mic (same device, unaware!)
```

**New Flow:**
```
Video Scanner → finds USB path "1-2" → registers VIDEO_USB capability
                                    → probes for audio sibling
                                    → registers AUDIO_INPUT capability

Audio Scanner → finds USB path "1-2" → checks registry
                                    → already registered as webcam audio
                                    → SKIP (don't show in Audio panel)

UI → queries "video devices" → shows webcam with audio checkbox
UI → queries "audio-only devices" → shows only standalone mics
```

---

## Affected Components

### Core Device System

| Component | Change |
|-----------|--------|
| Device Registry | Deprecate family-based model, add capability mapping |
| Device System | Integrate MasterDeviceRegistry |
| Lifecycle Manager | Query registry for capability-based device info |
| Events | Add capability-based event types |
| Scanner Adapter | Simplify - direct registry integration |
| Selection Model | Add capability-based queries |

### Scanners

| Scanner | Change |
|---------|--------|
| USB Camera Scanner | Resolve physical ID, probe for audio siblings |
| Audio Scanner | Resolve physical ID, check if webcam-associated |
| CSI Camera Scanner | Minor - use capability model |

### Modules

| Module | Change |
|--------|--------|
| Cameras | Add optional audio recording from webcam mic |
| Audio | Receives filtered list (no webcam mics) |
| Others (DRT, VOG, etc.) | Minimal - continue using VID/PID identification |

### UI

| Component | Change |
|-----------|--------|
| Device Panel | Show audio checkbox on webcams with mic |
| Audio Panel | Only show standalone audio devices |

---

## User Experience

### Cameras Panel (New)
- Webcams with built-in mic show an "audio available" indicator
- Checkbox: "Record audio from this camera"
- When enabled, audio is recorded alongside video

### Audio Panel (New)
- Only shows standalone audio devices (USB mics, audio interfaces)
- Webcam mics are NOT shown here
- Informational note: "Webcam microphones are managed in the Cameras panel"

---

## Implementation Phases

### Phase 1: Core Infrastructure
- Create MasterDevice and capability data models
- Create MasterDeviceRegistry
- Create USBPhysicalIdResolver for Linux
- No breaking changes - runs alongside existing system

### Phase 2: Scanner Integration
- Update USB Camera Scanner to probe audio siblings
- Update Audio Scanner to check webcam association
- Wire scanners to MasterDeviceRegistry

### Phase 3: Module Updates
- Add audio recording capability to Cameras module
- Update Audio module to receive filtered device list
- Update UI for audio checkbox on webcams

### Phase 4: Cleanup
- Remove deprecated family-based code
- Run dead code audit
- Update tests

---

## Technical Considerations

### USB Bus Path Resolution
On Linux, both video and audio interfaces of a USB device share the same sysfs path. The existing Linux camera backend already extracts this path - we extend this to link interfaces.

### Timing and Hot-plug
- Video and audio may be discovered at slightly different times
- Registry handles incremental capability addition
- Hot-plug events update registry and notify observers

### Cross-Platform
- Linux: sysfs-based resolution (primary target)
- macOS/Windows: May need alternative approaches or heuristics
- Graceful degradation if physical ID cannot be resolved

### Backwards Compatibility
- Existing VID/PID serial devices (DRT, VOG) continue working unchanged
- Family-based code can be deprecated gradually
- Capability model is additive, not disruptive

---

## Success Criteria

1. Webcam audio appears only in camera settings (not in Audio panel)
2. Standalone mics appear only in Audio panel
3. Recording from webcam mic works correctly and is synchronized with video
4. No regression in existing device discovery or module functionality
5. Clean removal of legacy family-based code

---

## Files Inventory

### New Files (3)
- `master_device.py` - Data models
- `master_registry.py` - Registry implementation
- `physical_id.py` - USB path resolution

### High-Impact Changes (4)
- `device_registry.py` - Deprecate families, add capability mapping
- `device_system.py` - Integrate registry
- `lifecycle.py` - Capability-based device info
- `Cameras/bridge.py` - Audio recording capability

### Medium-Impact Changes (6)
- `events.py` - Capability events
- `scanner_adapter.py` - Simplify
- `audio_scanner.py` - Physical ID resolution
- `usb_camera_scanner.py` - Audio sibling probing
- `device_controller.py` - UI updates
- `command_protocol.py` - Webcam audio parameters

### Low-Impact Changes (5+)
- `selection.py`, `catalog.py`, `logger_system.py`, module configs

### Dead Code Removal
- DeviceFamily enum (partial)
- Family-based queries
- Redundant adapter logic

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Physical ID resolution fails | Fall back to treating as separate devices |
| Audio/video timing mismatch | Registry handles incremental updates |
| Breaking existing functionality | Phased rollout, compatibility layer |
| Cross-platform differences | Platform-specific resolvers, graceful degradation |
