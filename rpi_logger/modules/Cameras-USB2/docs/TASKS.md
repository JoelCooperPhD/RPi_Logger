# Cameras-USB2 Module - Task Tracker

> **WARNING**: This module folder is `Cameras-USB2`. Do not rename or move.

## Coding Standards (MANDATORY)

| Requirement | Rationale |
|-------------|-----------|
| Modern asyncio patterns | Use async/await, not threads |
| Non-blocking I/O | All I/O via `asyncio.to_thread()` |
| No docstrings | Skip docstrings and obvious comments |
| Concise code | Optimize for AI readability |
| Type hints | Use type hints for self-documentation |
| Max 200 lines/file | Keep files small and focused |

## How to Use This Document

1. Find a task with `status=available` and all dependencies `completed`
2. Update status to `in_progress` and add your agent ID
3. Read the linked task file in `tasks/`
4. Read relevant specs in `specs/`
5. Implement deliverables listed in task file
6. Run validation checklist from task file
7. Update status to `completed` with date and notes

---

## Phase 1: Foundation

| ID | Task | Status | Depends On | Agent | File |
|----|------|--------|------------|-------|------|
| P1.1 | Core types and interfaces | available | - | - | `tasks/phase1_foundation.md` |
| P1.2 | Configuration system | available | - | - | `tasks/phase1_foundation.md` |
| P1.3 | USB backend probe | available | P1.1 | - | `tasks/phase1_foundation.md` |
| P1.4 | Capability normalization | available | P1.1, P1.3 | - | `tasks/phase1_foundation.md` |

## Phase 2: Capture Pipeline

| ID | Task | Status | Depends On | Agent | File |
|----|------|--------|------------|-------|------|
| P2.1 | USB capture class | available | P1.1, P1.3 | - | `tasks/phase2_capture.md` |
| P2.2 | Frame queue system | available | P2.1 | - | `tasks/phase2_capture.md` |
| P2.3 | Capture loop async | available | P2.1, P2.2 | - | `tasks/phase2_capture.md` |

## Phase 3: Recording

| ID | Task | Status | Depends On | Agent | File |
|----|------|--------|------------|-------|------|
| P3.1 | Session path resolution | available | P1.2 | - | `tasks/phase3_recording.md` |
| P3.2 | Encoder integration | available | P2.3 | - | `tasks/phase3_recording.md` |
| P3.3 | Timing CSV writer | available | P3.2 | - | `tasks/phase3_recording.md` |
| P3.4 | Disk guard integration | available | P3.1 | - | `tasks/phase3_recording.md` |

## Phase 4: Runtime Bridge

| ID | Task | Status | Depends On | Agent | File |
|----|------|--------|------------|-------|------|
| P4.1 | CamerasRuntime skeleton | available | P1.1, P1.2 | - | `tasks/phase4_runtime.md` |
| P4.2 | Device assignment | available | P4.1, P1.4 | - | `tasks/phase4_runtime.md` |
| P4.3 | Command handlers | available | P4.1, P3.2 | - | `tasks/phase4_runtime.md` |
| P4.4 | Status reporting | available | P4.3 | - | `tasks/phase4_runtime.md` |

## Phase 5: Preview System

| ID | Task | Status | Depends On | Agent | File |
|----|------|--------|------------|-------|------|
| P5.1 | Preview frame generation | available | P2.3 | - | `tasks/phase5_preview.md` |
| P5.2 | Canvas display widget | available | - | - | `tasks/phase5_preview.md` |
| P5.3 | Metrics panel | available | P5.2 | - | `tasks/phase5_preview.md` |

## Phase 6: Settings UI

| ID | Task | Status | Depends On | Agent | File |
|----|------|--------|------------|-------|------|
| P6.1 | Settings window | available | P5.2 | - | `tasks/phase6_settings.md` |
| P6.2 | Camera controls | available | P6.1, P1.4 | - | `tasks/phase6_settings.md` |
| P6.3 | Apply config handler | available | P6.1, P4.3 | - | `tasks/phase6_settings.md` |

