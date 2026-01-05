# Master Device Architecture - Task Breakdown

This document tracks all implementation tasks for the Master Device Architecture refactoring. Designed for parallel work by multiple agents.

---

## Integration Notes: Existing Camera Capability System

The codebase has a sophisticated camera capability discovery system that we MUST integrate with gracefully:

### Existing Components (DO NOT DUPLICATE)
- **CameraCapabilities** - Rich data model for modes, controls, limits
- **CapabilityValidator** - Single source of truth for settings validation
- **CameraModelDatabase** - Known camera database with fingerprinting
- **KnownCamerasCache** - Per-camera settings persistence
- **usb_backend.probe()** - V4L2/OpenCV capability probing

### Our New Components (COMPLEMENTARY)
- **MasterDevice** - Physical device identity (USB bus path) + capability classification
- **MasterDeviceRegistry** - Links video/audio interfaces on same physical device
- **USBPhysicalIdResolver** - Resolves USB bus paths for device association

### Key Distinction
| Existing System | New System |
|-----------------|------------|
| What can this camera DO? (modes, controls) | What INTERFACES does this device have? (video, audio) |
| Per-camera capability probing | Physical device identity tracking |
| Settings validation | Device classification |
| CameraCapabilities dataclass | MasterDevice dataclass |

### Integration Points
1. **USB Camera Scanner** already gets USB bus path via `LinuxCameraBackend._device_root()`
2. **assign_device command** already passes camera metadata - we ADD audio sibling params
3. **CamerasRuntime** uses CapabilityValidator - we ADD audio stream handling separately
4. **Audio recording** uses sounddevice library (same as Audio module) - NOT the camera capability system

### Design Principle
The new MasterDevice system handles DEVICE IDENTITY and CLASSIFICATION.
The existing camera system handles CAPABILITY DISCOVERY and VALIDATION.
They are orthogonal and complementary.

---

## Task States

| State | Symbol | Description |
|-------|--------|-------------|
| NOT_STARTED | `[ ]` | Work has not begun |
| IN_PROGRESS | `[~]` | Currently being worked on |
| BLOCKED | `[!]` | Waiting on dependency |
| COMPLETE | `[x]` | Finished and verified |

---

## Phase 1: Core Infrastructure

These tasks have no dependencies and can be worked in parallel.

### P1-A: Data Models
| ID | Task | State | Dependencies | Assignee | Notes |
|----|------|-------|--------------|----------|-------|
| P1-A1 | Create `DeviceCapability` enum | `[ ]` | None | | VIDEO_USB, VIDEO_CSI, AUDIO_INPUT, SERIAL_*, NETWORK |
| P1-A2 | Create `PhysicalInterface` enum | `[ ]` | None | | USB, CSI, UART, NETWORK, INTERNAL |
| P1-A3 | Create `CapabilityInfo` base class | `[ ]` | None | | Base dataclass for capability metadata |
| P1-A4 | Create `VideoUSBCapability` dataclass | `[ ]` | P1-A3 | | dev_path, stable_id, hw_model |
| P1-A5 | Create `VideoCSICapability` dataclass | `[ ]` | P1-A3 | | camera_num, sensor_model |
| P1-A6 | Create `AudioInputCapability` dataclass | `[ ]` | P1-A3 | | sounddevice_index, alsa_card, channels, sample_rate |
| P1-A7 | Create `SerialCapability` dataclass | `[ ]` | P1-A3 | | port, baudrate, vid, pid, device_subtype |
| P1-A8 | Create `NetworkCapability` dataclass | `[ ]` | P1-A3 | | ip_address, port, service_name |
| P1-A9 | Create `MasterDevice` dataclass | `[ ]` | P1-A1, P1-A2, P1-A3 | | physical_id, display_name, capabilities dict, convenience properties |

**Output file:** `rpi_logger/core/devices/master_device.py`

---

