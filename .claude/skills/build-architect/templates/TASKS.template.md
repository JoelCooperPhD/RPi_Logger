# [MODULE_NAME] Task Tracker

> **Master task list for AI-driven development**
>
> This is the single source of truth for task status. AI agents check here for available work.

## FIRST: Folder Setup

Before starting implementation:

```bash
cd [PROJECT_ROOT]
mkdir -p [module_path]/{folder1,folder2,folder3,tests/{unit,integration}}
touch [module_path]/{folder1,folder2,folder3}/__init__.py
```

---

## Coding Standards (MANDATORY)

Before implementing ANY task, read [design.md](reference/design.md). Key requirements:

- **Modern asyncio** - use `async/await`, not threads (except where noted)
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

## Phase 1: [PHASE_NAME] ([N] sub-tasks)

[Brief description]

| ID | Task | Status | Depends On | Agent | File to Create |
|----|------|--------|------------|-------|----------------|
| P1.1 | [Task description] | available | - | - | `path/file.py` |
| P1.2 | [Task description] | available | P1.1 | - | `path/file.py` |

**Task File**: [phase1_[name].md](tasks/phase1_[name].md) | **Specs**: [components.md](specs/components.md)

---

## Phase 2: [PHASE_NAME] ([N] sub-tasks)

[Brief description]

| ID | Task | Status | Depends On | Agent | File to Create |
|----|------|--------|------------|-------|----------------|
| P2.1 | [Task description] | available | P1.1 | - | `path/file.py` |

**Task File**: [phase2_[name].md](tasks/phase2_[name].md)

---

## Testing Tasks

| ID | Task | Status | Depends On | Agent | Task File |
|----|------|--------|------------|-------|-----------|
| T1 | Unit tests | available | P1, P2 | - | [testing_unit.md](tasks/testing_unit.md) |
| T2 | Integration tests | available | P[N] | - | [testing_integration.md](tasks/testing_integration.md) |

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

- **Total Tasks**: [N]
- **Available**: [N]
- **In Progress**: 0
- **Completed**: 0
- **Blocked**: 0