## Phase 7: Integration & Entry Point

| ID | Task | Status | Depends On | Agent | File |
|----|------|--------|------------|-------|------|
| P7.1 | Main entry point | available | P4.4 | - | `tasks/phase7_integration.md` |
| P7.2 | CameraView composition | available | P5.3, P6.3 | - | `tasks/phase7_integration.md` |
| P7.3 | End-to-end testing | available | P7.1, P7.2 | - | `tasks/phase7_integration.md` |

## Testing Tasks

| ID | Task | Status | Depends On | Agent | File |
|----|------|--------|------------|-------|------|
| T1 | Unit tests | available | P1.1, P2.1 | - | `tasks/testing_unit.md` |
| T2 | Integration tests | available | P7.1, P7.2 | - | `tasks/testing_integration.md` |
| T3 | Stress tests | available | P7.3 | - | `tasks/testing_stress.md` |

---

## Phase Sequencing Rationale

**Why this order?** Each phase builds on the previous, establishing contracts before consumers.

| Phase | Rationale | Breaks if Skipped |
|-------|-----------|-------------------|
| P1 Foundation | Defines core types (`CaptureFrame`, `CameraId`) used everywhere | All other phases fail to compile |
| P2 Capture | Produces frames that recording/preview consume | P3, P5 have nothing to display/record |
| P3 Recording | Depends on capture output, writes to disk | P4 can't start/stop recording |
| P4 Runtime | Orchestrates capture + recording, handles commands | P7 entry point has nothing to call |
| P5 Preview | Consumes frames from P2, displays in UI | P6 settings window has no preview |
| P6 Settings | Adjusts P4 runtime via UI controls | P7 integration incomplete |
| P7 Integration | Wires everything together | Module non-functional |

**Critical dependencies**:
- P2.3 (capture async) MUST complete before P3.2 (encoder) - encoder needs frame iterator
- P4.1 (runtime skeleton) MUST complete before P4.3 (commands) - commands need runtime instance
- P5.2 (canvas widget) MUST complete before P6.1 (settings) - settings embeds preview

**Parallelization opportunities**:
- P1.1 + P1.2 + P5.2 can run simultaneously (no interdependencies)
- P3.1 + P3.4 can run after P1.2 (only need config)
- P5.1 can run after P2.3 without waiting for P3.x

## Dependency Graph

```
NO DEPENDENCIES (can start immediately):
  P1.1, P1.2, P5.2

AFTER P1.1:
  P1.3

AFTER P1.1 + P1.3:
  P1.4, P2.1

AFTER P1.2:
  P3.1

AFTER P2.1:
  P2.2

AFTER P2.1 + P2.2:
  P2.3

AFTER P2.3:
  P3.2, P5.1

AFTER P3.1:
  P3.4

AFTER P3.2:
  P3.3

AFTER P1.1 + P1.2:
  P4.1

AFTER P4.1 + P1.4:
  P4.2

AFTER P4.1 + P3.2:
  P4.3

AFTER P4.3:
  P4.4

AFTER P5.2:
  P5.3, P6.1

AFTER P6.1 + P1.4:
  P6.2

AFTER P6.1 + P4.3:
  P6.3

AFTER P4.4:
  P7.1

AFTER P5.3 + P6.3:
  P7.2

AFTER P7.1 + P7.2:
  P7.3, T2

AFTER P1.1 + P2.1:
  T1

AFTER P7.3:
  T3
```

---

## Status Legend

| Status | Meaning |
|--------|---------|
| available | Ready to start, dependencies met |
| in_progress | Currently being worked on |
| completed | Done and validated |
| blocked | Waiting on external factor |

## Quick Stats

- Total tasks: 25 (22 implementation + 3 testing)
- Completed: 0
- In Progress: 0
- Available: 25
- Blocked: 0