### P1-B: Master Device Registry
| ID | Task | State | Dependencies | Assignee | Notes |
|----|------|-------|--------------|----------|-------|
| P1-B1 | Create `MasterDeviceRegistry` class | `[ ]` | P1-A9 | | Single source of truth for physical devices |
| P1-B2 | Implement `register_capability()` | `[ ]` | P1-B1 | | Add capability to device, create device if needed |
| P1-B3 | Implement `unregister_capability()` | `[ ]` | P1-B1 | | Remove capability, remove device if empty |
| P1-B4 | Implement `get_device()` | `[ ]` | P1-B1 | | Query by physical_id |
| P1-B5 | Implement `get_webcams()` | `[ ]` | P1-B1 | | Devices with VIDEO_USB capability |
| P1-B6 | Implement `get_webcams_with_audio()` | `[ ]` | P1-B1 | | Webcams that also have AUDIO_INPUT |
| P1-B7 | Implement `get_standalone_audio_devices()` | `[ ]` | P1-B1 | | AUDIO_INPUT without VIDEO |
| P1-B8 | Implement `get_csi_cameras()` | `[ ]` | P1-B1 | | Devices with VIDEO_CSI capability |
| P1-B9 | Implement observer pattern | `[ ]` | P1-B1 | | Notify on capability changes |

**Output file:** `rpi_logger/core/devices/master_registry.py`

---

### P1-C: Physical ID Resolution
| ID | Task | State | Dependencies | Assignee | Notes |
|----|------|-------|--------------|----------|-------|
| P1-C1 | Create `USBPhysicalIdResolver` class | `[ ]` | None | | Static methods for resolving USB bus paths |
| P1-C2 | Implement `from_video_device()` | `[ ]` | P1-C1 | | /dev/video0 → USB bus path via sysfs |
| P1-C3 | Implement `from_alsa_card()` | `[ ]` | P1-C1 | | ALSA card index → USB bus path via sysfs |
| P1-C4 | Implement `from_sounddevice_index()` | `[ ]` | P1-C1, P1-C3 | | sounddevice index → ALSA card → USB bus path |
| P1-C5 | Implement `from_serial_port()` | `[ ]` | P1-C1 | | /dev/ttyUSB0 → USB bus path via sysfs |
| P1-C6 | Add fallback for non-USB devices | `[ ]` | P1-C1 | | Return None gracefully for CSI, UART, etc. |

**Output file:** `rpi_logger/core/devices/physical_id.py`

---

### P1-D: Unit Tests for Phase 1
| ID | Task | State | Dependencies | Assignee | Notes |
|----|------|-------|--------------|----------|-------|
| P1-D1 | Test MasterDevice properties | `[ ]` | P1-A9 | | is_webcam, has_builtin_mic, is_standalone_audio |
| P1-D2 | Test MasterDeviceRegistry CRUD | `[ ]` | P1-B9 | | register, unregister, queries |
| P1-D3 | Test USBPhysicalIdResolver | `[ ]` | P1-C6 | | Mock sysfs paths |
| P1-D4 | Test registry observer notifications | `[ ]` | P1-B9 | | Capability add/remove events |

**Output file:** `tests/core/devices/test_master_device.py`

---

## Phase 2: Scanner Integration

Requires Phase 1 complete.

### P2-A: USB Camera Scanner Updates
| ID | Task | State | Dependencies | Assignee | Notes |
|----|------|-------|--------------|----------|-------|
| P2-A1 | Add physical_id to DiscoveredUSBCamera | `[ ]` | P1-C2 | | New field in dataclass |
| P2-A2 | Update LinuxCameraBackend to resolve physical_id | `[ ]` | P2-A1 | | Call resolver during discovery |
| P2-A3 | Add audio sibling probing | `[ ]` | P2-A2, P1-C4 | | Check for ALSA devices on same USB path |
| P2-A4 | Add audio_sibling_info to DiscoveredUSBCamera | `[ ]` | P2-A3 | | Optional field with sounddevice index, channels, rate |
| P2-A5 | Register VIDEO_USB capability with registry | `[ ]` | P2-A2, P1-B2 | | On camera discovery |
| P2-A6 | Register AUDIO_INPUT capability if sibling found | `[ ]` | P2-A4, P1-B2 | | Same physical_id as camera |

**Files:** `usb_camera_scanner.py`, `camera_backends/linux.py`, `camera_backends/base.py`

---

