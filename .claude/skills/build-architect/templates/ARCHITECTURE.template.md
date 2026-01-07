# [ModuleName] Architecture

> Elm/Redux architecture for [brief description]

## Quick Start for AI Agents

1. **Check tasks**: [docs/TASKS.md](docs/TASKS.md)
2. **Read specs**: Start with `docs/specs/components.md`

---

## Data Flow

```
User Action (button click, menu)
    │
    ▼
dispatch(Action)              ◄── Immutable intent
    │
    ▼
update(state, action)         ◄── Pure function, no I/O
    │
    ├─► new_state             ◄── Frozen dataclass
    │       │
    │       ▼
    │   Subscribers           ◄── UI re-renders
    │
    └─► effects[]             ◄── I/O descriptions
            │
            ▼
    EffectExecutor            ◄── I/O boundary
            │
            └─► dispatch(ResultAction)
```

---

## Standalone Execution

```bash
cd /path/to/[ModuleName]
uv run main.py
```

---

## Folder Structure

```
[ModuleName]/
├── ARCHITECTURE.md       ← This file
├── main.py               ← Entry point
├── config.py             ← Configuration dataclass
├── runtime.py            ← ModuleRuntime (wraps Store)
│
├── core/                 ← Pure state machine (100% testable)
│   ├── state.py          ← Frozen dataclasses
│   ├── actions.py        ← Action types
│   ├── effects.py        ← Effect descriptions
│   ├── update.py         ← Pure reducer
│   └── store.py          ← Dispatch/subscribe
│
├── infra/                ← I/O boundary
│   ├── effect_executor.py
│   └── command_handler.py
│
├── [domain]/             ← Module-specific
│   └── ...
│
├── ui/                   ← Stateless widgets
│   ├── renderer.py
│   └── widgets/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── widget/
│
└── docs/
    ├── TASKS.md
    └── ...
```

---

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| State management | Elm/Redux | Testable, single source of truth |
| State type | Frozen dataclass | Immutability |
| Update function | Pure | 100% testable, no mocks |
| Side effects | Effect descriptions | Decouple logic from I/O |
| UI pattern | Subscriber | Stateless widgets |

---

## Logger Integration

Module integrates via `StubCodexSupervisor`:
- `ModuleRuntime.start()` initializes Store
- `ModuleRuntime.handle_command()` routes to `Store.dispatch()`
- UI subscribes to Store for re-renders

---

*Last updated: [DATE]*
