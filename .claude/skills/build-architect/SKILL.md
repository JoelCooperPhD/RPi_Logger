---
name: build-architect
description: Knowledge base for designing AI-agent-friendly build documentation (project)
globs:
  - "**/ARCHITECTURE.md"
  - "**/docs/TASKS.md"
---

# Build Architect Skill

Guide for creating documentation structures for Logger modules. All modules use **Elm/Redux architecture** for consistency and testability.

## When to Use

Use `/architect` when starting a new module or planning a multi-phase implementation.

---

## Core Principles

### 1. Architecture-First

Create `ARCHITECTURE.md` BEFORE task documentation. Must include:
- Pattern declaration (Elm/Redux)
- Data flow diagram (ASCII art)
- Folder structure
- Standalone execution command (`uv run main.py`)

### 2. Testability via Elm/Redux

All modules use Elm/Redux for testable state management:
- **State**: Frozen dataclasses (`@dataclass(frozen=True)`)
- **Actions**: Immutable intent descriptions
- **Update**: Pure function `(state, action) -> (new_state, effects)`
- **Effects**: I/O descriptions, not I/O itself
- **Store**: Dispatch/subscribe pattern
- **Widgets**: Receive `dispatch` callback, never own state

This enables:
- Unit tests without GUI
- Widget tests via `button.invoke()` (no mouse)
- 100% testable state logic

### 3. Standalone Execution

Every module MUST run without the Logger parent:
- `uv run main.py` launches GUI standalone
- Graceful degradation when parent absent
- Test before integration

### 4. Logger Integration

Modules integrate via `StubCodexSupervisor`. The Elm/Redux Store replaces VMC:

```
StubCodexSupervisor
    └─► ModuleRuntime (wraps Store)
            ├─► Store.dispatch() ─► update() ─► effects
            └─► UI subscribes to state
```

See `templates/runtime.template.py` for implementation pattern.

---

## Documentation Structure

### Required Files

| File | Purpose |
|------|---------|
| `ARCHITECTURE.md` | High-level pattern, data flow, folder map |
| `docs/TASKS.md` | Master task tracker (agents start here) |
| `docs/README.md` | Navigation |
| `docs/reference/mission.md` | Goals, non-goals |
| `docs/reference/design.md` | Coding standards, standalone test commands |
| `docs/specs/components.md` | Interface definitions with full code |
| `docs/tasks/phase*.md` | Individual phase tasks |
| `docs/tasks/testing_*.md` | Unit, integration, stress test tasks |

### Folder Structure

```
module_name/
├── ARCHITECTURE.md
├── main.py
├── config.py
├── runtime.py
├── core/                 # Elm/Redux (state, actions, effects, update, store)
├── infra/                # I/O boundary (effect_executor, command_handler)
├── [domain]/             # Module-specific (capture/, hardware/, etc.)
├── ui/                   # Tkinter widgets
├── tests/                # unit/, integration/, widget/
└── docs/                 # TASKS.md, README.md, reference/, specs/, tasks/
```

---

## TASKS.md Requirements

1. **Coding standards table** - asyncio, no docstrings, type hints
2. **Phase tables** - ID, Task, Status, Depends On, File to Create
3. **Inline code** - Full dataclass definitions, not vague descriptions
4. **Validation commands** - Copy-pasteable verification for each task

---

## Wiring Verification Checklist

Before marking a module complete:

```
Core Elm/Redux:
- [ ] Store.dispatch() calls update()
- [ ] update() returns (new_state, effects)
- [ ] EffectExecutor handles ALL effect types

UI:
- [ ] UI subscribes to Store
- [ ] Buttons dispatch actions (not mutate state)

Logger Integration:
- [ ] ModuleRuntime wraps Store
- [ ] handle_command() routes to dispatch()
- [ ] main.py uses StubCodexSupervisor

Standalone:
- [ ] `uv run main.py` works
- [ ] Button clicks cause visible state changes
```

---

## References

### Templates
- `templates/ARCHITECTURE.template.md` - Module architecture doc
- `templates/TASKS.template.md` - Task tracker
- `templates/runtime.template.py` - ModuleRuntime + main.py pattern
- `templates/state.template.py` - Elm/Redux core files

### Existing Infrastructure
- `rpi_logger/modules/base/` - Shared utilities (config, encoding, GUI base classes)
- `rpi_logger/modules/stub (codex)/vmc/` - StubCodexSupervisor, ModuleRuntime

### Example Module
- `rpi_logger/modules/Cameras_CSI2/` - Reference Elm/Redux implementation