### P2-B: Audio Scanner Updates
| ID | Task | State | Dependencies | Assignee | Notes |
|----|------|-------|--------------|----------|-------|
| P2-B1 | Add physical_id resolution to AudioScanner | `[ ]` | P1-C4 | | Resolve for each discovered device |
| P2-B2 | Check registry before emitting discovery | `[ ]` | P2-B1, P1-B1 | | Is this audio already registered as webcam sibling? |
| P2-B3 | Skip webcam-associated audio devices | `[ ]` | P2-B2 | | Don't emit event if already in registry with VIDEO |
| P2-B4 | Register standalone audio with registry | `[ ]` | P2-B3, P1-B2 | | Only for truly standalone devices |

**File:** `audio_scanner.py`

---

### P2-C: CSI Camera Scanner Updates
| ID | Task | State | Dependencies | Assignee | Notes |
|----|------|-------|--------------|----------|-------|
| P2-C1 | Add physical_id for CSI cameras | `[ ]` | P1-B1 | | Use "csi:N" format |
| P2-C2 | Register VIDEO_CSI capability | `[ ]` | P2-C1, P1-B2 | | On CSI camera discovery |

**File:** `csi_camera_scanner.py` (if exists) or relevant scanner

---

### P2-D: Integration Tests for Phase 2
| ID | Task | State | Dependencies | Assignee | Notes |
|----|------|-------|--------------|----------|-------|
| P2-D1 | Test webcam with mic registers both capabilities | `[ ]` | P2-A6 | | Mock camera + audio discovery |
| P2-D2 | Test audio scanner filters webcam mics | `[ ]` | P2-B3 | | Verify not emitted |
| P2-D3 | Test standalone mic passes through | `[ ]` | P2-B4 | | Verify emitted |
| P2-D4 | Test hot-plug updates registry | `[ ]` | P2-A5, P2-B4 | | Add/remove device |

---

## Phase 3: Core System Updates

Can start once Phase 2 scanner work is complete.

### P3-A: Device System Integration
| ID | Task | State | Dependencies | Assignee | Notes |
|----|------|-------|--------------|----------|-------|
| P3-A1 | Add MasterDeviceRegistry instance to DeviceSystem | `[ ]` | P1-B9 | | Owned by DeviceSystem |
| P3-A2 | Wire scanners to registry | `[ ]` | P3-A1, P2-A6, P2-B4 | | Scanners register capabilities |
| P3-A3 | Add registry query methods to DeviceSystem | `[ ]` | P3-A1 | | Expose get_webcams(), etc. |
| P3-A4 | Update device_system __init__.py exports | `[ ]` | P3-A3 | | Export new types and methods |

**File:** `device_system.py`

---

### P3-B: Lifecycle Manager Updates
| ID | Task | State | Dependencies | Assignee | Notes |
|----|------|-------|--------------|----------|-------|
| P3-B1 | Add MasterDevice reference to DeviceInfo | `[ ]` | P3-A1, P1-A9 | | Optional field, populated from registry |
| P3-B2 | Add is_webcam_with_mic property to DeviceInfo | `[ ]` | P3-B1 | | Derived from MasterDevice |
| P3-B3 | Update _handle_discovered to query registry | `[ ]` | P3-B1 | | Get MasterDevice for capability info |
| P3-B4 | Update display name generation | `[ ]` | P3-B3 | | Include audio indicator for webcams with mic |

**File:** `lifecycle.py`

---

### P3-C: Events Updates
| ID | Task | State | Dependencies | Assignee | Notes |
|----|------|-------|--------------|----------|-------|
| P3-C1 | Add has_audio field to camera discovery events | `[ ]` | P2-A4 | | Boolean indicating webcam has mic |
| P3-C2 | Update discovered_camera_device builder | `[ ]` | P3-C1 | | Accept audio sibling info |

**File:** `events.py`

---

### P3-D: Selection Model Updates
| ID | Task | State | Dependencies | Assignee | Notes |
|----|------|-------|--------------|----------|-------|
| P3-D1 | Add capability-based enable/disable | `[ ]` | P3-A3 | | Alternative to family-based |
| P3-D2 | Update is_connection_enabled for capabilities | `[ ]` | P3-D1 | | Check by capability type |

**File:** `selection.py`

---

### P3-E: Scanner Adapter Simplification
| ID | Task | State | Dependencies | Assignee | Notes |
|----|------|-------|--------------|----------|-------|
| P3-E1 | Update on_usb_camera_found for audio info | `[ ]` | P3-C2 | | Pass through audio sibling data |
| P3-E2 | Evaluate adapter necessity | `[ ]` | P3-E1 | | May be simplified significantly |

