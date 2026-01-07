# Cameras_CSI2 Task Tracker

> **Master task list for AI-driven development**
>
> This is the single source of truth for task status. AI agents check here for available work.

## Coding Standards (MANDATORY)

Before implementing ANY task, read [design.md](reference/design.md). Key requirements:

- **Modern asyncio** - use `async/await`, not threads (except capture loop)
- **Non-blocking I/O** - all file/network ops via `asyncio.to_thread()` or async libs
- **No docstrings** - skip docstrings and obvious comments
- **Concise code** - optimize for AI readability (context/token efficiency)
- **Type hints** - use type hints instead of documentation

---

## How to Use

1. Find a task with status `available` and all dependencies `completed`
2. Change status to `in_progress` and add your agent ID (format: `claude-YYYYMMDD-HHMMSS`)
3. Read the linked task file for detailed instructions
4. When validation checklist passes, change status to `completed` and note the date
5. If blocked, set status to `blocked` and add blocker notes

---

## Phase 1: Foundation (4 sub-tasks)

Core data types and frame acquisition.

| ID | Task | Status | Depends On | Agent | File to Create |
|----|------|--------|------------|-------|----------------|
| P1.1 | CapturedFrame dataclass | available | - | - | `capture/frame.py` |
| P1.2 | FrameSource protocol | available | P1.1 | - | `capture/source.py` |
| P1.3 | PicamSource implementation | available | P1.2 | - | `capture/picam_source.py` |
| P1.4 | Lock-free frame buffer | available | - | - | `pipeline/frame_buffer.py` |

**Task File**: [phase1_foundation.md](tasks/phase1_foundation.md) | **Specs**: [components.md](specs/components.md)

---

## Phase 2: Pipeline (3 sub-tasks)

Frame routing and timing control.

| ID | Task | Status | Depends On | Agent | File to Create |
|----|------|--------|------------|-------|----------------|
| P2.1 | TimingGate | available | P1.1 | - | `pipeline/timing_gate.py` |
| P2.2 | FrameRouter | available | P1.4, P2.1 | - | `pipeline/router.py` |
| P2.3 | FrameMetrics | available | - | - | `pipeline/metrics.py` |

**Task File**: [phase2_pipeline.md](tasks/phase2_pipeline.md) | **Specs**: [components.md](specs/components.md)

---

## Phase 3: Recording (4 sub-tasks)

Video and CSV output pipeline.

| ID | Task | Status | Depends On | Agent | File to Create |
|----|------|--------|------------|-------|----------------|
| P3.1 | TimingCSVWriter | available | P1.1 | - | `recording/timing_csv.py` |
| P3.2 | VideoEncoder wrapper | available | - | - | `recording/encoder.py` |
| P3.3 | RecordingSession | available | P3.1, P3.2, P2.1 | - | `recording/recorder.py` |
| P3.4 | Session paths | available | - | - | `recording/session_paths.py` |

**Task File**: [phase3_recording.md](tasks/phase3_recording.md) | **Specs**: [output_formats.md](specs/output_formats.md)

---

## Phase 4: Preview (single task)

Display pipeline with efficient scaling.

| ID | Task | Status | Depends On | Agent | Files to Create |
|----|------|--------|------------|-------|-----------------|
| P4 | Preview pipeline | available | P1.1, P2.1 | - | `preview/processor.py`, `preview/scaler.py` |

**Task File**: [phase4_preview.md](tasks/phase4_preview.md)

---

## Phase 5: View (single task)

GUI layer matching current module.

| ID | Task | Status | Depends On | Agent | Files to Create |
|----|------|--------|------------|-------|-----------------|
| P5 | GUI/View layer | available | P4 | - | `view/view.py`, `view/settings_window.py`, `view/dialogs/` |

**Task File**: [phase5_view.md](tasks/phase5_view.md) | **Specs**: [gui.md](specs/gui.md)

---

## Phase 6: Runtime (3 sub-tasks)

Orchestration and entry points.

| ID | Task | Status | Depends On | Agent | File to Create |
|----|------|--------|------------|-------|----------------|
| P6.1 | CSICameraRuntime | available | P1-P5 | - | `runtime.py` |
| P6.2 | Entry point & factory | available | P6.1 | - | `main.py`, `__init__.py` |
| P6.3 | Configuration | available | - | - | `config.py` |

**Task File**: [phase6_runtime.md](tasks/phase6_runtime.md) | **Specs**: [commands.md](specs/commands.md)

---

## Phase 7: Hardening (single task)

Production readiness.

| ID | Task | Status | Depends On | Agent | Focus |
|----|------|--------|------------|-------|-------|
| P7 | Production hardening | available | P6 | - | Error handling, graceful degradation |

**Task File**: [phase7_hardening.md](tasks/phase7_hardening.md) | **Specs**: [debugging.md](specs/debugging.md)

---

## Testing Tasks

| ID | Task | Status | Depends On | Agent | Task File |
|----|------|--------|------------|-------|-----------|
| T1 | Unit tests | available | P1, P2 | - | [testing_unit.md](tasks/testing_unit.md) |
| T2 | Integration tests | available | P6 | - | [testing_integration.md](tasks/testing_integration.md) |
| T3 | Stress tests | available | P6 | - | [testing_stress.md](tasks/testing_stress.md) |

---

## Migration

| ID | Task | Status | Depends On | Agent | Task File |
|----|------|--------|------------|-------|-----------|
| M1 | Cutover & cleanup | available | P7, T1-T3 | - | [migration.md](tasks/migration.md) |

---

## Status Legend

| Status | Meaning |
|--------|---------|
| `available` | Ready to start (all dependencies completed) |
| `in_progress` | Being worked on (agent ID assigned) |
| `blocked` | Waiting on external issue (add blocker notes) |
| `completed` | Done and validation checklist passed |

---

## Completed Tasks Log

| ID | Completed | Agent | Duration | Notes |
|----|-----------|-------|----------|-------|
| - | - | - | - | - |

---

## Quick Stats

- **Total Tasks**: 21 (17 sub-tasks + 4 single tasks)
- **Available**: 21
- **In Progress**: 0
- **Completed**: 0
- **Blocked**: 0