**File:** `scanner_adapter.py`

---

## Phase 4: Module Updates

Can be done in parallel once Phase 3-B is complete.

### P4-A: Command Protocol Updates
| ID | Task | State | Dependencies | Assignee | Notes |
|----|------|-------|--------------|----------|-------|
| P4-A1 | Add webcam_audio_enabled param to assign_device | `[ ]` | None | | Boolean flag |
| P4-A2 | Add webcam_audio_index param | `[ ]` | P4-A1 | | sounddevice index |
| P4-A3 | Add webcam_audio_channels param | `[ ]` | P4-A1 | | Channel count |
| P4-A4 | Add webcam_audio_sample_rate param | `[ ]` | P4-A1 | | Sample rate |

**File:** `command_protocol.py`

---

### P4-B: Logger System Updates
| ID | Task | State | Dependencies | Assignee | Notes |
|----|------|-------|--------------|----------|-------|
| P4-B1 | Update _build_assign_device_command_builder | `[ ]` | P4-A4, P3-B2 | | Include webcam audio params from DeviceInfo |
| P4-B2 | Query MasterDeviceRegistry for device info | `[ ]` | P4-B1, P3-A3 | | Get audio capability details |

**File:** `logger_system.py`

---

### P4-C: Cameras Module - Audio Integration
| ID | Task | State | Dependencies | Assignee | Notes |
|----|------|-------|--------------|----------|-------|
| P4-C1 | Add audio state fields to CamerasRuntime | `[ ]` | P4-A4 | | audio_enabled, audio_stream, etc. |
| P4-C2 | Parse webcam_audio_* params in _assign_camera | `[ ]` | P4-C1 | | Extract from command dict |
| P4-C3 | Initialize sounddevice stream when audio enabled | `[ ]` | P4-C2 | | On camera assignment |
| P4-C4 | Add audio recording to _start_recording | `[ ]` | P4-C3 | | Start audio capture alongside video |
| P4-C5 | Add audio stop to _stop_recording | `[ ]` | P4-C4 | | Stop and finalize audio file |
| P4-C6 | Write audio to separate WAV file | `[ ]` | P4-C4 | | video_audio_trial_XXX.wav |
| P4-C7 | Add audio level meter support | `[ ]` | P4-C3 | | Optional: real-time level monitoring |

**File:** `Cameras/bridge.py`

**INTEGRATION NOTE:** Audio handling is SEPARATE from the existing CameraCapabilities/CapabilityValidator system.
- Use sounddevice library directly (same pattern as Audio module)
- DO NOT add audio to CameraCapabilities - it's a different interface on the same physical device
- Audio settings (sample rate, channels) come from MasterDevice, not from camera probing

---

### P4-D: Cameras Module - UI Updates
| ID | Task | State | Dependencies | Assignee | Notes |
|----|------|-------|--------------|----------|-------|
| P4-D1 | Add "has audio" indicator to camera view | `[ ]` | P4-C1 | | Show when webcam has mic |
| P4-D2 | Add "record audio" checkbox | `[ ]` | P4-D1 | | User toggle |
| P4-D3 | Wire checkbox to runtime state | `[ ]` | P4-D2, P4-C1 | | Update audio_enabled |
| P4-D4 | Add audio level meter widget | `[ ]` | P4-D3, P4-C7 | | Optional: show audio levels |

**File:** `Cameras/app/view.py`

---

### P4-E: Cameras Module - Config Updates
| ID | Task | State | Dependencies | Assignee | Notes |
|----|------|-------|--------------|----------|-------|
| P4-E1 | Add record_audio setting to CamerasConfig | `[ ]` | P4-D3 | | Persist user preference |
| P4-E2 | Load/save audio preference | `[ ]` | P4-E1 | | Per-camera setting in cache |

**File:** `Cameras/config.py`

---

### P4-F: Audio Module Updates
| ID | Task | State | Dependencies | Assignee | Notes |
|----|------|-------|--------------|----------|-------|
| P4-F1 | Verify Audio module receives filtered list | `[ ]` | P2-B3 | | Webcam mics not in device list |
| P4-F2 | Add info message about webcam mics | `[ ]` | P4-F1 | | Optional: UI note |

**File:** `Audio/runtime/adapter.py`

---

## Phase 5: UI Updates

Depends on Phase 3-B and Phase 4-D.

### P5-A: Device Controller Updates
| ID | Task | State | Dependencies | Assignee | Notes |
|----|------|-------|--------------|----------|-------|
| P5-A1 | Add webcam audio indicator to device panel | `[ ]` | P3-B2 | | Show mic icon on webcams with audio |
| P5-A2 | Update device grouping for capabilities | `[ ]` | P5-A1 | | Group by capability, not family |

**File:** `device_controller.py`

---

## Phase 6: Cleanup

Only after all features are working.

### P6-A: Dead Code Removal
| ID | Task | State | Dependencies | Assignee | Notes |
|----|------|-------|--------------|----------|-------|
| P6-A1 | Audit DeviceFamily usage | `[ ]` | P5-A2 | | Find all references |
| P6-A2 | Deprecate unused DeviceFamily values | `[ ]` | P6-A1 | | CAMERA_USB, AUDIO if fully replaced |
| P6-A3 | Audit DeviceType usage | `[ ]` | P5-A2 | | Keep VID/PID types |
| P6-A4 | Remove unused DeviceSpec fields | `[ ]` | P6-A3 | | If superseded by capabilities |
| P6-A5 | Simplify scanner_adapter.py | `[ ]` | P3-E2 | | Remove redundant adapters |
| P6-A6 | Run full dead code audit | `[ ]` | P6-A5 | | Use static analysis tools |
| P6-A7 | Remove identified dead code | `[ ]` | P6-A6 | | Clean removal |

---

### P6-B: Test Updates
| ID | Task | State | Dependencies | Assignee | Notes |
|----|------|-------|--------------|----------|-------|
| P6-B1 | Update existing device tests | `[ ]` | P6-A7 | | Fix broken tests |
| P6-B2 | Add end-to-end webcam audio test | `[ ]` | P4-C6 | | Full flow test |
| P6-B3 | Add regression tests for existing modules | `[ ]` | P6-A7 | | DRT, VOG, etc. still work |

---

## Dependency Graph

```
Phase 1 (Parallel)
├── P1-A: Data Models ──────────────────┐
├── P1-B: Registry (depends on P1-A9) ──┼──┐
├── P1-C: Physical ID Resolver ─────────┘  │
└── P1-D: Tests (depends on P1-A,B,C) ─────┘
                    │
                    ▼
Phase 2 (Parallel after Phase 1)
├── P2-A: USB Camera Scanner ───────────┐
├── P2-B: Audio Scanner ────────────────┼──┐
├── P2-C: CSI Camera Scanner ───────────┘  │
└── P2-D: Tests ───────────────────────────┘
                    │
                    ▼
Phase 3 (Sequential dependencies)
├── P3-A: Device System ────────────────┐
├── P3-B: Lifecycle (depends on P3-A) ──┤
├── P3-C: Events ───────────────────────┤
├── P3-D: Selection ────────────────────┤
└── P3-E: Scanner Adapter ──────────────┘
                    │
                    ▼
Phase 4 (Parallel after Phase 3)
├── P4-A: Command Protocol ─────────────┐
├── P4-B: Logger System (depends P4-A) ─┤
├── P4-C: Cameras Audio ────────────────┤
├── P4-D: Cameras UI (depends P4-C) ────┤
├── P4-E: Cameras Config ───────────────┤
└── P4-F: Audio Module ─────────────────┘
                    │
                    ▼
Phase 5 (After Phase 4)
└── P5-A: Device Controller UI ─────────┘
                    │
                    ▼
Phase 6 (Final cleanup)
├── P6-A: Dead Code Removal
└── P6-B: Test Updates
```

---

## Parallel Work Allocation

### Can be worked simultaneously by different agents:

**Agent 1:** P1-A (Data Models) → P2-A (USB Camera Scanner) → P4-C (Cameras Audio)

**Agent 2:** P1-B (Registry) → P3-A (Device System) → P4-B (Logger System)

**Agent 3:** P1-C (Physical ID) → P2-B (Audio Scanner) → P4-F (Audio Module)

**Agent 4:** P1-D (Tests) → P2-D (Integration Tests) → P6-B (Test Updates)

---

---

## Phase 7: Data Validation Testing (Super Sanity Test)

**Reference**: See `DATA_VALIDATION_TEST_PLAN.md` for full specifications.

This phase implements the comprehensive data validation framework that ensures all module data is captured correctly.

### P7-A: Schema Validation Framework
| ID | Task | State | Dependencies | Assignee | Notes |
|----|------|-------|--------------|----------|-------|
| P7-A1 | Create `CSVSchemaValidator` base class | `[ ]` | None | | Validates headers, types, ranges |
| P7-A2 | Define GPS schema (26 columns) | `[ ]` | P7-A1 | | See DATA_VALIDATION_TEST_PLAN.md |
| P7-A3 | Define DRT schemas (sDRT: 10, wDRT: 11 cols) | `[ ]` | P7-A1 | | Both protocols |
| P7-A4 | Define VOG schemas (sVOG: 7, wVOG: 11 cols) | `[ ]` | P7-A1 | | Both protocols |
| P7-A5 | Define EyeTracker schemas (GAZE, IMU, EVENTS) | `[ ]` | P7-A1 | | 3 separate CSVs |
| P7-A6 | Define Notes schema (8 columns) | `[ ]` | P7-A1 | | Simplest schema |
| P7-A7 | Define Audio timing schema | `[ ]` | P7-A1 | | WAV + optional timing CSV |
| P7-A8 | Implement row-by-row validation | `[ ]` | P7-A1 | | With detailed error reporting |

**Output file:** `rpi_logger/modules/base/tests/csv_schema.py`

---

### P7-B: Hardware Detection Framework
| ID | Task | State | Dependencies | Assignee | Notes |
|----|------|-------|--------------|----------|-------|
| P7-B1 | Create `HardwareAvailability` class | `[ ]` | None | | Singleton for hardware detection |
| P7-B2 | Implement GPS detection (serial VID/PID) | `[ ]` | P7-B1 | | Check for NMEA devices |
| P7-B3 | Implement DRT detection (serial VID/PID) | `[ ]` | P7-B1 | | sDRT + wDRT identifiers |
| P7-B4 | Implement VOG detection (serial VID/PID) | `[ ]` | P7-B1 | | sVOG + wVOG identifiers |
| P7-B5 | Implement EyeTracker detection (network) | `[ ]` | P7-B1 | | Pupil Neon discovery |
| P7-B6 | Implement Audio detection (sounddevice) | `[ ]` | P7-B1 | | Input device enumeration |
| P7-B7 | Implement Camera detection (V4L2) | `[ ]` | P7-B1 | | USB webcam enumeration |
| P7-B8 | Implement CSI detection (libcamera) | `[ ]` | P7-B1 | | RPi platform check |
| P7-B9 | Generate availability matrix report | `[ ]` | P7-B2-B8 | | Human-readable output |

**Output file:** `rpi_logger/modules/base/tests/hardware_detection.py`

---

### P7-C: Mock Infrastructure
| ID | Task | State | Dependencies | Assignee | Notes |
|----|------|-------|--------------|----------|-------|
| P7-C1 | Create `MockSerialDevice` base class | `[ ]` | None | | For DRT/VOG/GPS |
| P7-C2 | Implement GPS NMEA replay mock | `[ ]` | P7-C1 | | Feeds recorded NMEA sentences |
| P7-C3 | Implement DRT serial mock | `[ ]` | P7-C1 | | Simulates button press events |
| P7-C4 | Implement VOG serial mock | `[ ]` | P7-C1 | | Simulates shutter events |
| P7-C5 | Create `MockSoundDevice` | `[ ]` | None | | For Audio module |
| P7-C6 | Create `MockCameraBackend` | `[ ]` | None | | Generates test frames |
| P7-C7 | Create `MockPupilNeonAPI` | `[ ]` | None | | Network API simulation |

**Output directory:** `rpi_logger/modules/base/tests/mocks/`

---

### P7-D: Sample Data Fixtures
| ID | Task | State | Dependencies | Assignee | Notes |
|----|------|-------|--------------|----------|-------|
| P7-D1 | Create/collect GPS sample CSV | `[ ]` | None | | Valid NMEA-derived data |
| P7-D2 | Create/collect DRT sample CSVs | `[ ]` | None | | sDRT and wDRT examples |
| P7-D3 | Create/collect VOG sample CSVs | `[ ]` | None | | sVOG and wVOG examples |
| P7-D4 | Create/collect EyeTracker sample CSVs | `[ ]` | None | | GAZE, IMU, EVENTS |
| P7-D5 | Create Notes sample CSV | `[ ]` | None | | Can be generated |
| P7-D6 | Create Audio sample files | `[ ]` | None | | WAV + timing CSV |
| P7-D7 | Create Video sample file | `[ ]` | None | | Short MP4 clip |

**Output directory:** `rpi_logger/modules/base/tests/fixtures/`

---

### P7-E: Schema Validation Tests
| ID | Task | State | Dependencies | Assignee | Notes |
|----|------|-------|--------------|----------|-------|
| P7-E1 | Test GPS schema validation | `[ ]` | P7-A2, P7-D1 | | Valid + invalid cases |
| P7-E2 | Test DRT schema validation | `[ ]` | P7-A3, P7-D2 | | Both protocols |
| P7-E3 | Test VOG schema validation | `[ ]` | P7-A4, P7-D3 | | Both protocols |
| P7-E4 | Test EyeTracker schema validation | `[ ]` | P7-A5, P7-D4 | | All 3 stream types |
| P7-E5 | Test Notes schema validation | `[ ]` | P7-A6, P7-D5 | | UTF-8 edge cases |
| P7-E6 | Test Audio file validation | `[ ]` | P7-A7, P7-D6 | | WAV integrity |
| P7-E7 | Test 6-column prefix consistency | `[ ]` | P7-A1 | | Cross-module check |

**Output file:** `rpi_logger/modules/base/tests/test_data_validation.py`

---

### P7-F: Timing Validation Tests
| ID | Task | State | Dependencies | Assignee | Notes |
|----|------|-------|--------------|----------|-------|
| P7-F1 | Test monotonic timestamp ordering | `[ ]` | P7-E7 | | No time travel |
| P7-F2 | Test unix/mono time alignment | `[ ]` | P7-E7 | | Drift detection |
| P7-F3 | Test cross-module synchronization | `[ ]` | P7-E7 | | Gap detection |
| P7-F4 | Test SYNC file generation | `[ ]` | P7-E7 | | Complete and valid |
| P7-F5 | Test SYNC file references | `[ ]` | P7-F4 | | All files exist |

---

### P7-G: Integration Tests
| ID | Task | State | Dependencies | Assignee | Notes |
|----|------|-------|--------------|----------|-------|
| P7-G1 | Test recording lifecycle with mocks | `[ ]` | P7-C7 | | Start → capture → stop |
| P7-G2 | Test hardware unavailable handling | `[ ]` | P7-B9 | | Graceful skip |
| P7-G3 | Test error condition recovery | `[ ]` | P7-G1 | | Device disconnect |
| P7-G4 | Test disk space guard | `[ ]` | P7-G1 | | Near-full disk |

---

### P7-H: Test Reporting
| ID | Task | State | Dependencies | Assignee | Notes |
|----|------|-------|--------------|----------|-------|
| P7-H1 | Implement summary report generator | `[ ]` | P7-E7 | | Human-readable output |
| P7-H2 | Implement detailed error report | `[ ]` | P7-H1 | | Per-row errors |
| P7-H3 | Implement hardware matrix output | `[ ]` | P7-B9 | | Tested/untested list |
| P7-H4 | Add pytest markers for hardware tests | `[ ]` | P7-B9 | | @pytest.mark.requires_gps, etc. |

---

## Updated Dependency Graph

```
Phase 1-6 (existing)
        │
        ▼
Phase 7: Data Validation (can start in parallel with Phase 3+)
├── P7-A: Schema Framework ──────────┐
├── P7-B: Hardware Detection ────────┤
├── P7-C: Mocks (parallel) ──────────┤
├── P7-D: Sample Data (parallel) ────┤
├── P7-E: Schema Tests (needs A,D) ──┤
├── P7-F: Timing Tests (needs E) ────┤
├── P7-G: Integration (needs C,E) ───┤
└── P7-H: Reporting (needs all) ─────┘
```

---

## Notes

- Update task state in this document as work progresses
- Add assignee when claiming a task
- Add notes for blockers or decisions made
- Cross-reference commit hashes when completing tasks
